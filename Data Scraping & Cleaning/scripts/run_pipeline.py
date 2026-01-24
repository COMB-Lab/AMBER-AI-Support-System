#!/usr/bin/env python3
"""
Pipeline: fetch (discovers itself) -> parse -> link (flat json) with optional cleanup
Adds --cleanup-html to remove raw HTML after successful linking.
"""

import argparse, subprocess, sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent.resolve()
ROOT_DIR   = SCRIPT_DIR.parent.resolve()
DATA_DIR   = ROOT_DIR / "data"
HTML_DIR   = DATA_DIR / "html"
JSON_DIR   = DATA_DIR / "json"

def run(argv: list[str]) -> None:
    print("\n$ " + " ".join(map(str, argv)))
    res = subprocess.run(argv, check=False)
    if res.returncode != 0:
        sys.exit(res.returncode)

def ym_to_int(ym: str | None) -> int | None:
    if not ym: return None
    ym = ym.strip()
    if len(ym) == 7 and ym[4] == "-":
        y, m = ym.split("-")
        return int(y) * 100 + int(m)
    return None

def iter_months(start_year: int, end_year: int, since: str | None, until: str | None):
    """Yield YYYYMM strings, capped at current month."""
    now = datetime.now()
    cur_ym = now.year * 100 + now.month
    s = ym_to_int(since) or (start_year * 100 + 1)
    u = min(ym_to_int(until) or (end_year * 100 + 12), cur_ym)
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            ym = y * 100 + m
            if s <= ym <= u:
                yield f"{y}{m:02d}"

def cleanup_html_months(html_root: Path, months: list[str]) -> int:
    """Delete HTML files and month folders for the given YYYYMM list."""
    removed_files = 0
    for yyyymm in months:
        month_dir = html_root / yyyymm
        if not month_dir.is_dir():
            continue
        for p in month_dir.glob("*.html"):
            try:
                p.unlink()
                removed_files += 1
            except Exception:
                pass
        # remove empty month dir
        try:
            if not any(month_dir.iterdir()):
                month_dir.rmdir()
        except Exception:
            pass
    return removed_files

def main():
    p = argparse.ArgumentParser(description="Amber pipeline without manifests; flat thread JSONs.")
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year",   type=int, required=True)
    p.add_argument("--since", help="YYYY-MM inclusive start")
    p.add_argument("--until", help="YYYY-MM inclusive end")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--cleanup", action="store_true", help="Delete per-message JSON after linking")
    p.add_argument("--cleanup-html", action="store_true", help="Delete raw HTML after linking")
    p.add_argument("--html-dir", default=str(HTML_DIR))
    p.add_argument("--json-dir", default=str(JSON_DIR))
    args = p.parse_args()

    Path(args.html_dir).mkdir(parents=True, exist_ok=True)
    Path(args.json_dir).mkdir(parents=True, exist_ok=True)

    py = sys.executable

    # 1) Fetch HTML (discovers monthly links itself)
    fetch = [
        py, str(SCRIPT_DIR / "fetch_single_email.py"),
        "--start-year", str(args.start_year), "--end-year", str(args.end_year),
        "--out-dir", str(args.html_dir),
    ]
    if args.since: fetch += ["--since", args.since]
    if args.until: fetch += ["--until", args.until]
    if args.limit is not None: fetch += ["--limit", str(args.limit)]
    if args.force: fetch += ["--force"]
    run(fetch)

    # 2) Parse HTML -> per-message JSON
    parse = [
        py, str(SCRIPT_DIR / "parse_single_email.py"),
        "--in-dir", str(args.html_dir),
        "--out-dir", str(args.json_dir),
    ]
    if args.since: parse += ["--since", args.since]
    if args.until: parse += ["--until", args.until]
    if args.limit is not None: parse += ["--limit", str(args.limit)]
    if args.force: parse += ["--force"]
    run(parse)

    # 3) Link -> nested thread JSONs in json/YYYY/MM/<thread_id>.json
    link = [
        py, str(SCRIPT_DIR / "link_threads.py"),
        "--json-in",  str(args.json_dir),
        "--json-out", str(args.json_dir),
    ]
    if args.since:  link += ["--since", args.since]
    if args.until:  link += ["--until", args.until]
    if args.cleanup: link += ["--cleanup"]  # per-message JSON cleanup
    run(link)

    # 4) Optional: cleanup raw HTML for processed months
    if args.cleanup_html:
        months = list(iter_months(args.start_year, args.end_year, args.since, args.until))
        removed = cleanup_html_months(Path(args.html_dir), months)
        print(f"HTML cleanup: removed {removed} files across {len(months)} month folder(s)")

if __name__ == "__main__":
    main()