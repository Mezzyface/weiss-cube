"""Remove duplicate profiles created when rewrites made two profiles text-identical."""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('weiss_cards.db')
c = conn.cursor()

c.execute("""
    SELECT type, level, cost, power, soul, triggers, normalized_effect,
           COUNT(*) as n, GROUP_CONCAT(profile_id) as pids
    FROM card_profiles
    GROUP BY type, level, cost, power, soul, triggers, normalized_effect
    HAVING n > 1
""")
dupes = c.fetchall()
print(f"Duplicate groups: {len(dupes)}")

for row in dupes:
    pids = [int(p) for p in row[8].split(',')]
    keep = pids[0]
    drop = pids[1:]
    # Merge example_cards into keeper
    c.execute(f"SELECT example_cards, variant_count, set_count FROM card_profiles WHERE profile_id=?", (keep,))
    keeper = c.fetchone()
    all_examples = set((keeper[0] or '').split(', '))
    for pid in drop:
        c.execute("SELECT example_cards FROM card_profiles WHERE profile_id=?", (pid,))
        r = c.fetchone()
        if r and r[0]:
            all_examples.update(r[0].split(', '))
        conn.execute("DELETE FROM card_profiles WHERE profile_id=?", (pid,))
    conn.execute("UPDATE card_profiles SET example_cards=?, variant_count=? WHERE profile_id=?",
                 (', '.join(sorted(all_examples)), len(all_examples), keep))
    print(f"  Merged {len(drop)} duplicate(s) into profile {keep}")

conn.commit()
c.execute("SELECT COUNT(*) FROM card_profiles")
print(f"Profiles after dedup: {c.fetchone()[0]:,}")
conn.close()
