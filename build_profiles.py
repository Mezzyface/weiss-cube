"""
Build card_profiles from scratch from the cleaned cards table.

A "profile" = a unique combination of:
    type + level + cost + power + soul + triggers + normalized_effect

Cards that share all six fields are the same functional card printed multiple
times (alt-arts, reprints, SPs, cross-set reprints, etc.).

Steps:
  1. Pull every card from `cards`
  2. Normalise effect text one more time (whitespace, case of keywords)
  3. Group by the six fields above
  4. Pick a representative card per group (prefer EN lang, prefer lowest rarity)
  5. Write to card_profiles (drop + recreate)
  6. Export card_profiles_all.json
"""
import sqlite3, json, re, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

DB = 'weiss_cards.db'

# ── Text normalisation for grouping ─────────────────────────────────────────
# We want functionally identical effects to produce identical strings.

MULTI_SPACE = re.compile(r'  +')
TRAIL_PUNCT = re.compile(r'[\s.,;]+$')

# Keyword capitalisation — ensure consistent casing in the group key
KW_SUBS = [
    (re.compile(r'\[auto\]',     re.I), '[AUTO]'),
    (re.compile(r'\[cont\]',     re.I), '[CONT]'),
    (re.compile(r'\[act\]',      re.I), '[ACT]'),
    (re.compile(r'\[counter\]',  re.I), '[COUNTER]'),
    (re.compile(r'\bcx\s+combo\b', re.I), 'CX COMBO'),
    (re.compile(r'\bencore\b',   re.I), 'ENCORE'),
    (re.compile(r'\bbrainstorm\b',re.I),'BRAINSTORM'),
    (re.compile(r'\bbond\b/',    re.I), 'BOND/'),
    (re.compile(r'\bexperience\b',re.I),'EXPERIENCE'),
    (re.compile(r'\bchange\b(?=\s)',re.I),'CHANGE'),
    (re.compile(r'\balarm\b',    re.I), 'ALARM'),
    (re.compile(r'\bbackup\b',   re.I), 'BACKUP'),
    (re.compile(r'\bsupport\b',  re.I), 'SUPPORT'),
    (re.compile(r'\brecollection\b',re.I),'RECOLLECTION'),
    (re.compile(r'\bstandby\b',  re.I), 'STANDBY'),
    (re.compile(r'\bmerge\b',    re.I), 'MERGE'),
    (re.compile(r'\b\[rest\]',   re.I), '[REST]'),
    (re.compile(r'\b\[stand\]',  re.I), '[STAND]'),
    (re.compile(r'\b\[reverse\]',re.I), '[REVERSE]'),
]

def normalise_effect(text: str | None) -> str:
    """Return a stable grouping key for an effect text."""
    if not text:
        return ''
    t = text.strip()
    # Consistent keyword casing
    for pat, repl in KW_SUBS:
        t = pat.sub(repl, t)
    # Collapse whitespace
    t = MULTI_SPACE.sub(' ', t)
    t = TRAIL_PUNCT.sub('', t)
    return t


# ── Rarity ranking for representative selection ──────────────────────────────
# Lower = more "official" / preferred as the representative
RARITY_RANK = {
    'TD': 0, 'C': 1, 'U': 2, 'R': 3, 'RR': 4,
    'SR': 5, 'CC': 6, 'CR': 7, 'SP': 8, 'SSP': 9,
    'SEC': 10, 'PR': 11,
}

def rarity_rank(r: str | None) -> int:
    if not r:
        return 99
    return RARITY_RANK.get(r.upper(), 50)


# ── Load all cards, deduplicating EN/JP pairs ───────────────────────────────
# When both an EN card (W116-E029) and its JP counterpart (W116-029) exist,
# keep only the EN card — it has the official translation and is canonical.
# JP-only cards (no EN counterpart) are kept as-is.

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("""
    SELECT card_no, set_id, set_name, name_en, name_jp,
           type, level, cost, power, soul, triggers, color,
           traits_en, rarity, lang, card_text_en
    FROM cards
    WHERE type IN ('Character', 'Event', 'Climax')
""")
all_cards_raw = [dict(r) for r in cur.fetchall()]
print(f'Loaded {len(all_cards_raw):,} cards (raw)')

def jp_to_en_no(jp_no: str) -> str | None:
    """W116-029 → W116-E029  (the EN card number pattern)"""
    m = re.match(r'^(.*?/[A-Z]{1,2}\d{2,3})-(\d+\w*)$', jp_no)
    if m:
        return f'{m.group(1)}-E{m.group(2)}'
    return None

# Build set of JP card_nos that have an EN counterpart in the DB
en_card_nos = {c['card_no'] for c in all_cards_raw if c['lang'] == 'en'}
jp_with_en = set()
for card in all_cards_raw:
    if card['lang'] == 'jp':
        en_counterpart = jp_to_en_no(card['card_no'])
        if en_counterpart and en_counterpart in en_card_nos:
            jp_with_en.add(card['card_no'])

print(f'JP cards with EN counterpart (excluded): {len(jp_with_en):,}')

# Only keep JP cards that have NO EN counterpart, plus all EN cards
all_cards = [c for c in all_cards_raw
             if c['lang'] == 'en' or c['card_no'] not in jp_with_en]
print(f'Cards after EN/JP dedup: {len(all_cards):,}')

# ── Group into profiles ──────────────────────────────────────────────────────
# Key: (type, level, cost, power, soul, triggers, normalised_effect)
groups: dict[tuple, list[dict]] = defaultdict(list)

for card in all_cards:
    norm_eff = normalise_effect(card['card_text_en'])
    key = (
        card['type']     or '',
        card['level'],           # may be None for edge cases
        card['cost'],
        card['power'],
        card['soul'],
        card['triggers'] or 'None',
        norm_eff,
    )
    groups[key].append(card)

print(f'Unique profiles (raw): {len(groups):,}')

# ── Build profile rows ────────────────────────────────────────────────────────
profiles = []

for key, cards in groups.items():
    type_, level, cost, power, soul, triggers, norm_eff = key

    # Sort cards: EN lang first, then by rarity rank (lowest = most official)
    cards_sorted = sorted(
        cards,
        key=lambda c: (0 if c['lang'] == 'en' else 1, rarity_rank(c['rarity']))
    )
    rep = cards_sorted[0]  # representative

    example_cards = [c['card_no'] for c in cards_sorted]
    colors = sorted({c['color'] for c in cards if c['color']})
    power_levels = sorted({c['power'] for c in cards if c['power'] is not None})

    profiles.append({
        'card_no':          rep['card_no'],
        'set_id':           rep['set_id'],
        'set_name':         rep['set_name'],
        'name_en':          rep['name_en'],
        'type':             type_,
        'level':            level,
        'cost':             cost,
        'power':            power,
        'soul':             soul,
        'triggers':         triggers,
        'colors':           ', '.join(colors) if colors else None,
        'power_levels':     ', '.join(str(p) for p in power_levels) if power_levels else None,
        'normalized_effect':norm_eff,
        'example_cards':    ', '.join(example_cards),
        'variant_count':    len(cards),
        'set_count':        len({c['set_id'] for c in cards}),
    })

print(f'Profiles built: {len(profiles):,}')

# ── Write to DB ───────────────────────────────────────────────────────────────
conn.execute('DROP TABLE IF EXISTS card_profiles')
conn.execute('''
    CREATE TABLE card_profiles (
        profile_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        card_no          TEXT,
        set_id           TEXT,
        set_name         TEXT,
        name_en          TEXT,
        type             TEXT,
        level            INTEGER,
        cost             INTEGER,
        power            INTEGER,
        soul             INTEGER,
        triggers         TEXT,
        colors           TEXT,
        power_levels     TEXT,
        normalized_effect TEXT,
        example_cards    TEXT,
        variant_count    INTEGER,
        set_count        INTEGER
    )
''')

conn.executemany('''
    INSERT INTO card_profiles
    (card_no, set_id, set_name, name_en, type, level, cost, power, soul,
     triggers, colors, power_levels, normalized_effect, example_cards,
     variant_count, set_count)
    VALUES
    (:card_no, :set_id, :set_name, :name_en, :type, :level, :cost, :power,
     :soul, :triggers, :colors, :power_levels, :normalized_effect,
     :example_cards, :variant_count, :set_count)
''', profiles)

conn.commit()
print(f'Written {len(profiles):,} profiles to card_profiles table')

# ── Stats breakdown ───────────────────────────────────────────────────────────
cur.execute("SELECT type, level, COUNT(*) as n FROM card_profiles GROUP BY type, level ORDER BY type, level")
print('\nProfile breakdown:')
for r in cur.fetchall():
    print(f'  {r[0]:12s} L{r[1] if r[1] is not None else "?"}: {r[2]:,}')

cur.execute("SELECT COUNT(*) FROM card_profiles WHERE variant_count > 1")
reprints = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM card_profiles WHERE set_count > 1")
cross_set = cur.fetchone()[0]
print(f'\n  Multi-print profiles: {reprints:,}')
print(f'  Cross-set profiles:   {cross_set:,}')

# Top reprinted
cur.execute("SELECT card_no, name_en, level, power, variant_count, set_count FROM card_profiles ORDER BY variant_count DESC LIMIT 5")
print('\nTop 5 most-reprinted profiles:')
for r in cur.fetchall():
    print(f'  [{r[0]}] {r[1]} | L{r[2]} {r[3]}pw | {r[4]}×prints {r[5]} sets')

# ── Export JSON ───────────────────────────────────────────────────────────────
rows = [dict(r) for r in conn.execute("SELECT * FROM card_profiles ORDER BY level, cost, power DESC")]
with open('data/card_profiles_all.json', 'w', encoding='utf-8') as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print(f'\nExported {len(rows):,} profiles → data/card_profiles_all.json')

conn.close()
print('Done.')
