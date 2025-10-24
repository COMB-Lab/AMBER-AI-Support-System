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

BASE = "https://ambermd.org"
INDEX = f"{BASE}/tutorials/"
OUT_DIR = Path("data") / "tutorials"
CHUNK_OUT = Path("data") / "tutorials_chunks"
UA = "amber-tutorial-scraper/0.1 (+https://example.org/)"


def fetch(url: str, timeout: int = 15) -> Optional[str]:
    headers = {"User-Agent": UA}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        else:
            print(f"Failed fetch {url}: {resp.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None


def parse_index(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        # Accept links under /tutorials/ and several php links
        if href.startswith("/tutorials") or \
           href.startswith("tutorials") or \
           href.startswith("/AmberTutorials") or \
           'tutorial' in href.lower():
            full = urljoin(INDEX, href)
            # normalize fragment/query
            p = urlparse(full)
            full = p.scheme + "://" + p.netloc + p.path
            links.add(full)
    # return sorted to have deterministic order
    return sorted(links)


def extract_main_text(html: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
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
    print(f"Fetching index: {INDEX}")
    idx_html = fetch(INDEX)
    if not idx_html:
        print("Failed to fetch index")
        return
    links = parse_index(idx_html)
    print(f"Found {len(links)} candidate links")
    count = 0
    for url in links:
        if limit and count >= limit:
            break
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
        count += 1
        time.sleep(0.5)


if __name__ == '__main__':
    # demo run: limit to small number to avoid heavy scraping
    main(limit=10)
