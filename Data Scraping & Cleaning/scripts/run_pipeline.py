#!/usr/bin/env python3
"""
Pipeline: fetch (discovers itself) -> parse -> link (flat json) with optional cleanup
"""

import argparse, subprocess, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
ROOT_DIR   = SCRIPT_DIR.parent.resolve()
DATA_DIR   = ROOT_DIR / "data"
HTML_DIR   = DATA_DIR / "html"
JSON_DIR   = DATA_DIR / "json"

def run(argv: list[str]) -> None:
    print("\n$ " + " ".join(map(str, argv)))
    res = subprocess.run(argv, check=False)
    if res.returncode != 0: sys.exit(res.returncode)

def main():
    p = argparse.ArgumentParser(description="Amber pipeline without manifests; flat thread JSONs.")
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year",   type=int, required=True)
    p.add_argument("--since"); p.add_argument("--until")
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--cleanup", action="store_true", help="Delete per-message JSON after linking")
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

    # 3) Link -> flat thread JSONs in data/json/*.json
    link = [
        py, str(SCRIPT_DIR / "link_threads.py"),
        "--json-in",  str(args.json_dir),
        "--json-out", str(args.json_dir),
    ]
    if args.since:  link += ["--since", args.since]
    if args.until:  link += ["--until", args.until]
    if args.cleanup: link += ["--cleanup"]
    run(link)

if __name__ == "__main__":
    main()