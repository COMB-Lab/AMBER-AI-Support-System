#!/usr/bin/env python3
"""
One-command pipeline runner:
  crawl -> fetch -> parse -> link

Designed for this repo layout:
  Data Scraping & Cleaning/
    data/html, data/json
    scripts/*.py

Example:
  python "Data Scraping & Cleaning/scripts/run_pipeline.py" \
    --start-year 2023 --end-year 2023 \
    --since 2023-05 --until 2023-05 \
    --limit 5 \
    --threads-out "Data Scraping & Cleaning/data/threads_2023_05.json"
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
ROOT_DIR = SCRIPT_DIR.parent.resolve()                  # "Data Scraping & Cleaning"
DATA_DIR = ROOT_DIR / "data"
DEFAULT_HTML_DIR = DATA_DIR / "html"
DEFAULT_JSON_DIR = DATA_DIR / "json"

def run(argv: list[str]) -> None:
    """Run a subprocess and fail fast if it errors."""
    print("\n$ " + " ".join(map(str, argv)))
    try:
        res = subprocess.run(argv, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)

def main():
    p = argparse.ArgumentParser(description="Amber archive pipeline runner")
    # scope
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year", type=int, required=True)
    p.add_argument("--since", help="YYYY-MM inclusive (e.g., 2023-05)")
    p.add_argument("--until", help="YYYY-MM inclusive (e.g., 2023-05)")
    # perf / size
    p.add_argument("--limit", type=int, help="limit messages per month (fast demo)")
    p.add_argument("--rate", type=float, default=1.0, help="crawler rate/sleep factor")
    p.add_argument("--concurrency", type=int, default=6, help="crawler concurrency")
    # stages toggles
    p.add_argument("--skip-crawl", action="store_true")
    p.add_argument("--skip-fetch", action="store_true")
    p.add_argument("--skip-parse", action="store_true")
    p.add_argument("--skip-link", action="store_true")
    # I/O
    p.add_argument("--html-dir", default=str(DEFAULT_HTML_DIR))
    p.add_argument("--json-dir", default=str(DEFAULT_JSON_DIR))
    p.add_argument("--threads-out", default=str(DATA_DIR / "threads.json"))
    args = p.parse_args()

    # Ensure dirs exist
    Path(args.html_dir).mkdir(parents=True, exist_ok=True)
    Path(args.json_dir).mkdir(parents=True, exist_ok=True)
    Path(args.threads_out).parent.mkdir(parents=True, exist_ok=True)

    python = sys.executable

    # 1) Crawl
    if not args.skip_crawl:
        crawl = [
            python,
            str(SCRIPT_DIR / "crawl_amber_async.py"),
            "--start-year", str(args.start_year),
            "--end-year", str(args.end_year),
            "--rate", str(args.rate),
            "--concurrency", str(args.concurrency),
        ]
        if args.since: crawl += ["--since", args.since]
        run(crawl)

    # 2) Fetch
    if not args.skip_fetch:
        fetch = [
            python,
            str(SCRIPT_DIR / "fetch_single_email.py"),
            "--out-dir", str(args.html_dir),
        ]
        if args.since: fetch += ["--since", args.since]
        if args.until: fetch += ["--until", args.until]
        if args.limit is not None: fetch += ["--limit", str(args.limit)]
        run(fetch)

    # 3) Parse
    if not args.skip_parse:
        parse = [
            python,
            str(SCRIPT_DIR / "parse_single_email.py"),
            "--in-dir", str(args.html_dir),
            "--out-dir", str(args.json_dir),
        ]
        if args.since: parse += ["--since", args.since]
        if args.until: parse += ["--until", args.until]
        if args.limit is not None: parse += ["--limit", str(args.limit)]
        run(parse)

    # 4) Link (threads)
    if not args.skip_link:
        link = [
            python,
            str(SCRIPT_DIR / "link_threads.py"),
            "--in-dir", str(args.json_dir),
            "--out", str(args.threads_out),
        ]
        if args.since: link += ["--since", args.since]
        if args.until: link += ["--until", args.until]
        run(link)

if __name__ == "__main__":
    main()