#!/usr/bin/env python3
"""
Amber Mailing List Scraper — 2020–2025 (per-thread JSON with epoch IDs)

What it does
------------
- Crawls http://archive.ambermd.org for every month from 2020–2025
- Loads each month’s thread index (handles directory, index.html, thread.html, threads.html)
- Follows links to individual message pages
- Groups messages into threads (one JSON per mail chain)
- IDs are numeric epoch timestamps:
    * message_id  = epoch(Date header) in UTC
    * thread_id   = message_id of the root message
    * in_reply_to = thread_id on replies
- Writes: data/threads/YYYY-MM/<thread_id>.json
- **Cross-month reconcile**: after crawling, merges replies whose parent
  lives in another month using raw Message-ID/In-Reply-To headers.


"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional

import aiofiles
import aiohttp
from bs4 import BeautifulSoup
from tqdm import tqdm

# -------------------------------
# Config
# -------------------------------
BASE_URL = "http://archive.ambermd.org"
OUTPUT_DIR = os.path.join("data", "threads")
USER_AGENT = "Mozilla/5.0 (compatible; AmberScraper/1.2; +https://example.org/)"

MAX_CONCURRENCY = 8
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.75  # seconds

# -------------------------------
# Utilities
# -------------------------------
def eprint(msg):
    """Best-effort stderr print (portable)."""
    try:
        sys.stderr.write(str(msg) + "\n")
    except Exception:
        sys.stdout.write(str(msg) + "\n")


def _soup(html: str) -> BeautifulSoup:
    """Prefer lxml; fallback to stdlib HTML parser."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _stem_from_url(url: str) -> str:
    base = url.rstrip("/").split("/")[-1]
    return base.split(".")[0]


def clean_message_text(raw_text: str) -> str:
    """Drop quoted lines/headers, trim common sigs, normalize whitespace."""
    lines = raw_text.splitlines()
    out: List[str] = []
    in_sig = False
    for line in lines:
        s = line.strip()
        if s == "--" or s.startswith("Sent from my"):
            in_sig = True
        if in_sig:
            continue
        if line.lstrip().startswith(">"):
            continue
        if re.match(r"^On .*wrote:$", s):
            continue
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"^(From|Date|Subject|To):.*\n", "", text, flags=re.I | re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _epoch_from_date(date_raw: str, url_stem: str, month_for_fallback: str) -> int:
    """RFC2822 Date -> UTC epoch; deterministic fallback for odd inputs."""
    try:
        if date_raw:
            dt = parsedate_to_datetime(date_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.astimezone(timezone.utc).timestamp())
    except Exception:
        pass
    # Fallback: first-of-month UTC + stem*60s
    try:
        y = int(month_for_fallback[:4]); m = int(month_for_fallback[4:6])
    except Exception:
        y, m = 1970, 1
    try:
        n = int(url_stem)
    except Exception:
        n = 0
    base = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
    return base + n * 60


async def fetch_html(session: aiohttp.ClientSession, url: str) -> str:
    """HTTP GET with retries; returns response text."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.text(errors="ignore")
        except Exception:
            if attempt < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            else:
                raise


async def _fetch_month_index(session: aiohttp.ClientSession, month: str) -> str:
    """Try common month index URLs; return the first valid HTML."""
    candidates = [
        f"{BASE_URL}/{month}/",
        f"{BASE_URL}/{month}/index.html",
        f"{BASE_URL}/{month}/thread.html",
        f"{BASE_URL}/{month}/threads.html",
    ]
    last_err = None
    for url in candidates:
        try:
            html = await fetch_html(session, url)
            # sanity: many 000*.html links on the page
            if re.search(r'href="0\d{3}\.html"', html):
                return html
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not load a valid month index for {month}. Last error: {last_err}")


# -------------------------------
# Parsing helpers
# -------------------------------
HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z-]*):\s*(.*)$", re.I | re.M)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ANGLE_ID_RE = re.compile(r"<[^>]+>")


def _extract_header_value(text: str, header: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(header)}:\s*(.*)$", text, flags=re.I | re.M)
    return m.group(1).strip() if m else None


@dataclass
class Message:
    message_id: str           # numeric epoch (filled later)
    url: str
    subject: Optional[str]
    author_name: Optional[str]
    author_email: Optional[str]
    date: Optional[str]
    in_reply_to: Optional[str]
    references: List[str]
    raw_html: Optional[str]
    text_clean: str
    # raw linkage headers captured for cross-month reconcile
    message_id_hdr: Optional[str] = None
    in_reply_to_hdr: Optional[str] = None
    references_hdr: Optional[List[str]] = None


def _parse_message_page(url: str, html: str, month: str) -> Message:
    """Extract subject/headers/body from a single message page."""
    soup = _soup(html)

    # Subject
    subject_tag = soup.find(["h1", "H1"]) or soup.find("title")
    subject = subject_tag.get_text(strip=True) if subject_tag else None

    # Header-ish block (best-effort)
    header_container = soup.find("i") or soup.find("b")
    header_text = header_container.get_text("\n", strip=True) if header_container else "\n".join(
        soup.get_text("\n").splitlines()[:20]
    )

    # From: split name/email
    author_name = None
    author_email = None
    from_line = _extract_header_value(header_text, "From")
    if from_line:
        m = EMAIL_RE.search(from_line)
        if m:
            author_email = m.group(0)
            author_name = from_line.replace(author_email, "").strip().strip("<>- ") or None
        else:
            author_name = from_line.strip() or None

    date = _extract_header_value(header_text, "Date")

    # Optional headers present in page text
    page_text = soup.get_text("\n")
    message_id_hdr = _extract_header_value(page_text, "Message-ID") or _extract_header_value(page_text, "Message-Id")
    in_reply_to_hdr = _extract_header_value(page_text, "In-Reply-To")
    refs_line = _extract_header_value(page_text, "References")
    references_list = ANGLE_ID_RE.findall(refs_line) if refs_line else []

    # Body
    pre = soup.find("pre")
    raw_text = pre.get_text("\n", strip=False) if pre else soup.get_text("\n")
    text_clean = clean_message_text(raw_text)

    # Synthetic Message-ID header if missing (for reconcile lookup)
    if not message_id_hdr:
        stem = _stem_from_url(url)
        message_id_hdr = f"<{month}/{stem}@archive.ambermd.org>"

    # NOTE: numeric message_id gets computed during bundling via _epoch_from_date
    return Message(
        message_id="0",
        url=url,
        subject=subject,
        author_name=author_name,
        author_email=author_email,
        date=date,
        in_reply_to=None,
        references=references_list,
        raw_html=None,
        text_clean=text_clean,
        message_id_hdr=message_id_hdr,
        in_reply_to_hdr=in_reply_to_hdr,
        references_hdr=references_list,
    )


def _parse_thread_index(html: str, month: str) -> List[List[str]]:
    """Parse a month’s thread view (nested UL/LI) → list of threads (list of message URLs)."""
    soup = _soup(html)

    # Heuristic: first UL that contains 000*.html links
    container = None
    for ul in soup.find_all("ul"):
        if ul.find("a", href=re.compile(r"^[0-9]{4}\.html$")) or ul.find(
            "a", href=re.compile(r"^[0-9]{4}/[0-9]{4}\.html$")
        ):
            container = ul
            break
    if container is None:
        for ul in soup.find_all("ul"):
            if ul.find("a", href=re.compile(r"[0-9]{4}\.html$")):
                container = ul
                break
    if container is None:
        raise RuntimeError("Could not locate threads list in month index.")

    threads: List[List[str]] = []

    def walk_li(li_tag) -> List[str]:
        links = li_tag.find_all("a", href=True)
        this_urls: List[str] = []
        for a in links:
            href = a.get("href", "")
            if href.endswith(".html") and re.search(r"[0-9]{4}\.html$", href):
                if not href.startswith("http"):
                    if href.startswith("/"):
                        url = BASE_URL + href
                    else:
                        url = f"{BASE_URL}/{month}/{href}"
                else:
                    url = href
                this_urls.append(url)
                break  # first link in this LI is the message
        ul_child = li_tag.find("ul")
        if ul_child:
            for sub_li in ul_child.find_all("li", recursive=False):
                this_urls.extend(walk_li(sub_li))
        return this_urls

    for li in container.find_all("li", recursive=False):
        urls = walk_li(li)
        if urls:
            threads.append(urls)

    if not threads:
        raise RuntimeError("No threads found in parsed month index.")
    return threads


# ----------------------
# Async crawl orchestration
# ----------------------
async def _gather_with_semaphore(tasks, limit: int):
    sem = asyncio.Semaphore(limit)

    async def sem_task(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*(sem_task(t) for t in tasks))


async def crawl_month_threads(month: str) -> int:
    """
    Crawl one month (YYYYMM), merge messages by thread, write <thread_id>.json files.
    Returns the number of thread files written.
    """
    out_dir = os.path.join(OUTPUT_DIR, f"{month[:4]}-{month[4:6]}")
    os.makedirs(out_dir, exist_ok=True)

    connector = aiohttp.TCPConnector(limit_per_host=MAX_CONCURRENCY)
    written = 0

    async with aiohttp.ClientSession(
        timeout=REQUEST_TIMEOUT,
        connector=connector,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    ) as session:
        index_html = await _fetch_month_index(session, month)
        threads_urls = _parse_thread_index(index_html, month)

        for urls in tqdm(threads_urls, desc=f"Threads in {month}"):
            if not urls:
                continue

            pages = await _gather_with_semaphore(
                [fetch_html(session, u) for u in urls],
                MAX_CONCURRENCY,
            )

            messages: List[Message] = []
            for u, html in zip(urls, pages):
                try:
                    messages.append(_parse_message_page(u, html, month))
                except Exception as e:
                    m_stem = _stem_from_url(u)
                    messages.append(
                        Message(
                            message_id="0",
                            url=u,
                            subject=None,
                            author_name=None,
                            author_email=None,
                            date=None,
                            in_reply_to=None,
                            references=[],
                            raw_html=None,
                            text_clean=f"[PARSE ERROR] {e}",
                            message_id_hdr=f"<{month}/{m_stem}@archive.ambermd.org>",
                            in_reply_to_hdr=None,
                            references_hdr=[],
                        )
                    )

            if not messages:
                continue

            # Thread bundling (epoch IDs)
            root_msg = messages[0]
            root_stem = _stem_from_url(root_msg.url)
            thread_epoch = _epoch_from_date(root_msg.date or "", root_stem, month)
            subject = root_msg.subject or ""

            thread_bundle = {
                "thread_id": thread_epoch,
                "subject": subject,
                "messages": [],
            }

            for i, msg in enumerate(messages):
                stem = _stem_from_url(msg.url)
                msg_epoch = _epoch_from_date(msg.date or "", stem, month)
                entry = {
                    "message_id": msg_epoch,
                    "author": msg.author_name or (msg.author_email or None),
                    "date_raw": msg.date,
                    "body": msg.text_clean,
                    "url": msg.url,
                    # keep raw headers for post-pass reconcile
                    "message_id_hdr": msg.message_id_hdr,
                    "in_reply_to_hdr": msg.in_reply_to_hdr,
                    "references_hdr": msg.references_hdr or [],
                }
                if i > 0:
                    entry["in_reply_to"] = thread_epoch
                thread_bundle["messages"].append(entry)

            out_path = os.path.join(out_dir, f"{thread_epoch}.json")
            if os.path.exists(out_path):
                continue  # idempotent

            tmp_path = out_path + ".tmp"
            try:
                async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                    await f.write(json.dumps(thread_bundle, ensure_ascii=False, indent=2))
                os.replace(tmp_path, out_path)
                written += 1
            except Exception as err:
                eprint(f"Atomic rename failed for {tmp_path} → {out_path}: {err}")
                raise

    return written


def months_range_yyyymm(year_start=2020, year_end=2025) -> List[str]:
    return [f"{y}{m:02d}" for y in range(year_start, year_end + 1) for m in range(1, 13)]


async def crawl_all_months(year_start=2020, year_end=2025) -> None:
    total_threads = 0
    for month in months_range_yyyymm(year_start, year_end):
        try:
            wrote = await crawl_month_threads(month)
            print(f"{month}: wrote {wrote} threads")
            total_threads += wrote
        except Exception as e:
            eprint(f"{month}: ERROR {e}")
    print(f"Done. Total thread files: {total_threads}")


# ----------------------
# Post-pass: cross-month reconcile
# ----------------------

def reconcile_threads_cross_months(root_dir: str = OUTPUT_DIR) -> None:
    """Merge replies whose `in_reply_to_hdr` points to a message in another file.

    Process:
      1) Build lookup: { raw Message-ID -> file path holding that message }
      2) Move replies into the parent's thread if parent is in a different file
      3) Sort messages by numeric 'message_id' (epoch) and rewrite files
      4) Remove any thread file that ends up empty after moves
    """
    files = sorted(glob.glob(os.path.join(root_dir, "*", "*.json")))
    id_to_file = {}
    file_to_thread = {}

    # Load & index
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            t = json.load(f)
        file_to_thread[fp] = t
        for m in t.get("messages", []):
            rid = m.get("message_id_hdr")
            if rid and rid not in id_to_file:
                id_to_file[rid] = fp

    # Plan moves
    moves = []  # (from_fp, to_fp, message_dict)
    for fp, t in file_to_thread.items():
        keep = []
        for m in t.get("messages", []):
            parent_raw = m.get("in_reply_to_hdr")
            if parent_raw and parent_raw in id_to_file:
                parent_fp = id_to_file[parent_raw]
                if parent_fp != fp:
                    moves.append((fp, parent_fp, m))
                    continue
            keep.append(m)
        t["messages"] = keep

    # Apply moves
    for from_fp, to_fp, m in moves:
        file_to_thread[to_fp].setdefault("messages", []).append(m)

    # Sort & write back; remove empties
    for fp, t in list(file_to_thread.items()):
        t["messages"].sort(key=lambda x: int(x.get("message_id", 0)))
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False, indent=2)
        if not t.get("messages"):
            try:
                os.remove(fp)
            except Exception as e:
                eprint(f"Could not remove empty thread file {fp}: {e}")


# ----------------------
# Program entry
# ----------------------

def _run_coro(coro):
    """Run an async coroutine in both script and notebook/REPL contexts.

    - Prefers asyncio.run when no loop is running (normal script usage).
    - If a loop *is* running (e.g., Jupyter), tries `nest_asyncio` so we can
      nest an event loop safely; otherwise prints a helpful warning.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            try:
                import nest_asyncio  # optional dep for notebooks
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            except Exception:
                eprint("[warn]: Detected a running event loop. Install 'nest_asyncio' or call me as: `await crawl_all_months(...)`. Skipping run.")
                return None
        else:

            return loop.run_until_complete(coro)
    except RuntimeError:

        return asyncio.run(coro)


if __name__ == "__main__":
    try:
        _run_coro(crawl_all_months(2020, 2025))
        print(f"Done. Thread JSONs saved under: {OUTPUT_DIR}")
        reconcile_threads_cross_months(OUTPUT_DIR)
        print("Cross-month reconciliation complete.")
    except KeyboardInterrupt:
        print("Interrupted.")
    except Exception as e:
        eprint(f"ERROR: {e}")
        sys.exit(1)
