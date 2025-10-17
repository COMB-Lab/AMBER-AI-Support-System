#!/usr/bin/env python3
"""Crawl the Amber archive and produce per-thread JSON files.

Usage (demo for a single month):
  python scripts/crawl_archive.py --start-year 2022 --end-year 2022 --months 4

This script will:
 - fetch monthly index pages like http://archive.ambermd.org/202204/
 - extract message links (e.g., 0000.html)
 - download each message HTML to data/html/<YYYYMM>/<NNNN>.html
 - parse each message JSON using scripts/parse_single_email.py logic
 - group messages by thread_id and write data/threads/<thread_id>.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import List

import requests

# import parser function from our parse script by reading it as a module
from importlib.machinery import SourceFileLoader

PARSER_PATH = Path(__file__).resolve().parent / 'parse_single_email.py'
parse_mod = SourceFileLoader('parse_single_email', str(PARSER_PATH)).load_module()


BASE = 'http://archive.ambermd.org'


def list_month_index(year: int, month: int) -> str:
    return f"{BASE}/{year:04d}{month:02d}/"


def fetch_index(url: str, timeout: int = 10) -> str:
    headers = {"User-Agent": "amber-archive-crawler/0.1"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def extract_message_paths(index_html: str) -> List[str]:
    # Look for href="0000.html" within the index
    found = re.findall(r'href=["\']([0-9]{4}\.html)["\']', index_html)
    # Return unique sorted
    return sorted(set(found))


def download_message(month_dir: Path, year_month: str, filename: str) -> Path:
    url = f"{BASE}/{year_month}/{filename}"
    out_dir = month_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    if out_path.exists():
        return out_path
    headers = {"User-Agent": "amber-archive-crawler/0.1"}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def crawl_range(start_year: int, end_year: int, months: List[int], delay: float = 0.5):
    threads_dir = Path('data') / 'threads'
    threads_dir.mkdir(parents=True, exist_ok=True)
    all_messages = []

    for year in range(start_year, end_year + 1):
        for month in months:
            ym = f"{year:04d}{month:02d}"
            index_url = list_month_index(year, month)
            try:
                print(f"Fetching index: {index_url}")
                index_html = fetch_index(index_url)
            except Exception as e:
                print(f"Failed to fetch index {index_url}: {e}")
                continue

            message_files = extract_message_paths(index_html)
            print(f"Found {len(message_files)} messages in {ym}")

            month_dir = Path('data') / 'html' / ym
            for filename in message_files:
                try:
                    path = download_message(month_dir, ym, filename)
                except Exception as e:
                    print(f"Failed to download {filename}: {e}")
                    continue
                # parse into JSON using parse_mod.parse_file
                try:
                    parsed = parse_mod.parse_file(path, url=f"{BASE}/{ym}/{filename}")
                except Exception as e:
                    print(f"Failed to parse {path}: {e}")
                    continue

                # write per-message JSON under data/json/<ym>/<filename>.json
                json_out = Path('data') / 'json' / 'html' / ym / Path(filename).with_suffix('.json')
                json_out.parent.mkdir(parents=True, exist_ok=True)
                json_out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
                all_messages.append(parsed)

                time.sleep(delay)

    # group by thread_id
    threads = {}
    for msg in all_messages:
        tid = msg.get('thread_id') or msg.get('subject') or 'unknown'
        threads.setdefault(tid, []).append(msg)

    # write thread JSON files named by thread id (sanitize filename)
    for tid, msgs in threads.items():
        safe = re.sub(r'[^A-Za-z0-9\-_. ]+', '_', tid)[:200]
        out = Path('data') / 'threads' / (safe + '.json')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"thread_id": tid, "messages": msgs}, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"Wrote {len(threads)} thread files to data/threads/")


def parse_months_arg(s: str) -> List[int]:
    if ',' in s:
        parts = s.split(',')
        return [int(p) for p in parts]
    return [int(s)]


def main():
    parser = argparse.ArgumentParser(description='Crawl Amber archive months and produce thread JSONs')
    parser.add_argument('--start-year', type=int, default=2020)
    parser.add_argument('--end-year', type=int, default=2025)
    parser.add_argument('--months', type=str, default='1,2,3,4,5,6,7,8,9,10,11,12')
    parser.add_argument('--delay', type=float, default=0.5)
    args = parser.parse_args()

    months = parse_months_arg(args.months)
    crawl_range(args.start_year, args.end_year, months, delay=args.delay)


if __name__ == '__main__':
    main()
