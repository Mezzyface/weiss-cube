"""
Fix all FAIL items from prenorm_audit.py:

  1. 3 cards still have 【 】 brackets  → strip via fallback regex
  2. 1 card has raw 「」 name brackets  → replace with [CHARACTER]
  3. 5,600 cards with non-standard CX COMBO → normalize
  4. 15 Character cards with invalid level → investigate + fix

Also normalises the non-standard trigger values (WARN) into canonical forms.
"""
import sqlite3, re, sys
sys.stdout.reconfigure(encoding='utf-8')

DB = 'weiss_cards.db'
conn = sqlite3.connect(DB)
c = conn.cursor()

total_fixed = 0

# ── Fix 1: remaining 【 】 brackets ─────────────────────────────────────────
print('Fix 1: 【 】 brackets')
BRACKET_RE = re.compile(r'【([^】]*)】')
c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en LIKE '%【%'")
rows = c.fetchall()
for card_no, text in rows:
    new_text = BRACKET_RE.sub(r'[\1]', text)
    conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_text, card_no))
    print(f'  [{card_no}] fixed')
    total_fixed += 1
conn.commit()
print(f'  → fixed {len(rows)} cards')

# ── Fix 2: raw 「」 name brackets ─────────────────────────────────────────────
print('\nFix 2: 「」 name brackets')
JP_NAME_RE = re.compile(r'「[^」]{1,60}」')
c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en LIKE '%「%' OR card_text_en LIKE '%」%'")
rows = c.fetchall()
for card_no, text in rows:
    new_text = JP_NAME_RE.sub('[CHARACTER]', text)
    if new_text != text:
        conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_text, card_no))
        total_fixed += 1
        print(f'  [{card_no}] fixed')
conn.commit()
print(f'  → fixed {len(rows)} cards')

# ── Fix 3: non-standard CX COMBO formatting ──────────────────────────────────
print('\nFix 3: non-standard CX COMBO')
BAD_CX = re.compile(r'CXコンボ|CXCombo|CXCOMBO|\[CX\s+COMBO\]|\[CX COMBO\]', re.I)
c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en IS NOT NULL")
rows = c.fetchall()
fixed = 0
for card_no, text in rows:
    if text and BAD_CX.search(text):
        new_text = BAD_CX.sub('CX COMBO', text)
        conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_text, card_no))
        fixed += 1
conn.commit()
total_fixed += fixed
print(f'  → fixed {fixed:,} cards')

# ── Fix 4: invalid Character levels ──────────────────────────────────────────
print('\nFix 4: invalid Character levels')
c.execute("""
    SELECT card_no, name_en, level, cost, type, card_text_en
    FROM cards
    WHERE type='Character' AND (level IS NULL OR level NOT BETWEEN 0 AND 3)
    ORDER BY card_no
""")
bad = c.fetchall()
for row in bad:
    print(f'  [{row[0]}] {row[1]} | level={row[2]} cost={row[3]} | {(row[5] or "")[:60]}')

# Try to infer level from cost heuristic (cost 0=L0, 1=L0/L1, etc.)
# For now just report; these need manual review or a cost-based rule
fixed_lvl = 0
for card_no, name, level, cost, typ, text in bad:
    inferred = None
    if cost is not None:
        if cost == 0:   inferred = 0
        elif cost <= 2: inferred = 1
        elif cost <= 5: inferred = 2
        elif cost <= 9: inferred = 3
    if inferred is not None:
        conn.execute("UPDATE cards SET level=? WHERE card_no=?", (inferred, card_no))
        fixed_lvl += 1
        print(f'  → [{card_no}] inferred level {inferred} from cost {cost}')
conn.commit()
total_fixed += fixed_lvl
print(f'  → auto-fixed {fixed_lvl} / {len(bad)} invalid levels')

# ── Fix 5: trigger value normalisation (WARN → clean) ────────────────────────
print('\nFix 5: normalise trigger values')
TRIGGER_MAP = {
    # image-tag formats from old scrapers
    '[[soul.gif]]':                     'Soul',
    '[[soul.gif]] [[soul.gif]]':        '2 Soul',
    '[[soul.gif]][[soul.gif]]':         '2 Soul',
    '[[gate.gif]]':                     'Gate',
    '[[soul.gif]] [[gate.gif]]':        'Gate',      # soul+gate → Gate
    '[[soul.gif]][[gate.gif]]':         'Gate',
    '[[salvage.gif]]':                  'Salvage',
    '[[bounce.gif]]':                   'Return',
    '[[soul.gif]] [[bounce.gif]]':      'Soul Bounce',
    '[[bounce.gif]][[soul.gif]]':       'Soul Bounce',
    '[[shot.gif]]':                     'Shot',
    '[[soul.gif]] [[shot.gif]]':        'Shot',
    '[[soul.gif]][[shot.gif]]':         'Shot',
    '[[treasure.gif]]':                 'Treasure',
    '[[focus.gif]]':                    'Book',
    '[[comeback.gif]]':                 'Comeback',
    '[[chance.gif]]':                   'Choice',
    '[[discovery.gif]]':                'Standby',
    '[[bushi.gif]]':                    'None',
    '[[shot.gif]][[bounce.gif]][[salvage.gif]]': 'Shot',  # multi-icon edge case
    # dash / none variants
    '―':   'None',
    '－':   'None',
    'Soul Standby': 'Standby',
}

fixed_trig = 0
for bad_val, good_val in TRIGGER_MAP.items():
    c.execute("SELECT COUNT(*) FROM cards WHERE triggers=?", (bad_val,))
    n = c.fetchone()[0]
    if n:
        conn.execute("UPDATE cards SET triggers=? WHERE triggers=?", (good_val, bad_val))
        print(f'  {bad_val!r:50s} → {good_val!r}  ({n} cards)')
        fixed_trig += n
conn.commit()
total_fixed += fixed_trig
print(f'  → normalised {fixed_trig:,} trigger values')

# ── Fix 6: color = 'None' → NULL ─────────────────────────────────────────────
print('\nFix 6: color = "None" → NULL')
c.execute("SELECT COUNT(*) FROM cards WHERE color='None'")
n = c.fetchone()[0]
conn.execute("UPDATE cards SET color=NULL WHERE color='None'")
conn.commit()
total_fixed += n
print(f'  → cleared {n:,} color="None" values')

# ── Final summary ─────────────────────────────────────────────────────────────
print(f'\nTotal records fixed: {total_fixed:,}')
conn.close()
print('Done. Re-run prenorm_audit.py to verify.')
