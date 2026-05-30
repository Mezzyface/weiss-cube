"""
Pre-normalization audit.
Checks everything that needs to be clean before building card_profiles.

Sections:
  1. JP character residuals
  2. Ability marker consistency
  3. Trait / name placeholder consistency
  4. Fullwidth character residuals
  5. CX COMBO formatting
  6. Numeric field sanity (level/cost/power/soul)
  7. Type / color / trigger field validity
  8. Blank / null text coverage
  9. Duplicate card numbers
 10. Summary + pass/fail
"""
import sqlite3, re, sys
sys.stdout.reconfigure(encoding='utf-8')

DB = 'weiss_cards.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

PASS = []
WARN = []
FAIL = []

def ok(msg):   PASS.append(msg); print(f'  ✓  {msg}')
def warn(msg): WARN.append(msg); print(f'  ⚠  {msg}')
def fail(msg): FAIL.append(msg); print(f'  ✗  {msg}')

# ── 1. JP character residuals ─────────────────────────────────────────────────
print('\n── 1. JP character residuals ──────────────────────────────────────────')
JP_RE = re.compile(r'[ぁ-んァ-ン一-鿿々〆〇]')

c.execute("SELECT COUNT(*) FROM cards WHERE lang='jp' AND card_text_en IS NOT NULL AND card_text_en != ''")
jp_with_en = c.fetchone()[0]
c.execute("SELECT card_no, card_text_en FROM cards WHERE lang='jp' AND card_text_en IS NOT NULL")
jp_rows = [(r[0], r[1]) for r in c.fetchall() if r[1]]
jp_remaining = [(cn, en) for cn, en in jp_rows if JP_RE.search(en)]

if not jp_remaining:
    ok(f'All {jp_with_en:,} JP cards have clean EN text (0 JP chars)')
else:
    fail(f'{len(jp_remaining):,} JP cards still contain Japanese characters')
    for cn, en in jp_remaining[:5]:
        print(f'       [{cn}] {en[:100]}')

c.execute("SELECT COUNT(*) FROM cards WHERE lang='jp' AND (card_text_en IS NULL OR card_text_en='')")
jp_blank = c.fetchone()[0]
if jp_blank == 0:
    ok('All JP cards have non-empty card_text_en')
else:
    warn(f'{jp_blank:,} JP cards have null/empty card_text_en')

# ── 2. Ability marker consistency ─────────────────────────────────────────────
print('\n── 2. Ability marker consistency ──────────────────────────────────────')
FW_BRACKET = re.compile(r'【|】')
OLD_JP_MARKERS = re.compile(r'【自】|【永】|【起】|【カウンター】')

c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en LIKE '%【%'")
fw_count = c.fetchone()[0]
if fw_count == 0:
    ok('No fullwidth 【 】 brackets in any card_text_en')
else:
    fail(f'{fw_count:,} cards still have 【 】 brackets in card_text_en')
    c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en LIKE '%【%' LIMIT 5")
    for r in c.fetchall():
        print(f'       [{r[0]}] {r[1][:100]}')

# Check [AUTO]/[CONT]/[ACT] presence vs card type
c.execute("SELECT COUNT(*) FROM cards WHERE type='Character' AND card_text_en IS NOT NULL AND card_text_en != ''")
char_with_text = c.fetchone()[0]
c.execute("""SELECT COUNT(*) FROM cards
             WHERE type='Character' AND card_text_en IS NOT NULL AND card_text_en != ''
             AND card_text_en NOT LIKE '%[AUTO]%' AND card_text_en NOT LIKE '%[CONT]%'
             AND card_text_en NOT LIKE '%[ACT]%' AND card_text_en NOT LIKE '%[COUNTER]%'
             AND card_text_en NOT LIKE '%CX COMBO%'""")
no_marker = c.fetchone()[0]
# Some characters have no abilities (vanilla) - that's fine
# So we just report as info
print(f'  ℹ  Characters with text but no ability marker: {no_marker:,} / {char_with_text:,} (likely vanilla)')

# ── 3. Trait / name placeholder consistency ───────────────────────────────────
print('\n── 3. Trait / name placeholder consistency ─────────────────────────────')
# Raw JP trait brackets should not appear in EN text
c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en LIKE '%《%' OR card_text_en LIKE '%》%'")
raw_jp_traits = c.fetchone()[0]
if raw_jp_traits == 0:
    ok('No raw JP trait brackets 《》 in card_text_en')
else:
    fail(f'{raw_jp_traits:,} cards still have raw 《》 trait brackets')
    c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en LIKE '%《%' LIMIT 5")
    for r in c.fetchall():
        print(f'       [{r[0]}] {r[1][:100]}')

# Raw JP name brackets
c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en LIKE '%「%' OR card_text_en LIKE '%」%'")
raw_jp_names = c.fetchone()[0]
if raw_jp_names == 0:
    ok('No raw JP name brackets 「」 in card_text_en')
else:
    fail(f'{raw_jp_names:,} cards still have raw 「」 name brackets')

# EN trait notation still present (should be ::TRAIT::)
c.execute("SELECT COUNT(*) FROM cards WHERE lang='en' AND card_text_en LIKE '%<<%' AND card_text_en NOT LIKE '%::TRAIT::%'")
en_raw_trait = c.fetchone()[0]
if en_raw_trait == 0:
    ok('No unconverted <<>> trait brackets in EN lang cards')
else:
    warn(f'{en_raw_trait:,} EN cards have <<>> but no ::TRAIT:: (may be intentional)')

# ::TRAIT:: count
c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en LIKE '%::TRAIT::%'")
trait_count = c.fetchone()[0]
ok(f'{trait_count:,} cards use ::TRAIT:: placeholder')

c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en LIKE '%[CHARACTER]%'")
char_count = c.fetchone()[0]
ok(f'{char_count:,} cards use [CHARACTER] placeholder')

# ── 4. Fullwidth character residuals ─────────────────────────────────────────
print('\n── 4. Fullwidth character residuals ────────────────────────────────────')
FW_RE = re.compile(r'[！-～]|＋|－|　')  # fullwidth punctuation / space

c.execute("SELECT card_text_en FROM cards WHERE card_text_en IS NOT NULL LIMIT 100000")
all_texts = [r[0] for r in c.fetchall() if r[0]]
fw_texts = [t for t in all_texts if FW_RE.search(t)]
if len(fw_texts) == 0:
    ok('No fullwidth ASCII characters in card_text_en')
elif len(fw_texts) < 100:
    warn(f'{len(fw_texts)} cards have residual fullwidth characters (minor)')
else:
    fail(f'{len(fw_texts):,} cards have residual fullwidth characters')

# ── 5. CX COMBO formatting ────────────────────────────────────────────────────
print('\n── 5. CX COMBO formatting ───────────────────────────────────────────────')
bad_cx = re.compile(r'CXコンボ|CXCombo|CXCOMBO|\[CX\s+COMBO\]', re.I)
c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en IS NOT NULL")
total_with_text = c.fetchone()[0]
c.execute("SELECT card_text_en FROM cards WHERE card_text_en IS NOT NULL")
cx_bad = sum(1 for r in c.fetchall() if r[0] and bad_cx.search(r[0]))
if cx_bad == 0:
    ok('CX COMBO consistently formatted in all cards')
else:
    fail(f'{cx_bad:,} cards have non-standard CX COMBO formatting')

c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en LIKE '%CX COMBO%'")
cx_good = c.fetchone()[0]
ok(f'{cx_good:,} cards use standard "CX COMBO" keyword')

# ── 6. Numeric field sanity ───────────────────────────────────────────────────
print('\n── 6. Numeric field sanity ─────────────────────────────────────────────')
c.execute("SELECT COUNT(*) FROM cards WHERE type='Character' AND (level IS NULL OR level NOT BETWEEN 0 AND 3)")
bad_level = c.fetchone()[0]
if bad_level == 0:
    ok('All Character cards have level 0–3')
else:
    fail(f'{bad_level:,} Character cards have invalid level')

c.execute("SELECT COUNT(*) FROM cards WHERE type='Character' AND (cost IS NULL OR cost < 0 OR cost > 10)")
bad_cost = c.fetchone()[0]
if bad_cost == 0:
    ok('All Character cards have cost 0–10')
else:
    warn(f'{bad_cost:,} Character cards have unusual cost (>10 or NULL)')

c.execute("SELECT COUNT(*) FROM cards WHERE type='Character' AND (power IS NULL OR power < 0 OR power > 25000)")
bad_power = c.fetchone()[0]
if bad_power == 0:
    ok('All Character cards have power 0–25000')
else:
    warn(f'{bad_power:,} Character cards have unusual power')

c.execute("SELECT COUNT(*) FROM cards WHERE type='Character' AND soul IS NOT NULL AND soul NOT BETWEEN 0 AND 4")
bad_soul = c.fetchone()[0]
if bad_soul == 0:
    ok('All Character cards have soul 0–4 (NULLs ignored)')
else:
    warn(f'{bad_soul:,} Character cards have soul outside 0–4')

# ── 7. Type / color / trigger field validity ──────────────────────────────────
print('\n── 7. Type / color / trigger field validity ────────────────────────────')
VALID_TYPES    = {'Character', 'Event', 'Climax'}
VALID_COLORS   = {'Red', 'Blue', 'Yellow', 'Green', 'Purple'}
VALID_TRIGGERS = {'None', 'Soul', '2 Soul', 'Salvage', 'Book', 'Door', 'Shot',
                  'Treasure', 'Standby', 'Gate', 'Choice', 'Soul Bounce',
                  'Return', 'Comeback', 'Draw', 'Pool', 'Bounce', None, ''}

c.execute("SELECT DISTINCT type FROM cards WHERE type NOT IN ('Character','Event','Climax') AND type IS NOT NULL")
bad_types = [r[0] for r in c.fetchall()]
if not bad_types:
    ok('All card types are valid (Character / Event / Climax)')
else:
    fail(f'Unknown type values: {bad_types}')

c.execute("SELECT DISTINCT color FROM cards WHERE color NOT IN ('Red','Blue','Yellow','Green','Purple') AND color IS NOT NULL AND color != ''")
bad_colors = [r[0] for r in c.fetchall()]
if not bad_colors:
    ok('All card colors are valid (Red/Blue/Yellow/Green/Purple)')
else:
    warn(f'Unknown color values: {bad_colors[:10]}')

c.execute("SELECT DISTINCT triggers FROM cards")
all_triggers = {r[0] for r in c.fetchall()}
bad_triggers = all_triggers - VALID_TRIGGERS
if not bad_triggers:
    ok('All trigger values are standard')
else:
    warn(f'Non-standard trigger values: {bad_triggers}')

# ── 8. Text coverage ──────────────────────────────────────────────────────────
print('\n── 8. Text coverage ────────────────────────────────────────────────────')
c.execute("SELECT COUNT(*) FROM cards")
total = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM cards WHERE card_text_en IS NOT NULL AND card_text_en != ''")
has_en = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM cards WHERE (card_text_en IS NULL OR card_text_en='') AND type != 'Climax'")
no_text_nonclimaz = c.fetchone()[0]

pct = 100 * has_en / total
if pct >= 98:
    ok(f'{has_en:,} / {total:,} cards ({pct:.1f}%) have EN text')
elif pct >= 90:
    warn(f'{has_en:,} / {total:,} cards ({pct:.1f}%) have EN text')
else:
    fail(f'Only {has_en:,} / {total:,} cards ({pct:.1f}%) have EN text')

if no_text_nonclimaz == 0:
    ok('All non-Climax cards have card_text_en')
else:
    warn(f'{no_text_nonclimaz:,} non-Climax cards have no EN text')

# ── 9. Duplicate card numbers ─────────────────────────────────────────────────
print('\n── 9. Duplicate card numbers ───────────────────────────────────────────')
c.execute("SELECT card_no, COUNT(*) as n FROM cards GROUP BY card_no HAVING n > 1")
dupes = c.fetchall()
if not dupes:
    ok('No duplicate card_no values')
else:
    warn(f'{len(dupes):,} card_no values appear more than once (alt-arts / SP expected)')
    for cn, n in dupes[:5]:
        print(f'       {cn} × {n}')

# ── 10. Summary ───────────────────────────────────────────────────────────────
print('\n── Summary ─────────────────────────────────────────────────────────────')
print(f'  PASS : {len(PASS)}')
print(f'  WARN : {len(WARN)}')
print(f'  FAIL : {len(FAIL)}')
if not FAIL:
    print('\n  ✅  All checks passed — ready for normalization.')
else:
    print('\n  ❌  Fix the FAIL items above before running normalization.')

conn.close()
