# WeissCube Card Profiles DB — Query Reference

## Files
- `weiss_cards.db` — SQLite database (main source of truth)
- `data/card_profiles_all.json` — same data exported as JSON (29,423 profiles)

## Database Schema

### `card_profiles` table (29,423 rows)
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
- **Character**: 27,352
- **Event**: 1,854
- **Climax**: 217

## Profile Counts by Level
- **Level 0**: 10,235
- **Level 1**: 8,798
- **Level 2**: 6,107
- **Level 3**: 4,283

## Trigger Distribution
- `None`: 23,380
- `Soul`: 5,958
- `2 Soul`: 33
- `Treasure`: 9
- `Salvage`: 8
- `Book`: 8
- `Standby`: 8
- `Gate`: 6
- `Choice`: 6
- `Shot`: 3
- `Soul Bounce`: 2
- `Comeback`: 1
- `Return`: 1

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
