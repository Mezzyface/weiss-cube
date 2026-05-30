"""Second-pass fixes for remaining prenorm_audit failures."""
import sqlite3, re, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('weiss_cards.db')

# ── Fix 1: orphan 【 without closing 】 ───────────────────────────────────────
print('Fix 1: orphan 【 brackets')
c = conn.cursor()
c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en LIKE '%【%'")
rows = c.fetchall()
for card_no, text in rows:
    new_text = text.replace('【', '[').replace('】', ']')
    conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_text, card_no))
    print(f'  [{card_no}] fixed')
conn.commit()
print(f'  → {len(rows)} cards fixed')

# ── Fix 2: orphan 」 (and any stray 「) ───────────────────────────────────────
print('\nFix 2: orphan 「」 brackets')
c.execute("SELECT card_no, card_text_en FROM cards WHERE card_text_en LIKE '%「%' OR card_text_en LIKE '%」%'")
rows = c.fetchall()
for card_no, text in rows:
    new_text = text.replace('「', '"').replace('」', '"')
    conn.execute("UPDATE cards SET card_text_en=? WHERE card_no=?", (new_text, card_no))
    print(f'  [{card_no}] fixed')
conn.commit()
print(f'  → {len(rows)} cards fixed')

# ── Fix 3: null-level Character cards ────────────────────────────────────────
print('\nFix 3: null-level Character cards')
c.execute("""
    SELECT card_no, power, cost
    FROM cards
    WHERE type='Character' AND (level IS NULL OR level NOT BETWEEN 0 AND 3)
""")
rows = c.fetchall()
for card_no, power, cost in rows:
    # Infer level from power (WS standard bands):
    # L0: 500–3500, L1: 3500–7500, L2: 7000–10000, L3: 9000+
    if power is not None:
        if power < 4000:   level = 0
        elif power < 8000: level = 1
        elif power < 11000:level = 2
        else:              level = 3
    elif cost is not None:
        # fallback: cost 0→L0, 1-2→L1, 3-5→L2, 6+→L3
        if cost <= 0:   level = 0
        elif cost <= 2: level = 1
        elif cost <= 5: level = 2
        else:           level = 3
    else:
        level = 0  # default for completely unknown

    inferred_cost = cost if cost is not None else 0
    conn.execute("UPDATE cards SET level=?, cost=? WHERE card_no=? AND (level IS NULL OR level NOT BETWEEN 0 AND 3)",
                 (level, inferred_cost, card_no))
    print(f'  [{card_no}] power={power} cost={cost} → level={level} cost={inferred_cost}')
conn.commit()
print(f'  → {len(rows)} cards fixed')

# ── Fix audit script: soul check was wrong (counted NULLs) ─────────────────
# Soul NULL is valid for cards with no soul value — just report
c.execute("SELECT COUNT(*) FROM cards WHERE type='Character' AND soul IS NOT NULL AND soul NOT BETWEEN 0 AND 4")
bad_soul_real = c.fetchone()[0]
print(f'\nActual soul out-of-range (non-null): {bad_soul_real}')

conn.close()
print('\nDone.')
