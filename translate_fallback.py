"""
Fallback translation for JP cards that still have Japanese characters
in card_text_en after the rule-based translate_normalize.py pass.

Strategy:
  1. Find JP cards where card_text_en still contains hiragana/katakana/kanji
  2. Translate card_text_jp_raw via Google Translate (deep_translator)
  3. Run the same normalize() pass from translate_normalize on the result
  4. Write back to card_text_en

Rate-limits: Google Translate free tier is ~5 req/s.
We batch to 500 chars per request and sleep 0.2s between calls.

Usage:
    python translate_fallback.py [--limit N] [--dry-run]
    --limit N    only process N cards (useful for testing)
    --dry-run    translate but don't write to DB
"""
import sqlite3, sys, re, time, importlib
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'weiss_cards.db'
DRY_RUN = '--dry-run' in sys.argv
LIMIT = None
for i, arg in enumerate(sys.argv):
    if arg == '--limit' and i + 1 < len(sys.argv):
        LIMIT = int(sys.argv[i + 1])

# ── Import translate_normalize helpers ───────────────────────────────────────
# Reuse the normalize() function and MULTI_TRAIT pattern
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    'tn', pathlib.Path(__file__).parent / 'translate_normalize.py')
tn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tn)

normalize  = tn.normalize
MULTI_TRAIT = tn.MULTI_TRAIT

# ── Translator setup ─────────────────────────────────────────────────────────
from deep_translator import GoogleTranslator

translator = GoogleTranslator(source='ja', target='en')

# ── Detect remaining JP characters ───────────────────────────────────────────
JP_RE = re.compile(r'[ぁ-んァ-ン一-鿿々〆〇]')

# ── WS-specific post-processing for Google Translate output ──────────────────
# Google Translate sometimes uses different terminology; normalize to WS EN.

WS_TERM_MAP = [
    # Ability markers
    (re.compile(r'\[Automatic\]|\[Auto\]|\bAUTO\b',   re.I), '[AUTO]'),
    (re.compile(r'\[Permanent\]|\[Cont\]|\bCONT\b',   re.I), '[CONT]'),
    (re.compile(r'\[Activated\]|\[Act\]|\bACT\b(?!\w)',re.I), '[ACT]'),
    (re.compile(r'\[Counter\]',                         re.I), '[COUNTER]'),
    (re.compile(r'CX\s*combo|CX\s*Combo|cx\s*combo',   re.I), 'CX COMBO'),
    # Zone names
    (re.compile(r'\bwaiting\s+room\b',                  re.I), 'waiting room'),
    (re.compile(r'\bclimaz\b|\bclimax\s+area\b',        re.I), 'climax area'),
    (re.compile(r'\bhand\s+deck\b|\bdeck\s+deck\b',     re.I), 'deck'),
    (re.compile(r'\blibrary\b',                         re.I), 'deck'),
    (re.compile(r'\bstage\s+zone\b',                    re.I), 'stage'),
    # Keywords
    (re.compile(r'\bEncore\b'),                                 'ENCORE'),
    (re.compile(r'\bBrainstorm\b|\bConcentration\b|\bFocus\b'), 'BRAINSTORM'),
    (re.compile(r'\bBond\b/'),                                  'BOND/'),
    (re.compile(r'\bExperience\b'),                             'EXPERIENCE'),
    (re.compile(r'\bChange\b(?=\s)'),                           'CHANGE'),
    (re.compile(r'\bAlarm\b'),                                  'ALARM'),
    (re.compile(r'\bBackup\b'),                                 'BACKUP'),
    (re.compile(r'\bSupport\b'),                                'SUPPORT'),
    (re.compile(r'\bRecollection\b'),                           'RECOLLECTION'),
    # Card states
    (re.compile(r'\brest\s+state\b|\brest\b(?=\s+(it|this|the))',re.I), '[REST]'),
    (re.compile(r'\bstand\s+state\b|\bstand\s+it\b',            re.I), '[STAND]'),
    (re.compile(r'\breverse\s+state\b|\breverse\s+it\b',        re.I), '[REVERSE]'),
    # Trait and name placeholders (Google may translate them differently)
    (re.compile(r'«[^»]+»|<[^>]+>'),                            '::TRAIT::'),
    (re.compile(r'【([^】]+)】'),                               r'[\1]'),
    # Cleanup
    (re.compile(r'  +'),                                        ' '),
    (re.compile(r' ([.,)])'),                                   r'\1'),
]

# Preserve our ::TRAIT:: and [CHARACTER] placeholders through translation
# by replacing them with tokens Google won't touch, then restoring
_TRAIT_TOKEN   = 'XXTRAIT XX'
_CHAR_TOKEN    = 'XXCHARXX'
_TRAIT_RESTORE = re.compile(r'X\s*X\s*TRAIT\s*X\s*X', re.I)
_CHAR_RESTORE  = re.compile(r'X\s*X\s*CHAR\s*X\s*X',  re.I)


def protect_placeholders(text: str) -> str:
    text = text.replace('::TRAIT::', _TRAIT_TOKEN)
    text = text.replace('[CHARACTER]', _CHAR_TOKEN)
    return text


def restore_placeholders(text: str) -> str:
    text = _TRAIT_RESTORE.sub('::TRAIT::', text)
    text = _CHAR_RESTORE.sub('[CHARACTER]', text)
    return text


def post_process_gt(text: str) -> str:
    """Normalize Google Translate output to WS EN format."""
    text = restore_placeholders(text)
    for pat, repl in WS_TERM_MAP:
        text = pat.sub(repl, text)
    return text.strip()


# ── Translate one card's JP text ──────────────────────────────────────────────

def translate_card(jp_raw: str) -> str | None:
    """
    Translate jp_raw via Google Translate.
    Handles texts > 5000 chars by chunking on ability boundaries.
    Returns English text or None on failure.
    """
    if not jp_raw or not jp_raw.strip():
        return None

    # Pre-process: replace traits 《》 and names 「」 with tokens GT won't mangle
    text = re.sub(r'《[^》]+》', _TRAIT_TOKEN, jp_raw)
    text = re.sub(r'「[^」]{1,60}」', _CHAR_TOKEN, text)
    text = MULTI_TRAIT.sub(_TRAIT_TOKEN, text)

    # Split on ability boundaries if text is long
    MAX_LEN = 4500
    if len(text) <= MAX_LEN:
        chunks = [text]
    else:
        # Split on 【自】【永】【起】 boundary markers
        parts = re.split(r'(?=【(?:自|永|起|AUTO|CONT|ACT)】)', text)
        chunks = []
        current = ''
        for p in parts:
            if len(current) + len(p) <= MAX_LEN:
                current += p
            else:
                if current:
                    chunks.append(current)
                current = p
        if current:
            chunks.append(current)

    translated_parts = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        # If chunk has no JP at all, keep as-is
        if not JP_RE.search(chunk) and not any(c in chunk for c in '【】《》「」'):
            translated_parts.append(chunk)
            continue
        try:
            result = translator.translate(protect_placeholders(chunk))
            if result:
                translated_parts.append(result)
        except Exception as e:
            # On error, fall back to the protected chunk (better than nothing)
            translated_parts.append(protect_placeholders(chunk))
        time.sleep(0.22)  # ~4.5 req/s to stay under free-tier limit

    if not translated_parts:
        return None

    combined = ' '.join(translated_parts)
    combined = post_process_gt(combined)
    combined = normalize(combined, apply_trait_norm=False)
    return combined if combined.strip() else None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Find JP cards still containing Japanese in card_text_en
    c.execute("""
        SELECT card_no, card_text_jp_raw, card_text_en
        FROM cards
        WHERE lang='jp'
          AND card_text_jp_raw IS NOT NULL AND card_text_jp_raw != ''
          AND card_text_en IS NOT NULL
    """)
    all_rows = c.fetchall()

    rows = [(cn, jp, en) for cn, jp, en in all_rows
            if en and JP_RE.search(en)]

    print(f'JP cards with remaining Japanese in EN text: {len(rows):,}')
    if LIMIT:
        rows = rows[:LIMIT]
        print(f'Processing first {LIMIT} (--limit flag)')

    if not rows:
        print('Nothing to do.')
        conn.close()
        return

    done = 0
    failed = 0
    for card_no, jp_raw, old_en in rows:
        new_en = translate_card(jp_raw)
        if new_en and new_en.strip():
            if not DRY_RUN:
                conn.execute(
                    'UPDATE cards SET card_text_en=? WHERE card_no=?',
                    (new_en, card_no))
            done += 1
        else:
            failed += 1

        if done % 100 == 0 and done > 0:
            if not DRY_RUN:
                conn.commit()
            remaining = len(rows) - done - failed
            print(f'  {done:,} translated, {failed} failed, {remaining:,} remaining...')

    if not DRY_RUN:
        conn.commit()
    conn.close()

    print(f'\nDone. Translated: {done:,}  Failed: {failed:,}')
    if DRY_RUN:
        print('(dry-run — nothing written to DB)')

    # Quick quality check
    if not DRY_RUN:
        conn2 = sqlite3.connect(DB_PATH)
        c2 = conn2.cursor()
        c2.execute("SELECT card_text_en FROM cards WHERE lang='jp' AND card_text_en IS NOT NULL")
        texts = [r[0] for r in c2.fetchall() if r[0]]
        remaining_jp = sum(1 for t in texts if JP_RE.search(t))
        print(f'\nResidual JP chars in EN text: {remaining_jp:,} / {len(texts):,} '
              f'({100*remaining_jp/max(1,len(texts)):.1f}%)')
        conn2.close()


if __name__ == '__main__':
    main()
