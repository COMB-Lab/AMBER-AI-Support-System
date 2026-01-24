#!/usr/bin/env python3
import argparse, re, sys, time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ARCHIVE_ROOT = "http://archive.ambermd.org/"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
HTML_DIR_DEFAULT = DATA_ROOT / "html"

A_MSG = re.compile(r"^0\d{3}\.html$")  # 0000.html

def ym_to_int(ym: str | None) -> int | None:
    if not ym: return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", ym)
    return int(m.group(1))*100 + int(m.group(2)) if m else None

def iter_months(start_year: int, end_year: int, since: str | None, until: str | None):
    import datetime
    now = datetime.datetime.now()
    cur_ym = now.year * 100 + now.month  # cap at current month
    s = ym_to_int(since) or (start_year * 100 + 1)
    u = min(ym_to_int(until) or (end_year * 100 + 12), cur_ym)
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            ym = y * 100 + m
            if s <= ym <= u:
                yield f"{y}{m:02d}"

def discover_month(yyyymm: str) -> list[dict]:
    """Return list of {'id': '0000', 'url': '...', 'yyyymm': 'YYYYMM'} for the month."""
    url = urljoin(ARCHIVE_ROOT, f"{yyyymm}/")
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if A_MSG.match(href):
            out.append({"id": href[:-5], "url": urljoin(url, href), "yyyymm": yyyymm})
    # de-dup preserve order
    seen, uniq = set(), []
    for it in out:
        if it["id"] in seen: continue
        seen.add(it["id"]); uniq.append(it)
    return uniq

def main():
    ap = argparse.ArgumentParser(description="Fetch AMBER HTML directly from monthly indexes (no manifests).")
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, required=True)
    ap.add_argument("--since", help="YYYY-MM inclusive start")
    ap.add_argument("--until", help="YYYY-MM inclusive end")
    ap.add_argument("--limit", type=int, help="Max messages per month")
    ap.add_argument("--out-dir", default=str(HTML_DIR_DEFAULT))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update({"User-Agent": "AmberFetcher/2.0"})

    for yyyymm in iter_months(args.start_year, args.end_year, args.since, args.until):
        month = out_dir / yyyymm
        month.mkdir(parents=True, exist_ok=True)
        try:
            items = discover_month(yyyymm)
        except requests.HTTPError as e:
            print(f"==> {yyyymm} ERROR: {e}", file=sys.stderr)
            continue

        if args.limit is not None:
            items = items[: max(0, args.limit)]

        saved = skipped = 0
        for it in items:
            fn = month / f"{it['id']}.html"
            if fn.exists() and not args.force:
                skipped += 1
                continue
            r = s.get(it["url"], timeout=30)
            r.raise_for_status()
            fn.write_text(r.text, encoding="utf-8")
            saved += 1
            time.sleep(0.1)  # be polite
        print(f"==> {yyyymm} saved={saved} skipped={skipped} -> {month}")

if __name__ == "__main__":
    main()