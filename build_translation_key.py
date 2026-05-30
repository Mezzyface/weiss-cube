"""
Build a JP→EN translation key from cards that exist in both languages.

EN card numbers use an 'E' prefix on the serial: W116-E029 (EN) ↔ W116-029 (JP)
Strategy:
  1. Find all EN cards in DB (lang='en')
  2. For each, derive the JP card number (strip 'E' from serial)
  3. Join to JP card (lang='jp') on that derived number
  4. Collect (jp_text_segment, en_text_segment) pairs
  5. Build phrase-level translation map via sentence alignment
  6. Apply map to untranslated JP cards → populate card_text_en

Output: data/translation_key.json  +  DB updated with auto-translated EN text
"""
import sys, re, json, sqlite3
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH  = Path(__file__).parent / 'weiss_cards.db'
KEY_PATH = Path(__file__).parent / 'data' / 'translation_key.json'

# ── Card number mapping ────────────────────────────────────────────────────

def en_to_jp_no(en_no):
    """
    F35/W120-E052  →  F35/W120-052
    YRC/W116-E029  →  YRC/W116-029
    WS/S80-E001    →  WS/S80-001
    If no 'E' in serial, return None (can't map).
    """
    m = re.match(r'^(.*?/)([A-Z]{1,2}\d{2,3})-E(\d+\w*)$', en_no)
    if m:
        return f'{m.group(1)}{m.group(2)}-{m.group(3)}'
    # Some sets: ABC/W116-E029SP → ABC/W116-029SP
    m2 = re.match(r'^(.*?/[A-Z]{1,2}\d{2,3})-E(\d+\w*)$', en_no)
    if m2:
        return f'{m2.group(1)}-{m2.group(2)}'
    return None


# ── Text splitting ─────────────────────────────────────────────────────────

def split_abilities(text):
    """
    Split card text into individual ability segments.
    Abilities start with 【AUTO】/【CONT】/【ACT】 or [AUTO]/[CONT] etc.
    """
    if not text:
        return []
    # Split on ability markers
    parts = re.split(r'(?=【(?:AUTO|CONT|ACT|S|C|A)】|\[(?:AUTO|CONT|ACT|S|C|A)\])', text.strip())
    return [p.strip() for p in parts if p.strip()]


def split_sentences(text):
    """Split into sentences on '.', '。', newlines."""
    if not text:
        return []
    parts = re.split(r'[.。\n]+', text)
    return [p.strip() for p in parts if len(p.strip()) > 5]


# ── Alignment ──────────────────────────────────────────────────────────────

def align_sentences(jp_sents, en_sents):
    """
    Simple 1:1 alignment when counts match.
    Returns list of (jp, en) pairs.
    """
    if len(jp_sents) == len(en_sents):
        return list(zip(jp_sents, en_sents))
    # Fallback: just pair ability blocks
    pairs = []
    for j, e in zip(jp_sents, en_sents):
        pairs.append((j, e))
    return pairs


def align_abilities(jp_text, en_text):
    """Split both into abilities and align 1:1 when counts match."""
    jp_abs = split_abilities(jp_text)
    en_abs = split_abilities(en_text)
    if len(jp_abs) == len(en_abs) and jp_abs:
        return list(zip(jp_abs, en_abs))
    # Fall back to full-text pair
    if jp_text and en_text:
        return [(jp_text.strip(), en_text.strip())]
    return []


# ── Phrase extraction ──────────────────────────────────────────────────────

# Common WS phrases to extract explicitly
JP_PHRASE_PATTERNS = [
    # Zones
    (r'手札', 'your hand'),
    (r'舞台', 'stage'),
    (r'控え室', 'waiting room'),
    (r'山札', 'deck'),
    (r'クロック', 'clock'),
    (r'ストック', 'stock'),
    (r'思い出', 'memory'),
    (r'レベル置き場', 'level zone'),
    (r'バトル領域', 'battle area'),
    (r'クライマックス置き場', 'climax zone'),
    # Actions
    (r'手札に加える', 'add it to your hand'),
    (r'控え室に置く', 'put it in your waiting room'),
    (r'山札の上に置く', 'put it on top of your deck'),
    (r'クロックに置く', 'put it in your clock'),
    (r'ストックに置く', 'put it in your stock'),
    (r'思い出にする', 'send it to memory'),
    (r'レストする', 'rest this'),
    (r'スタンドする', 'stand this'),
    (r'リバースする', 'reverse this'),
    # Triggers
    (r'自動効果', '[AUTO]'),
    (r'継続効果', '[CONT]'),
    (r'起動効果', '[ACT]'),
    (r'【自】', '[AUTO]'),
    (r'【永】', '[CONT]'),
    (r'【起】', '[ACT]'),
    # WS specific
    (r'バトル相手', 'the battle opponent of this'),
    (r'フロントアタック', 'front attack'),
    (r'サイドアタック', 'side attack'),
    (r'ダイレクトアタック', 'direct attack'),
    (r'アンコール', 'encore'),
    (r'ダメージを与える', 'deal damage to your opponent'),
    (r'キャンセル', 'cancel'),
]


def extract_phrase_pairs(jp_text, en_text):
    """Extract sub-sentence phrase pairs using regex patterns."""
    pairs = []

    # Align abilities first
    ability_pairs = align_abilities(jp_text, en_text)
    for jp_ab, en_ab in ability_pairs:
        # Sentence-level alignment within each ability
        jp_sents = split_sentences(jp_ab)
        en_sents = split_sentences(en_ab)
        sentence_pairs = align_sentences(jp_sents, en_sents)
        pairs.extend(sentence_pairs)

    return pairs


# ── Main ───────────────────────────────────────────────────────────────────

def build_key():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Get all EN cards
    c.execute("SELECT card_no, card_text_en FROM cards WHERE lang='en' AND card_text_en IS NOT NULL")
    en_cards = {row[0]: row[1] for row in c.fetchall()}
    print(f'EN cards with text: {len(en_cards):,}')

    # 2. Match to JP cards
    matches = 0
    phrase_pairs = []
    full_text_pairs = []  # (jp_no, en_no, jp_text, en_text)

    for en_no, en_text in en_cards.items():
        jp_no = en_to_jp_no(en_no)
        if not jp_no:
            continue
        c.execute("SELECT card_text_jp FROM cards WHERE card_no=? AND lang='jp'", (jp_no,))
        row = c.fetchone()
        if row and row[0]:
            matches += 1
            jp_text = row[0]
            full_text_pairs.append((jp_no, en_no, jp_text, en_text))
            phrase_pairs.extend(extract_phrase_pairs(jp_text, en_text))

    print(f'Matched pairs: {matches:,}')
    print(f'Raw phrase pairs extracted: {len(phrase_pairs):,}')

    # 3. Build frequency-filtered translation map
    # Count how often each (jp, en) pair appears
    pair_counts = Counter(phrase_pairs)

    # Keep pairs that appear at least twice (consistent translation)
    # and where jp segment is meaningful (>3 chars)
    translation_map = {}
    for (jp, en), count in pair_counts.most_common():
        jp_clean = jp.strip()
        en_clean = en.strip()
        if (len(jp_clean) > 3 and len(en_clean) > 3
                and jp_clean not in translation_map
                and count >= 2):
            translation_map[jp_clean] = en_clean

    print(f'Translation key entries (freq >= 2): {len(translation_map):,}')

    # Also add hardcoded phrase patterns
    hardcoded = {}
    for jp_pat, en_val in JP_PHRASE_PATTERNS:
        hardcoded[jp_pat] = en_val

    # 4. Save key
    key_data = {
        'phrase_map':  translation_map,
        'hardcoded':   hardcoded,
        'pair_count':  matches,
        'stats': {
            'en_cards':     len(en_cards),
            'matched':      matches,
            'phrase_pairs': len(phrase_pairs),
            'map_entries':  len(translation_map),
        }
    }
    KEY_PATH.write_text(json.dumps(key_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved key to {KEY_PATH}')

    # Show top 20 most common translations
    print('\nTop 20 phrase translations:')
    for (jp, en), cnt in pair_counts.most_common(20):
        print(f'  [{cnt:4d}x] {jp[:50]} → {en[:60]}')

    conn.close()
    return translation_map, hardcoded


def apply_translation(jp_text, phrase_map, hardcoded):
    """
    Apply translation key to a JP text string.
    Returns best-effort English translation.
    """
    if not jp_text:
        return None

    result = jp_text

    # Apply hardcoded replacements first (structural markers)
    for jp_pat, en_val in hardcoded.items():
        result = result.replace(jp_pat, en_val)

    # Apply learned phrase map (longest match first)
    for jp_phrase in sorted(phrase_map.keys(), key=len, reverse=True):
        if jp_phrase in result:
            result = result.replace(jp_phrase, phrase_map[jp_phrase])

    return result.strip() if result.strip() else None


def apply_to_db():
    """Apply translation key to all JP-only cards missing EN text."""
    if not KEY_PATH.exists():
        print('No key found. Run build_key() first.')
        return

    key_data = json.loads(KEY_PATH.read_text(encoding='utf-8'))
    phrase_map = key_data['phrase_map']
    hardcoded  = key_data['hardcoded']

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # JP cards with no EN text equivalent
    c.execute("""
        SELECT card_no, card_text_jp
        FROM cards
        WHERE lang='jp'
          AND card_text_jp IS NOT NULL
          AND (card_text_en IS NULL OR card_text_en = '')
    """)
    rows = c.fetchall()
    print(f'JP cards needing translation: {len(rows):,}')

    translated = 0
    for card_no, jp_text in rows:
        en_text = apply_translation(jp_text, phrase_map, hardcoded)
        if en_text and en_text != jp_text:
            c.execute("UPDATE cards SET card_text_en=? WHERE card_no=?",
                      (en_text, card_no))
            translated += 1

    conn.commit()
    conn.close()
    print(f'Translated {translated:,} cards.')


if __name__ == '__main__':
    print('=== Building translation key ===')
    tm, hc = build_key()
    print('\n=== Applying translations to JP-only cards ===')
    apply_to_db()
