#!/usr/bin/env python3
import argparse, json, re, sys, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ARCHIVE_ROOT = "http://archive.ambermd.org/"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data"   # Data Scraping & Cleaning/data
MANIFESTS = DATA_ROOT / "manifests"
HTML_DIR = DATA_ROOT / "html"

A_MSG = re.compile(r"^0\d{3}\.html$")  # 0000.html pattern

def ym_to_int(ym: str | None) -> int | None:
    if not ym: return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", ym)
    return int(m.group(1))*100 + int(m.group(2)) if m else None

def iter_months(start_year: int, end_year: int, since: str | None, until: str | None):
    now = datetime.now()
    cur_ym = now.year*100 + now.month
    s = ym_to_int(since) or (start_year*100 + 1)
    u = min(ym_to_int(until) or (end_year*100 + 12), cur_ym)
    for y in range(start_year, end_year+1):
        for m in range(1, 13):
            ym = y*100 + m
            if ym < s or ym > u: continue
            yield f"{y}{m:02d}"

def discover_month(yyyymm: str) -> list[dict]:
    url = urljoin(ARCHIVE_ROOT, f"{yyyymm}/")
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if A_MSG.match(href):
            out.append({
                "id": href[:-5],  # '0000'
                "url": urljoin(url, href),
                "yyyymm": yyyymm,
                "filename": f"{href}"
            })
    # de-dup preserving order
    seen = set(); uniq = []
    for it in out:
        if it["id"] in seen: continue
        seen.add(it["id"]); uniq.append(it)
    return uniq

def main():
    ap = argparse.ArgumentParser(description="Discover AMBER monthly message URLs and write manifests.")
    ap.add_argument("--start-year", type=int, required=True)
    ap.add_argument("--end-year", type=int, required=True)
    ap.add_argument("--since", help="YYYY-MM inclusive start")
    ap.add_argument("--until", help="YYYY-MM inclusive end")
    ap.add_argument("--limit", type=int, help="Max messages per month")
    ap.add_argument("--force", action="store_true", help="Rewrite manifests")
    args = ap.parse_args()

    MANIFESTS.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)

    for yyyymm in iter_months(args.start_year, args.end_year, args.since, args.until):
        month_manifest = MANIFESTS / f"{yyyymm}.json"
        if month_manifest.exists() and not args.force:
            print(f"==> {yyyymm} (manifest exists; skip)")
            continue
        try:
            msgs = discover_month(yyyymm)
            if args.limit is not None:
                msgs = msgs[: max(0, args.limit)]
            month_manifest.write_text(json.dumps(msgs, indent=2), encoding="utf-8")
            print(f"==> {yyyymm} discovered={len(msgs)} wrote={month_manifest}")
            # prepare html folder
            (HTML_DIR / yyyymm).mkdir(parents=True, exist_ok=True)
            time.sleep(0.2)
        except requests.HTTPError as e:
            print(f"==> {yyyymm} ERROR: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()