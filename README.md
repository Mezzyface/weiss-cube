# WeissCube Card Database

SQLite database of Weiss Schwarz card profiles used to design the **WeissCube** — a 480-card custom WS draft cube.

## What's Here

| File | Description |
|------|-------------|
| `weiss_cards.db` | Main SQLite database (228MB, not in git — see below) |
| `data/card_profiles_all.json` | All 29,423 unique profiles exported as JSON |
| `data/translation_key.json` | Learned JP→EN phrase pairs (9,856 entries) from aligned cards |
| `data/W107-wsrawbtrtd.json` | Sample raw set data |
| `review_site/index.html` | Browser UI for exploring profiles (serve locally) |

## Database State

- **92,977 raw cards** across **710 sets** (EN + JP)
- **29,423 unique card profiles** after deduplication
- EN cards use official English text; JP-only cards use Google Translate + agent rewording
- All effect text normalized to modern WS English format

### Profile Breakdown

| Type | L0 | L1 | L2 | L3 |
|------|----|----|----|-----|
| Character | 10,015 | 7,914 | 5,391 | 4,032 |
| Event | 4 | 884 | 716 | 250 |
| Climax | 217 | — | — | — |

## Pipeline Scripts

Run these in order to rebuild everything from scratch:

```bash
# 1. Scrape cards (EN + JP sources)
python crawl.py

# 2. Normalize text — add ::TRAIT:: / [CHARACTER] placeholders, backup raw cols
python normalize_text.py

# 3. Build JP→EN translation key from matched EN/JP card pairs
python build_translation_key.py

# 4. Rule-based translation pass (fast, ~2s)
python translate_normalize.py

# 5. Google Translate fallback for remaining JP cards (~60 min)
python translate_fallback.py

# 6. Pre-normalization audit + fixes
python prenorm_audit.py
python prenorm_fixes.py && python prenorm_fixes2.py

# 7. Build profiles + merge power creep + dedup
python build_profiles.py
python merge_power_creep.py
python dedup_profiles.py

# 8. Export JSON
python export_profiles.py
```

## Rewriting JP-Translated Text

Cards only available in Japanese get Google-translated text. To improve wording to modern WS English style:

```bash
# Generate batch input files (40 cards each)
python get_needs_rewrite.py

# Spawn haiku agents to rewrite → rewrites/batch_NNN.json
# Then review and apply:
python review_rewrites.py          # quality check
python apply_rewrites.py --auto    # apply (skips regressions)
```

## Card Profile Review Site

```bash
# Serve locally and open in browser
python -m http.server 8080
# → open http://localhost:8080/review_site/
```

Features: filter by type/level/cost/trigger/color/mechanic, full-text search, click for detail panel, "Add to Cube" picks saved in localStorage.

## Database Schema

```sql
cards(
  card_no TEXT,           -- e.g. "YRC/W116-029"
  set_id TEXT,
  name_en TEXT, name_jp TEXT,
  rarity TEXT, color TEXT, side TEXT, type TEXT,
  level INTEGER, cost INTEGER, power INTEGER, soul INTEGER,
  triggers TEXT, traits_jp TEXT, traits_en TEXT,
  card_text_en TEXT,      -- English effect (official or translated)
  card_text_jp TEXT,      -- Japanese effect (normalized, ::TRAIT:: placeholders)
  card_text_en_raw TEXT,  -- Original before normalization
  card_text_jp_raw TEXT,
  lang TEXT               -- 'en' or 'jp'
)

card_profiles(
  profile_id INTEGER,
  card_no TEXT,           -- representative card
  name_en TEXT, type TEXT,
  level INTEGER, cost INTEGER, power INTEGER, soul INTEGER,
  triggers TEXT,
  colors TEXT,            -- comma-separated colors that printed this profile
  power_levels TEXT,      -- all observed power values (power creep tracking)
  normalized_effect TEXT, -- WS English effect; ::TRAIT:: and [CHARACTER] placeholders
  example_cards TEXT,     -- all card_nos sharing this profile
  variant_count INTEGER,  -- total printings collapsed into this profile
  set_count INTEGER       -- distinct sets
)
```

## Key Query Patterns

```sql
-- All ENCORE characters
SELECT name_en, level, cost, power, normalized_effect
FROM card_profiles
WHERE type='Character' AND normalized_effect LIKE '%ENCORE%'
ORDER BY level, cost;

-- BRAINSTORM cards
SELECT * FROM card_profiles
WHERE normalized_effect LIKE '%BRAINSTORM%';

-- L3 finishers by power
SELECT name_en, power, soul, triggers, normalized_effect
FROM card_profiles
WHERE type='Character' AND level=3
ORDER BY power DESC;

-- CX COMBO cards
SELECT name_en, level, power, normalized_effect
FROM card_profiles
WHERE normalized_effect LIKE '%CX COMBO%';

-- Multi-color profiles (reprinted across colors)
SELECT name_en, level, power, colors, variant_count
FROM card_profiles
WHERE colors LIKE '%,%'
ORDER BY variant_count DESC;

-- Widely reprinted designs (strong archetypes)
SELECT name_en, level, variant_count, set_count,
       substr(normalized_effect,1,80) as effect
FROM card_profiles
ORDER BY variant_count DESC LIMIT 20;
```

## Restoring the Database

The DB is not in git (228MB). To restore:

1. Copy from backup: `weiss_cards_rewritten_20260530_0040.db` → `weiss_cards.db`
2. Or rebuild from scratch using the pipeline above (~90 min)
