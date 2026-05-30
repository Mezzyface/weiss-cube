"""Quick audit of the freshly built card_profiles table."""
import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('weiss_cards.db')
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM card_profiles")
total = c.fetchone()[0]
print(f'Total profiles: {total:,}')

# Breakdown
c.execute("SELECT type, level, COUNT(*) FROM card_profiles GROUP BY type, level ORDER BY type, level")
print('\nType / Level breakdown:')
for r in c.fetchall():
    print(f'  {r[0]:12s} L{r[1]}: {r[2]:,}')

# Color coverage
c.execute("SELECT COUNT(*) FROM card_profiles WHERE colors IS NOT NULL")
with_colors = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM card_profiles WHERE colors IS NULL")
no_colors = c.fetchone()[0]
print(f'\nColor coverage: {with_colors:,} have colors, {no_colors:,} missing')

# Multi-color profiles (reprinted across colors)
c.execute("SELECT COUNT(*) FROM card_profiles WHERE colors LIKE '%,%'")
multi_color = c.fetchone()[0]
print(f'Multi-color profiles: {multi_color:,}')

# Cross-set
c.execute("SELECT COUNT(*) FROM card_profiles WHERE set_count >= 5")
wide = c.fetchone()[0]
print(f'Profiles in 5+ sets: {wide:,}')

# Effect coverage
c.execute("SELECT COUNT(*) FROM card_profiles WHERE normalized_effect IS NOT NULL AND normalized_effect != ''")
has_effect = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM card_profiles WHERE normalized_effect IS NULL OR normalized_effect = ''")
no_effect = c.fetchone()[0]
print(f'\nEffect coverage: {has_effect:,} have text, {no_effect:,} blank (vanilla/CX)')

# Trigger distribution
c.execute("SELECT triggers, COUNT(*) as n FROM card_profiles GROUP BY triggers ORDER BY n DESC")
print('\nTrigger distribution:')
for r in c.fetchall():
    print(f'  {(r[0] or "None"):20s} {r[1]:,}')

# Sanity: no duplicate profile for same (type,level,cost,power,soul,triggers,effect)
c.execute("""
    SELECT COUNT(*) FROM (
        SELECT type, level, cost, power, soul, triggers, normalized_effect,
               COUNT(*) as n
        FROM card_profiles
        GROUP BY type, level, cost, power, soul, triggers, normalized_effect
        HAVING n > 1
    )
""")
dupes = c.fetchone()[0]
if dupes == 0:
    print('\n✅  No duplicate profiles — every (stats+effect) combo is unique')
else:
    print(f'\n⚠  {dupes} duplicate profile keys found')

conn.close()
