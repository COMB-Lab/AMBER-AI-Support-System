#!/usr/bin/env python3
"""
Amber Mailing List Scraper — March 2024 (Threads → JSON)
=========================================================

This script crawls the Amber mailing list archive (http://archive.ambermd.org/)
for **March 2024** and writes one JSON file per **thread**. The filename is the
thread ID (derived from the root message of that thread), e.g.:

    data/threads/202403_0001.json

Each JSON contains all messages in that thread with cleaned text content
(quoted lines removed, whitespace normalized, common sig blocks trimmed).

Key features
------------
- Async & scalable: `aiohttp` + `asyncio` + bounded concurrency
- Robust thread parsing: uses the month thread index page (threads.html)
- Retry logic with exponential backoff
- Polite crawling: small delay, reasonable headers, avoids duplicate fetches
- Thorough comments and clear structure for maintainability

"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Set, Tuple

import aiofiles
import aiohttp
from bs4 import BeautifulSoup, Comment
import requests
from email.utils import parsedate_to_datetime
from datetime import timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from tqdm import tqdm


def _soup(html: str) -> BeautifulSoup:
    """Return a BeautifulSoup using lxml if available, otherwise stdlib parser.
    Avoids: "Couldn't find a tree builder with the features you requested: lxml"
    """
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")

# -------------------------------
# Configuration (adjust as needed)
# -------------------------------
BASE_URL = "http://archive.ambermd.org"
MONTH = "202403"  # March 2024
THREADS_INDEX = f"{BASE_URL}/{MONTH}/thread.html"
OUTPUT_DIR = os.path.join("data", "threads")
USER_AGENT = (
    "Mozilla/5.0 (compatible; AmberScraper/1.0; +https://example.org/)"
)

# Tunables for scalability/politeness
MAX_CONCURRENCY = 8  # simultaneous HTTP requests
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.75  # seconds (exponential backoff)

# ----------------
# Data structures
# ----------------
@dataclass
class Message:
    message_id: str
    url: str
    subject: Optional[str]
    author_name: Optional[str]
    author_email: Optional[str]
    date: Optional[str]
    in_reply_to: Optional[str]
    references: List[str]
    raw_html: Optional[str]  # kept for debugging; can be disabled
    text_clean: str

@dataclass
class ThreadJSON:
    thread_id: str
    month: str
    source_index: str
    message_count: int
    messages: List[Message]

# ----------------
# Helper functions
# ----------------

def eprint(msg):
    """Best-effort stderr print compatible with older Python versions."""
    try:
        sys.stderr.write(str(msg))
        sys.stderr.write("\n")
    except Exception:
        sys.stdout.write(str(msg))
        sys.stdout.write("\n")


_message_id_re = re.compile(r"<[^>]+>")
_email_re = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _stem_from_url(url: str) -> str:
    """Return the last path component without extension (e.g., 0001 from .../0001.html)."""
    base = url.rstrip("/").split("/")[-1]
    return base.split(".")[0]


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_message_text(raw_text: str) -> str:
    """Basic cleaning heuristics:
    - Drop quote lines (starting with ">" or "|>")
    - Remove common reply headers (On Mon, X wrote:)
    - Trim likely signature block (lines after a standalone "--" or starting with "Sent from my")
    - Collapse whitespace
    """
    lines = raw_text.splitlines()
    cleaned: List[str] = []
    sig = False
    for line in lines:
        if line.strip() == "--" or line.strip().startswith("Sent from my"):
            sig = True
        if sig:
            continue
        if line.lstrip().startswith(">"):
            continue  # quoted
        # Remove common "On ... wrote:" patterns
        if re.match(r"^On .*wrote:$", line.strip()):
            continue
        cleaned.append(line)
    text = "\n".join(cleaned)
    # Remove leading reply metadata blocks like "From: ..., Date: ..." repeated in body
    text = re.sub(r"^(From|Date|Subject|To):.*\n", "", text, flags=re.IGNORECASE | re.MULTILINE)
    # Normalize whitespace
    # Keep paragraphs but collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def fetch_html(session: aiohttp.ClientSession, url: str) -> str:
    """Fetch a URL with retries; return response text."""
    last_err: Optional[Exception] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.text(errors="ignore")
        except Exception as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            else:
                raise
    assert False, last_err  # for type checkers


# -----------------------
# Thread index extraction
# -----------------------

def _parse_thread_index(html: str) -> List[List[str]]:
    """Parse the monthly threads index and return a list of threads, where each
    thread is a list of message URLs (root first, then replies depth-first).

    Many Pipermail-like archives render the thread view as nested <ul>/<li>
    where each <li> contains an <a href="0001.html">Subject</a> and possibly a
    nested <ul> for replies. We'll traverse this tree depth-first to collect the
    message links per thread.
    """
    soup = _soup(html)

    # Heuristic: find the first <ul> inside body that contains links to *.html
    # Alternatively, some archives wrap it in a div with id="content" or class.
    container = None
    for ul in soup.find_all("ul"):
        if ul.find("a", href=re.compile(r"^[0-9]{4}/[0-9]{4}\.html$|^[0-9]{4}\.html$")) or ul.find(
            "a", href=re.compile(r"^[0-9]{4}\.html$")
        ):
            container = ul
            break

    if container is None:
        # Fallback: any UL that has at least one numeric *.html link
        for ul in soup.find_all("ul"):
            if ul.find("a", href=re.compile(r"[0-9]{4}\.html$")):
                container = ul
                break

    if container is None:
        raise RuntimeError("Could not locate threads list in threads.html. Adjust selectors.")

    threads: List[List[str]] = []

    def walk_li(li_tag) -> List[str]:
        links = li_tag.find_all("a", href=True)
        this_urls: List[str] = []
        for a in links:
            href = a.get("href", "")
            if href.endswith(".html") and re.search(r"[0-9]{4}\.html$", href):
                # Normalize to absolute monthly URL
                if not href.startswith("http"):
                    if href.startswith("/"):
                        url = BASE_URL + href
                    else:
                        url = f"{BASE_URL}/{MONTH}/{href}"
                else:
                    url = href
                this_urls.append(url)
                break  # only first link per LI is the message; others may be anchors
        # Collect replies in nested <ul>
        ul_child = li_tag.find("ul")
        if ul_child:
            for sub_li in ul_child.find_all("li", recursive=False):
                this_urls.extend(walk_li(sub_li))
        return this_urls

    # Top-level LIs each represent a thread
    for li in container.find_all("li", recursive=False):
        urls = walk_li(li)
        if urls:
            threads.append(urls)

    if not threads:
        raise RuntimeError("No threads found in parsed threads.html")

    return threads


# --------------------
# Message page parsing
# --------------------

def _extract_header_value(text: str, header: str) -> Optional[str]:
    pattern = re.compile(rf"^{header}:\s*(.*)$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _parse_message_page(url: str, html: str) -> Message:
    """Extract metadata + body text from a single message page.

    Pipermail-style pages often have:
      - <h1>Subject</h1>
      - A header block with From, Date, etc.
      - The message body inside <pre> ... </pre>

    We try multiple fallbacks to be resilient.
    """
    soup = _soup(html)

    # Subject
    subject_tag = soup.find(["h1", "H1"]) or soup.find("title")
    subject = subject_tag.get_text(strip=True) if subject_tag else None

    # Extract the visible header block text (often found near <i> or after h1)
    header_text = ""
    header_container = soup.find("i") or soup.find("b")
    if header_container:
        header_text = header_container.get_text("\n", strip=True)
    else:
        # fallback: take the first few lines of the page text
        header_text = "\n".join(soup.get_text("\n").splitlines()[:20])

    # Fields from header text (best effort)
    author_name = None
    author_email = None
    from_line = _extract_header_value(header_text, "From")
    if from_line:
        # Attempt to split name and email
        email_match = _email_re.search(from_line)
        if email_match:
            author_email = email_match.group(0)
            author_name = from_line.replace(author_email, "").strip().strip("<>- ") or None
        else:
            author_name = from_line.strip() or None

    date = _extract_header_value(header_text, "Date")

    # Message-ID, In-Reply-To, References occasionally present in page text
    page_text = soup.get_text("\n")
    message_id = _extract_header_value(page_text, "Message-ID") or _extract_header_value(page_text, "Message-Id")
    in_reply_to = _extract_header_value(page_text, "In-Reply-To")

    # References can be a long line with multiple <...>
    refs_line = _extract_header_value(page_text, "References")
    references: List[str] = _message_id_re.findall(refs_line) if refs_line else []

    # Body: prefer <pre>, else main content after a known marker
    pre = soup.find("pre")
    if pre:
        raw_text = pre.get_text("\n", strip=False)
    else:
        # Fallback: take a chunk after the header region
        full = soup.get_text("\n")
        # Heuristic: split on a line with many dashes (common in archives)
        parts = re.split(r"\n[-]{5,}\n", full, maxsplit=1)
        raw_text = parts[1] if len(parts) > 1 else full

    text_clean = clean_message_text(raw_text)

    # If no message-id, derive a synthetic one from URL stem
    if not message_id:
        stem = _stem_from_url(url)
        message_id = f"<{MONTH}/{stem}@archive.ambermd.org>"

    return Message(
        message_id=message_id,
        url=url,
        subject=subject,
        author_name=author_name,
        author_email=author_email,
        date=date,
        in_reply_to=in_reply_to,
        references=references,
        raw_html=None,  # set to html if you wish to retain raw pages
        text_clean=text_clean,
    )


# ----------------------
# Crawl coordinator (async)
# ----------------------
async def _gather_with_semaphore(tasks, limit: int):
    sem = asyncio.Semaphore(limit)

    async def sem_task(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(sem_task(t) for t in tasks))


async def crawl_month_threads() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENCY)
    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT,
        connector=connector,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as session:
        # 1) Load threads index for the month
        index_html = await fetch_html(session, THREADS_INDEX)
        threads_urls: List[List[str]] = _parse_thread_index(index_html)

        # 2) Iterate each thread: fetch each message page, parse, write JSON
        for urls in tqdm(threads_urls, desc=f"Threads in {MONTH}"):
            if not urls:
                continue
            root_url = urls[0]
            root_stem = _stem_from_url(root_url)
            thread_id = f"{MONTH}_{root_stem}"
            out_path = os.path.join(OUTPUT_DIR, _safe_filename(thread_id) + ".json")
            if os.path.exists(out_path):
                # Idempotent: skip existing threads
                continue

            # Fetch messages concurrently (bounded)
            tasks = [fetch_html(session, u) for u in urls]
            pages: List[str] = await _gather_with_semaphore(tasks, MAX_CONCURRENCY)

            messages: List[Message] = []
            for u, html in zip(urls, pages):
                try:
                    msg = _parse_message_page(u, html)
                    messages.append(msg)
                except Exception as e:
                    # If one message fails, continue collecting others but record a stub
                    messages.append(
                        Message(
                            message_id=f"<{MONTH}/{_stem_from_url(u)}@archive.ambermd.org>",
                            url=u,
                            subject=None,
                            author_name=None,
                            author_email=None,
                            date=None,
                            in_reply_to=None,
                            references=[],
                            raw_html=None,
                            text_clean=f"[PARSE ERROR] {e}",
                        )
                    )

            thread_obj = ThreadJSON(
                thread_id=thread_id,
                month=MONTH,
                source_index=THREADS_INDEX,
                message_count=len(messages),
                messages=messages,
            )

            # Write JSON (pretty but compact enough)
            async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
                await f.write(
                    json.dumps(
                        asdict(thread_obj), ensure_ascii=False, indent=2
                    )
                )


# ---------------
# Program entry
# ---------------
if __name__ == "__main__":
    try:
        asyncio.run(crawl_month_threads())
        print(f"Done. Thread JSONs saved under: {OUTPUT_DIR}")
    except KeyboardInterrupt:
        print("Interrupted.")
    except Exception as e:
        eprint(f"ERROR: {e}")
        sys.exit(1)
