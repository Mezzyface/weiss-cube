"""Show before/after for rewrite files, flagging improvements vs regressions."""
import sqlite3, json, re, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect('weiss_cards.db')
c = conn.cursor()

BAD_PATTERNS = re.compile(
    r'played and placed|\[Stand\]|\[Rest\]|\[Reverse\]'
    r'|\[Continuous\]|\[Activate\]|\[Permanent\]'
    r'|for the turn, \+\d|this card\'s \+\d'
    r'|front attackwhen|handchoose|handput|charactersdoes'
)

def load_json(fpath):
    raw = fpath.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        text = raw.decode('utf-16')
    else:
        text = raw.decode('utf-8-sig')
    return json.loads(text)

files = sorted(Path('rewrites').glob('batch_*.json'))
print(f"Output files to review: {len(files)}\n")

total_improved = 0
total_regressed = 0
total_unchanged = 0
skipped_files = 0

for fpath in files:
    try:
        data = load_json(fpath)
    except Exception as e:
        print(f"  {fpath.name}: SKIP ({e})")
        skipped_files += 1
        continue

    file_improved = 0
    file_regressed = 0
    file_unchanged = 0

    for pid_str, new_text in data.items():
        pid = int(pid_str)
        c.execute("SELECT name_en, level, normalized_effect FROM card_profiles WHERE profile_id=?", (pid,))
        row = c.fetchone()
        if not row:
            continue
        name, lvl, old = row
        old = old or ''
        new_text = new_text or ''

        if new_text == old:
            file_unchanged += 1
        elif BAD_PATTERNS.search(new_text) and not BAD_PATTERNS.search(old):
            file_regressed += 1
        elif new_text != old:
            file_improved += 1

    total_improved  += file_improved
    total_regressed += file_regressed
    total_unchanged += file_unchanged

    flag = '⚠' if file_regressed > 0 else ' '
    print(f"  {flag}{fpath.name}: ✓{file_improved} improved  ✗{file_regressed} regressed  ={file_unchanged} unchanged")

print(f"\nTotals across {len(files)-skipped_files} files ({skipped_files} skipped):")
print(f"  Improved : {total_improved}")
print(f"  Regressed: {total_regressed}")
print(f"  Unchanged: {total_unchanged}")
conn.close()
