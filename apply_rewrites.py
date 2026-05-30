"""
Review and apply agent-produced rewrite JSON files.

Each file in rewrites/ is a JSON dict: {profile_id: rewritten_effect_text}
This script:
  1. Loads all JSON files from rewrites/
  2. Shows a before/after diff for review
  3. Applies approved rewrites to card_profiles.normalized_effect
  4. Moves applied files to rewrites/applied/

Usage:
    python apply_rewrites.py [--auto]   # --auto skips review, applies all
"""
import sqlite3, json, sys, os, re
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

DB = 'weiss_cards.db'
REWRITES_DIR = Path('rewrites')
APPLIED_DIR  = REWRITES_DIR / 'applied'
APPLIED_DIR.mkdir(exist_ok=True)

AUTO = '--auto' in sys.argv
JP_RE = re.compile(r'[ぁ-んァ-ン一-鿿々〆〇]')

conn = sqlite3.connect(DB)
c = conn.cursor()

files = sorted(REWRITES_DIR.glob('*.json'))
print(f'Found {len(files)} rewrite file(s)\n')

total_applied = 0
total_skipped = 0

for fpath in files:
    try:
        raw = fpath.read_bytes()
        text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8-sig')
        data = json.loads(text)
    except Exception as e:
        print(f'  SKIP {fpath.name}: {e}')
        continue
    print(f'=== {fpath.name} ({len(data)} rewrites) ===')

    # Pre-check: skip whole file if it has net regressions
    regressions = 0
    improvements = 0
    for pid_str, new_text in data.items():
        pid = int(pid_str)
        c.execute("SELECT normalized_effect FROM card_profiles WHERE profile_id=?", (pid,))
        row = c.fetchone()
        if not row or not row[0]: continue
        old = row[0]
        JP_RE2 = re.compile(r'played and placed|\[Stand\]|\[Rest\]|\[Reverse\]|\[Continuous\]')
        if JP_RE2.search(new_text) and not JP_RE2.search(old):
            regressions += 1
        elif new_text != old:
            improvements += 1
    if regressions > improvements:
        print(f'  SKIP {fpath.name}: {regressions} regressions > {improvements} improvements')
        total_skipped += regressions
        fpath.rename(APPLIED_DIR / fpath.name) if not (APPLIED_DIR / fpath.name).exists() else None
        continue

    file_applied = 0
    for pid_str, new_text in data.items():
        pid = int(pid_str)
        c.execute("SELECT name_en, level, normalized_effect FROM card_profiles WHERE profile_id=?", (pid,))
        row = c.fetchone()
        if not row:
            print(f'  [!] profile_id {pid} not found — skip')
            continue
        name, level, old_text = row

        # Skip if new text is worse (still has JP chars when old didn't)
        old_jp = bool(JP_RE.search(old_text or ''))
        new_jp = bool(JP_RE.search(new_text or ''))
        if new_jp and not old_jp:
            print(f'  [!] L{level} {name}: new text has JP chars, old didn\'t — skip')
            total_skipped += 1
            continue

        if AUTO:
            conn.execute("UPDATE card_profiles SET normalized_effect=? WHERE profile_id=?",
                         (new_text, pid))
            file_applied += 1
        else:
            print(f'\n  [{pid}] L{level} {name}')
            print(f'  OLD: {(old_text or "")[:120]}')
            print(f'  NEW: {new_text[:120]}')
            ans = input('  Apply? [y/N] ').strip().lower()
            if ans == 'y':
                conn.execute("UPDATE card_profiles SET normalized_effect=? WHERE profile_id=?",
                             (new_text, pid))
                file_applied += 1
            else:
                total_skipped += 1

    conn.commit()
    total_applied += file_applied
    print(f'  Applied {file_applied} rewrites from {fpath.name}')

    # Move to applied/ (overwrite if already there)
    dest = APPLIED_DIR / fpath.name
    if dest.exists():
        dest.unlink()
    fpath.rename(dest)

conn.close()
print(f'\nTotal applied: {total_applied}  skipped: {total_skipped}')
