#!/usr/bin/env python3
"""Fetch a single email archive page and save the raw HTML to disk.

Writes to data/html/202204/0000.html by default.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path

import requests


DEFAULT_URL = "http://archive.ambermd.org/202204/0000.html"
DEFAULT_OUT = Path("data/html/202204/0000.html")


def fetch(url: str, timeout: int = 10, max_retries: int = 3, backoff: float = 1.0, sleep_between: float = 0.5):
    headers = {"User-Agent": "fetch_single_email/1.0 (+https://example.com)"}
    attempt = 0
    while attempt < max_retries:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            attempt += 1
            wait = backoff * (2 ** (attempt - 1))
            print(f"Request failed (attempt {attempt}/{max_retries}): {e}")
            if attempt >= max_retries:
                raise
            print(f"Retrying after {wait:.1f}s...")
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.content
        else:
            attempt += 1
            print(f"Unexpected status code {resp.status_code} (attempt {attempt}/{max_retries})")
            if attempt >= max_retries:
                resp.raise_for_status()
            wait = backoff * (2 ** (attempt - 1))
            print(f"Retrying after {wait:.1f}s...")
            time.sleep(wait)
    raise RuntimeError("Failed to fetch URL after retries")


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fetch a single Amber archive email page and save raw HTML")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL to fetch")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output file path")
    parser.add_argument("--timeout", type=int, default=10, help="Request timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Max number of retries on failure")
    parser.add_argument("--backoff", type=float, default=1.0, help="Base backoff seconds for retries")
    args = parser.parse_args(argv)

    out_path: Path = args.out
    try:
        print(f"Fetching: {args.url}")
        data = fetch(args.url, timeout=args.timeout, max_retries=args.retries, backoff=args.backoff)
    except Exception as e:
        print(f"Failed to fetch URL: {e}")
        sys.exit(2)

    if not data:
        print("Downloaded content is empty")
        sys.exit(3)

    ensure_parent(out_path)
    out_path.write_bytes(data)

    checksum = sha256_hex(data)
    print(f"Saved {out_path} ({len(data)} bytes)")
    print(f"SHA256: {checksum}")


if __name__ == "__main__":
    main()
