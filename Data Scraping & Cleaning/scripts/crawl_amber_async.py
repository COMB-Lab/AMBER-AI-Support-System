#!/usr/bin/env python3
"""
Crawl Amber mailing list archive and save RAW HTML for each message.

Examples:
  # Crawl 2020–2025 with default rate
  python scripts/crawl_amber_async.py --start-year 2020 --end-year 2025

  # Only months since 2024-01 (incremental)
  python scripts/crawl_amber_async.py --since 2024-01

  # Force re-download, faster concurrency but same polite rate
  python scripts/crawl_amber_async.py --force --concurrency 20 --rate 2.0
"""
import asyncio
import re
import json
import time
from dataclasses import dataclass, asdict
from typing import List, Tuple, Optional, Set
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from aiolimiter import AsyncLimiter
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

ROOT = "http://archive.ambermd.org/"
DATA_DIR = Path("scripts/data")  # matches your existing layout
HTML_DIR = DATA_DIR / "html"
MANIFEST_DIR = DATA_DIR / "manifests"

# --------- CLI ---------
import argparse
def parse_args():
    p = argparse.ArgumentParser(description="Amber archive crawler (RAW HTML downloader)")
    p.add_argument("--start-year", type=int, default=1999)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--since", type=str, default=None, help="YYYY-MM; only months >= this are crawled")
    p.add_argument("--concurrency", type=int, default=12, help="Max concurrent downloads")
    p.add_argument("--rate", type=float, default=1.5, help="Requests per second (global)")
    p.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout seconds")
    p.add_argument("--force", action="store_true", help="Re-download even if file exists")
    return p.parse_args()

# --------- Helpers ---------
def yyyymm_iter(start_year:int, end_year:int) -> List[Tuple[int,int]]:
    months = []
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            months.append((y, m))
    return months

def yyyymm_str(y:int, m:int) -> str:
    return f"{y:04d}{m:02d}"

def month_url(y:int, m:int) -> str:
    return urljoin(ROOT, f"{y:04d}{m:02d}/")

def ensure_dirs():
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

def month_manifest_path(y:int, m:int) -> Path:
    return MANIFEST_DIR / f"{y:04d}{m:02d}.json"

def html_path_for(y:int, m:int, msg_id:str) -> Path:
    return HTML_DIR / f"{y:04d}{m:02d}" / f"{msg_id}.html"

def parse_since(since: Optional[str]) -> Optional[Tuple[int,int]]:
    if not since:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", since)
    if not m: 
        raise ValueError("--since must be YYYY-MM")
    return (int(m.group(1)), int(m.group(2)))

# --------- HTTP client with rate limit & retries ---------
class Fetcher:
    def __init__(self, rate_per_sec: float, timeout: float):
        self.timeout = httpx.Timeout(timeout)
        # global rate limiter (tokens/sec)
        self.limiter = AsyncLimiter(max_rate=rate_per_sec, time_period=1.0)
        self.client = httpx.AsyncClient(timeout=self.timeout, headers={"User-Agent": "AmberCrawler/1.0"})

    async def close(self):
        await self.client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.ReadTimeout)),
        wait=wait_exponential_jitter(initial=0.5, max=10.0),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def get_text(self, url: str) -> str:
        async with self.limiter:
            resp = await self.client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.ReadTimeout)),
        wait=wait_exponential_jitter(initial=0.5, max=10.0),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def download_to(self, url: str, dest: Path):
        async with self.limiter:
            resp = await self.client.get(url, follow_redirects=True)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)

# --------- Parsing monthly page ---------
MSG_ID_RE = re.compile(r"(\d{4})\.html$")
COUNT_RE = re.compile(r"(\d+)\s+messages", re.I)

def extract_month_links_and_count(month_html: str, base_url: str) -> Tuple[List[str], Optional[int]]:
    soup = BeautifulSoup(month_html, "html.parser")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Accept relative '0001.html' or absolute '/YYYYMM/0001.html' or full URL
        if MSG_ID_RE.search(href):
            links.append(urljoin(base_url, href))
    # Deduplicate while preserving order
    seen: Set[str] = set()
    uniq_links = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq_links.append(u)

    # Find "N messages" in visible text
    text = soup.get_text(" ", strip=True)
    m = COUNT_RE.search(text)
    count = int(m.group(1)) if m else None
    return uniq_links, count

# --------- Manifest ---------
@dataclass
class MonthManifest:
    month: str           # YYYYMM
    url: str
    expected_count: Optional[int]
    discovered_count: int
    downloaded_count: int
    failed_urls: List[str]
    ts: float

# --------- Pipeline for one month ---------
async def process_month(fetcher: Fetcher, y:int, m:int, force: bool) -> MonthManifest:
    base = month_url(y, m)
    # 1) fetch monthly index
    month_html = await fetcher.get_text(base)
    # 2) parse links & expected count
    links, expected = extract_month_links_and_count(month_html, base)

    # 3) download each message
    downloaded = 0
    failures: List[str] = []

    sem = asyncio.Semaphore(50)  # local throttle for file I/O scheduling

    async def grab(url: str):
        nonlocal downloaded
        msg_id_match = MSG_ID_RE.search(urlparse(url).path)
        if not msg_id_match:
            failures.append(url)
            return
        msg_id = msg_id_match.group(1)
        dest = html_path_for(y, m, msg_id)
        if dest.exists() and not force and dest.stat().st_size > 0:
            return  # incremental skip
        try:
            await fetcher.download_to(url, dest)
            downloaded += 1
        except Exception:
            failures.append(url)

    tasks = []
    for u in links:
        await sem.acquire()
        async def _runner(u=u):
            try:
                await grab(u)
            finally:
                sem.release()
        tasks.append(asyncio.create_task(_runner()))
    if tasks:
        await asyncio.gather(*tasks)

    manifest = MonthManifest(
        month=yyyymm_str(y, m),
        url=base,
        expected_count=expected,
        discovered_count=len(links),
        downloaded_count=downloaded,
        failed_urls=failures,
        ts=time.time(),
    )

    # 4) write manifest
    manifest_path = month_manifest_path(y, m)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2))
    return manifest

# --------- Main ---------
async def amain():
    args = parse_args()
    ensure_dirs()
    since = parse_since(args.since)

    fetcher = Fetcher(rate_per_sec=args.rate, timeout=args.timeout)
    try:
        months = yyyymm_iter(args.start_year, args.end_year)
        # filter by --since
        if since:
            sy, sm = since
            months = [(y, m) for (y, m) in months if (y > sy) or (y == sy and m >= sm)]

        # run months sequentially to keep memory/logs sane; downloads inside each month are concurrent
        for y, m in months:
            print(f"==> {y}-{m:02d}  (url: {month_url(y,m)})")
            try:
                manifest = await process_month(fetcher, y, m, force=args.force)
                exp = manifest.expected_count if manifest.expected_count is not None else "?"
                print(f"    discovered={manifest.discovered_count}  expected={exp}  "
                      f"downloaded={manifest.downloaded_count}  failed={len(manifest.failed_urls)}")
            except Exception as e:
                print(f"    ERROR month {y}-{m:02d}: {e}")
    finally:
        await fetcher.close()

def main():
    asyncio.run(amain())

if __name__ == "__main__":
    main()