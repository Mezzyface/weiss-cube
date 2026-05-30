"""
Export the cleaned card_profiles table to card_profiles_all.json
and write a DB_README with schema + query examples for a new chat session.
"""
import sqlite3, json, sys, re
sys.stdout.reconfigure(encoding='utf-8')

c = sqlite3.connect('weiss_cards.db')
c.row_factory = sqlite3.Row

# ── 1. Export card_profiles_all.json ──────────────────────────────────────────
profiles = [dict(r) for r in c.execute(
    "SELECT * FROM card_profiles ORDER BY level, cost, power DESC")]

with open('data/card_profiles_all.json', 'w', encoding='utf-8') as f:
    json.dump(profiles, f, ensure_ascii=False, indent=2)
print(f"Exported {len(profiles)} profiles → data/card_profiles_all.json")

# ── 2. Quick stats for the readme ─────────────────────────────────────────────
by_type = {}
for p in profiles:
    t = p['type'] or 'Unknown'
    by_type[t] = by_type.get(t, 0) + 1

by_level = {}
for p in profiles:
    k = p['level']
    by_level[k] = by_level.get(k, 0) + 1

triggers_dist = {}
for p in profiles:
    t = p['triggers'] or 'None'
    triggers_dist[t] = triggers_dist.get(t, 0) + 1

# ── 3. Sample profiles (one per type/level combo) ────────────────────────────
samples = {}
for p in profiles:
    key = (p['type'] or '', p['level'])
    if key not in samples:
        samples[key] = p

# ── 4. Write DB_README.md ─────────────────────────────────────────────────────
readme = f"""# WeissCube Card Profiles DB — Query Reference

## Files
- `weiss_cards.db` — SQLite database (main source of truth)
- `data/card_profiles_all.json` — same data exported as JSON ({len(profiles):,} profiles)

## Database Schema

### `card_profiles` table ({len(profiles):,} rows)
The central table. Each row is a unique card design profile (same stats + same effect = 1 row).
Multiple physical printings of the same design are folded into one profile via `example_cards`.

| Column | Type | Description |
|--------|------|-------------|
| `profile_id` | INTEGER PK | Auto-increment row ID |
| `card_no` | TEXT | Representative card number (from `example_cards[0]`) |
| `set_id` | TEXT | Set the representative card is from |
| `set_name` | TEXT | Human-readable set name |
| `name_en` | TEXT | English card name of the representative |
| `type` | TEXT | `Character`, `Event`, `Climax`, or blank |
| `level` | INTEGER | 0–3 |
| `cost` | INTEGER | Stock cost to play |
| `power` | INTEGER | Base power (Characters only; 0 otherwise) |
| `soul` | INTEGER | Soul value |
| `triggers` | TEXT | Trigger icon(s): `None`, `Soul`, `2 Soul`, `Salvage`, `Book`, `Door`, `Shot`, `Treasure`, `Standby`, `Gate`, `Choice`, `Soul Bounce`, etc. |
| `normalized_effect` | TEXT | Effect text with specific trait/character names replaced by `::TRAIT::` or `[CHARACTER]` placeholders |
| `example_cards` | TEXT | Comma-separated list of all card_nos that share this profile |
| `variant_count` | INTEGER | Total number of physical cards sharing this profile (including alt-arts, SPs, etc.) |
| `set_count` | INTEGER | Number of distinct sets that printed this profile |

### `cards` table (27,335 rows)
Raw scraped card data, one row per physical card.

| Column | Type | Description |
|--------|------|-------------|
| `card_no` | TEXT PK | Card number (e.g. `BTR/W107-T01`) |
| `set_id` | TEXT | FK → sets.set_id |
| `name_en` | TEXT | English name |
| `name_jp` | TEXT | Japanese name |
| `rarity` | TEXT | `TD`, `C`, `U`, `R`, `RR`, `SR`, `CC`, `CR`, `SP`, `SSP`, etc. |
| `color` | TEXT | `Red`, `Yellow`, `Green`, `Blue`, `Purple` |
| `side` | TEXT | `Weiss` or `Schwarz` |
| `type` | TEXT | `Character`, `Event`, `Climax` |
| `level` | INTEGER | 0–3 |
| `cost` | INTEGER | Stock cost |
| `power` | INTEGER | Power |
| `soul` | INTEGER | Soul |
| `triggers` | TEXT | Trigger icon |
| `traits_en` | TEXT | English trait names (comma-separated) |
| `traits_jp` | TEXT | Japanese trait names |
| `card_text_en` | TEXT | Raw English effect text |
| `flavor_text_en` | TEXT | Flavor text if any |
| `image_url` | TEXT | Card image URL |
| `source_url` | TEXT | Source page URL |

### `sets` table (393 rows)
| Column | Description |
|--------|-------------|
| `set_id` | Internal ID (e.g. `W107-wsrawbtrtd`) |
| `set_name` | Display name (e.g. `Bocchi the Rock Trial Deck`) |
| `scraped_at` | Timestamp |

## Profile Counts by Type
"""
for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
    readme += f"- **{t or 'Unknown'}**: {n:,}\n"

readme += f"""
## Profile Counts by Level
"""
for lvl in sorted(k for k in by_level if k is not None):
    readme += f"- **Level {lvl}**: {by_level[lvl]:,}\n"

readme += f"""
## Trigger Distribution
"""
for trig, n in sorted(triggers_dist.items(), key=lambda x: -x[1])[:15]:
    readme += f"- `{trig}`: {n:,}\n"

readme += """
## Effect Text Conventions
- `::TRAIT::` — placeholder for a specific trait name (e.g. `::Music::`, `::Weapon::`)
- `::TRAIT:: or ::TRAIT::` — card accepts characters from either of two traits
- `[CHARACTER]` — placeholder for a specific character name (used in BOND effects)
- `COLOR` — placeholder for a specific color (Red/Yellow/Green/Blue/Purple)
- `[A]` / `[C]` / `[S]` — Auto / Continuous / Activated ability
- `[Counter]` — can be played as a Counter during opponent's attack
- `ENCORE [cost]` — pay cost to stand this card after it's reversed
- `BOND/[CHARACTER] [cost]` — pay cost to search for named character
- `BACKUP N, Level M [cost]` — Counter giving +N power at level M
- `BRAINSTORM [cost]` — flip top 4 cards, trigger effect per Climax revealed
- `MERGE [cost]` — place card under this as a Marker

## Common Query Patterns

### SQLite (weiss_cards.db)

```sql
-- All L1 character profiles, sorted by power
SELECT * FROM card_profiles
WHERE type='Character' AND level=1
ORDER BY power DESC;

-- Find all profiles containing a specific keyword
SELECT card_no, name_en, normalized_effect
FROM card_profiles
WHERE normalized_effect LIKE '%BRAINSTORM%'
  AND level=0;

-- Profiles with specific trigger
SELECT * FROM card_profiles
WHERE triggers='Door' AND type='Climax';

-- Find cards in a specific set
SELECT c.card_no, c.name_en, c.color, c.level, c.cost, c.power, c.card_text_en
FROM cards c
WHERE c.set_id = 'W107-wsrawbtrtd'
ORDER BY c.level, c.cost;

-- Join profiles to raw cards for full detail
SELECT p.*, c.color, c.traits_en, c.card_text_en
FROM card_profiles p
JOIN cards c ON c.card_no = p.card_no
WHERE p.level=3 AND p.type='Character'
ORDER BY p.power DESC;

-- Profiles with high variant_count (widely reprinted designs)
SELECT card_no, name_en, level, power, variant_count, set_count,
       substr(normalized_effect, 1, 80) as effect_preview
FROM card_profiles
ORDER BY variant_count DESC
LIMIT 20;
```

### Python (card_profiles_all.json)

```python
import json
with open('data/card_profiles_all.json', encoding='utf-8') as f:
    profiles = json.load(f)

# Filter Level 0 Characters by power
l0 = [p for p in profiles if p['type']=='Character' and p['level']==0]
l0.sort(key=lambda p: p['power'], reverse=True)

# Find all Brainstorm profiles
brainstorms = [p for p in profiles if 'BRAINSTORM' in (p['normalized_effect'] or '')]

# Group by trigger
from collections import defaultdict
by_trigger = defaultdict(list)
for p in profiles:
    by_trigger[p['triggers'] or 'None'].append(p)
```
"""

with open('DB_README.md', 'w', encoding='utf-8') as f:
    f.write(readme)
print("Wrote DB_README.md")

# ── 5. Verify JSON round-trips cleanly ───────────────────────────────────────
with open('data/card_profiles_all.json', encoding='utf-8') as f:
    check = json.load(f)
assert len(check) == len(profiles), "JSON count mismatch!"
print(f"JSON verified: {len(check):,} profiles, round-trip OK")

c.close()
print("\nDone. Ready for a new chat session.")
