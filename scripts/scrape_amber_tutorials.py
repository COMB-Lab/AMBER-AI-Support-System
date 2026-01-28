#!/usr/bin/env python3
"""Prototype scraper for AmberMD tutorials.

This script collects tutorial links from https://ambermd.org/tutorials/,
fetches pages, extracts structured text sections, and writes out per-tutorial
JSON plus chunked JSONL suitable for ingestion into a vector DB like Chroma.

This is a research prototype — it's forgiving about HTML structure and logs
failures for manual inspection.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import argparse
from tenacity import retry, wait_exponential, stop_after_attempt

BASE = "https://ambermd.org"
INDEX = f"{BASE}/tutorials/"
OUT_DIR = Path("data") / "tutorials"
CHUNK_OUT = Path("data") / "tutorials_chunks"
UA = "amber-tutorial-scraper/0.1 (+https://example.org/)"


@retry(wait=wait_exponential(min=1, max=20), stop=stop_after_attempt(3))
def fetch(url: str, timeout: int = 15) -> Optional[str]:
    headers = {"User-Agent": UA}
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code == 200:
        return resp.text
    # raise for non-200 so tenacity can retry on server errors
    resp.raise_for_status()
    return None


def parse_index(html: str, domain_filter: Optional[str] = None) -> List[str]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        # Accept links that appear to be tutorial pages
        if ('tutorial' in href.lower()) or href.startswith('/tutorials') or href.endswith('.php') or href.endswith('.html'):
            full = urljoin(INDEX, href)
            # normalize fragment/query
            p = urlparse(full)
            full = p.scheme + "://" + p.netloc + p.path
            if domain_filter:
                if urlparse(full).netloc.endswith(domain_filter):
                    links.add(full)
            else:
                links.add(full)
    # return sorted to have deterministic order
    return sorted(links)


def extract_main_text(html: str) -> Dict:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    # try common main containers
    main = soup.find(id="content") or soup.find("main") or soup.find("article") or soup.body

    # remove navigation/footer/header elements
    for sel in main.select("nav, header, footer, .nav, .menu, .breadcrumb, .breadcrumbs") if main else []:
        sel.decompose()

    sections = []
    if main is None:
        return {"title": "", "sections": [], "full_text": ""}

    title_tag = main.find(["h1", "h2"]) or soup.find(["h1", "h2"]) or None
    title = title_tag.get_text(strip=True) if title_tag else ""

    current = {"heading": "", "text": []}
    for el in main.find_all(recursive=False):
        # top-level headings
        if el.name and re.match(r'h[1-4]', el.name):
            if current["text"]:
                sections.append({"heading": current["heading"], "text": "\n\n".join(current["text"])})
            current = {"heading": el.get_text(strip=True), "text": []}
        elif el.name in ("p", "pre", "div"):
            txt = el.get_text("\n", strip=True)
            if txt:
                current["text"].append(txt)
        elif el.name in ("ul", "ol"):
            items = [li.get_text(" ", strip=True) for li in el.find_all("li")]
            if items:
                current["text"].append("\n".join(items))

    # flush
    if current and current["text"]:
        sections.append({"heading": current["heading"], "text": "\n\n".join(current["text"])})

    full_text = "\n\n".join([(s.get("heading") + "\n" + s.get("text")) if s.get("heading") else s.get("text") for s in sections])
    return {"title": title, "sections": sections, "full_text": full_text}


def slug_from_url(url: str) -> str:
    p = urlparse(url)
    slug = p.path.strip('/').replace('/', '_') or 'root'
    slug = re.sub(r'[^A-Za-z0-9_\-\.]+', '_', slug)
    return slug[:200]


def chunk_text(text: str, max_chars: int = 2000) -> List[str]:
    # naive splitter by paragraphs, group until max_chars
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chunks = []
    cur = []
    cur_len = 0
    for p in paras:
        if cur_len + len(p) + 2 > max_chars and cur:
            chunks.append('\n\n'.join(cur))
            cur = [p]
            cur_len = len(p)
        else:
            cur.append(p)
            cur_len += len(p) + 2
    if cur:
        chunks.append('\n\n'.join(cur))
    return chunks


def save_tutorial(url: str, scraped: Dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CHUNK_OUT.mkdir(parents=True, exist_ok=True)
    slug = slug_from_url(url)
    out_path = OUT_DIR / (slug + '.json')
    meta = {
        'url': url,
        'title': scraped.get('title', ''),
    }
    obj = {**meta, 'sections': scraped.get('sections', []), 'full_text': scraped.get('full_text', '')}
    out_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

    # write chunks JSONL for vector DB ingestion (id, text, metadata)
    chunks = chunk_text(obj['full_text'])
    chunk_path = CHUNK_OUT / (slug + '_chunks.jsonl')
    with chunk_path.open('w', encoding='utf-8') as f:
        for i, c in enumerate(chunks):
            doc = {'id': f"{slug}-{i}", 'text': c, 'metadata': meta}
            f.write(json.dumps(doc, ensure_ascii=False) + '\n')


def main(limit: Optional[int] = None):
    parser = argparse.ArgumentParser(description='Scrape Amber tutorials')
    parser.add_argument('--limit', type=int, default=limit)
    parser.add_argument('--domain', type=str, default='ambermd.org', help='Restrict links to this domain (e.g., ambermd.org)')
    parser.add_argument('--delay', type=float, default=0.5)
    parser.add_argument('--checkpoint', type=str, default=str(OUT_DIR / 'processed_urls.json'))
    args = parser.parse_args()

    print(f"Fetching index: {INDEX}")
    try:
        idx_html = fetch(INDEX)
    except Exception as e:
        print(f"Failed to fetch index: {e}")
        return
    if not idx_html:
        print("Failed to fetch index")
        return
    links = parse_index(idx_html, domain_filter=args.domain)
    print(f"Found {len(links)} candidate links (filtered by domain={args.domain})")
    count = 0
    # load checkpoint
    checkpoint_path = Path(args.checkpoint)
    processed = set()
    if checkpoint_path.exists():
        try:
            processed = set(json.loads(checkpoint_path.read_text(encoding='utf-8')))
        except Exception:
            processed = set()
    for url in links:
        if limit and count >= limit:
            break
        if url in processed:
            print(f"Skipping already processed {url}")
            continue
        print(f"Processing {url}")
        html = fetch(url)
        # try fallback: if 404 or None, attempt adding /index.php
        if html is None:
            if not url.endswith('/'):
                alt = url.rstrip('/') + '/index.php'
            else:
                alt = urljoin(url, 'index.php')
            print(f"Trying fallback {alt}")
            html = fetch(alt)
            if html:
                url = alt
        if not html:
            print(f"Skipping {url} (no content)")
            continue
        scraped = extract_main_text(html)
        save_tutorial(url, scraped)
        processed.add(url)
        # update checkpoint
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(json.dumps(sorted(list(processed))), encoding='utf-8')
        except Exception:
            pass
        count += 1
        time.sleep(args.delay)

    print(f"Processed {count} pages; checkpoint written to {checkpoint_path}")


if __name__ == '__main__':
    # demo run: default limit 10 if not provided via CLI
    main(limit=10)
