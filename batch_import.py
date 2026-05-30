#!/usr/bin/env python3
"""
Batch importer for Weiss Schwarz sets from heartofthecards.com.
This script reads pre-saved HTML files from data/html/<set_id>.html
and processes them into the database.

Usage:
  python3 batch_import.py                    # process all pending sets in data/html/
  python3 batch_import.py --list             # show status of all sets
  python3 batch_import.py --set wsbtrbp      # process one specific set
  python3 batch_import.py --rebuild-only     # just rebuild profiles from existing cards
"""

import re
import json
import sqlite3
import argparse
import sys
from pathlib import Path

# Reuse core functions from scrape.py
sys.path.insert(0, str(Path(__file__).parent))
from scrape import init_db, parse_translation_text, rebuild_profiles, normalize_effect

DB_PATH  = Path(__file__).parent / "weiss_cards.db"
DATA_DIR = Path(__file__).parent / "data"
HTML_DIR = DATA_DIR / "html"
SETS_FILE = DATA_DIR / "sets_manifest.json"


def load_manifest() -> dict:
    if SETS_FILE.exists():
        return json.loads(SETS_FILE.read_text())
    return {}


def save_manifest(manifest: dict):
    SETS_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


def get_scraped_sets(conn) -> set:
    return {r[0] for r in conn.execute("SELECT set_id FROM sets")}


def process_html_file(conn, set_id: str, html_path: Path) -> int:
    """Parse a saved translation HTML file and upsert its cards into the DB. Returns card count."""
    html = html_path.read_text(encoding="utf-8", errors="replace")

    # Extract set name from title
    m = re.search(r'<title>[^<]*Schwarz\s+(.+?)\s+[Tt]ranslation', html)
    if m:
        set_name = m.group(1).strip()
    else:
        # Fall back to manifest
        manifest = load_manifest()
        set_name = manifest.get(set_id, {}).get("name", set_id)

    cards = parse_translation_text(html, set_id, set_name)
    if not cards:
        print(f"  WARN: no cards parsed from {html_path.name}")
        return 0

    conn.execute("INSERT OR REPLACE INTO sets(set_id,set_name) VALUES(?,?)", (set_id, set_name))
    inserted = 0
    for c in cards:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO cards(card_no,set_id,set_name,name_en,name_jp,rarity,color,side,type,
                    level,cost,power,soul,triggers,traits_jp,traits_en,card_text_en,flavor_text_en,image_url,source_url)
                VALUES(:card_no,:set_id,:set_name,:name_en,:name_jp,:rarity,:color,:side,:type,
                    :level,:cost,:power,:soul,:triggers,:traits_jp,:traits_en,:card_text_en,:flavor_text_en,:image_url,:source_url)
            """, c)
            inserted += 1
        except Exception as e:
            print(f"    ERROR inserting {c.get('card_no','?')}: {e}")
    conn.commit()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Batch import WS sets from saved HTML")
    parser.add_argument("--list",         action="store_true", help="Show status of all sets")
    parser.add_argument("--set",          help="Process a single set_id")
    parser.add_argument("--rebuild-only", action="store_true", help="Just rebuild profiles")
    parser.add_argument("--force-all",    action="store_true", help="Re-import ALL HTML files (overwrites existing cards, fixes parsing bugs)")
    args = parser.parse_args()

    HTML_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    if args.list:
        scraped = get_scraped_sets(conn)
        html_files = {p.stem for p in HTML_DIR.glob("*.html")}
        manifest = load_manifest()
        all_sets = sorted(set(manifest.keys()) | html_files)
        print(f"{'Set ID':<35} {'Status':<12} {'Cards':>6}  Name")
        print("-" * 80)
        for sid in all_sets:
            in_db = sid in scraped
            has_html = sid in html_files
            count = 0
            if in_db:
                r = conn.execute("SELECT COUNT(*) FROM cards WHERE set_id=?", (sid,)).fetchone()
                count = r[0]
            status = "✓ in DB" if in_db else ("HTML ready" if has_html else "pending")
            name = manifest.get(sid, {}).get("name", "?")
            print(f"  {sid:<33} {status:<12} {count:>6}  {name}")
        conn.close()
        return

    if args.rebuild_only:
        print("Rebuilding profiles...")
        profiles = rebuild_profiles(conn)
        print(f"  {len(profiles)} unique profiles across all sets")
        # Export
        out = DATA_DIR / "card_profiles_all.json"
        out.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        conn.close()
        return

    # Process sets
    if args.set:
        targets = [args.set]
    elif args.force_all:
        targets = [p.stem for p in sorted(HTML_DIR.glob("*.html"))]
        print(f"Force re-importing all {len(targets)} HTML files...")
    else:
        # Process all HTML files not yet in DB
        scraped = get_scraped_sets(conn)
        targets = [p.stem for p in sorted(HTML_DIR.glob("*.html")) if p.stem not in scraped]

    if not targets:
        print("Nothing to process. All HTML files already imported.")
        print("Use --rebuild-only to regenerate profiles.")
        conn.close()
        return

    total_cards = 0
    for set_id in targets:
        html_path = HTML_DIR / f"{set_id}.html"
        if not html_path.exists():
            print(f"  SKIP {set_id}: no HTML file in data/html/")
            continue
        print(f"Processing {set_id}...", end=" ", flush=True)
        count = process_html_file(conn, set_id, html_path)
        total_cards += count
        print(f"{count} cards")

    print(f"\nTotal new cards inserted: {total_cards}")
    print("Rebuilding profiles...")
    profiles = rebuild_profiles(conn)
    print(f"  {len(profiles)} unique profiles across all sets")

    out = DATA_DIR / "card_profiles_all.json"
    out.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Profiles JSON: {out}")

    conn.close()


if __name__ == "__main__":
    main()
