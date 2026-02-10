import os
import re
import json
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# -----------------------------
# Configuration
# -----------------------------
INDEX_URL = "https://ambermd.org/tutorials/"
BASE_DOMAIN = "ambermd.org"
ALLOWED_PREFIX = "/tutorials/"

OUT_DIR = "output"
PER_TUTORIAL_DIR = os.path.join(OUT_DIR, "tutorials")
OUT_JSON = os.path.join(OUT_DIR, "amber_tutorials.json")

REQUEST_TIMEOUT = (10, 30)
DELAY = 0.3
MIN_TEXT_LEN = 20

# Crawl behavior:
MAX_PAGES_PER_TUTORIAL = 25   # safety cap
CRAWL_SECTION_PAGES = True    # set False if you only want the main page

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ambermd.org/",
})

# -----------------------------
# URL helpers
# -----------------------------
def normalize_url(base, href):
    """Make href absolute and remove #fragment."""
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "javascript:")):
        return None
    u = urljoin(base, href)
    u, _ = urldefrag(u)
    return u

def is_allowed(url):
    """Limit to ambermd.org/tutorials/* and skip binary assets."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if p.netloc != BASE_DOMAIN:
        return False
    if not p.path.startswith(ALLOWED_PREFIX):
        return False
    if p.path.lower().endswith((
        ".pdf", ".zip", ".tar", ".gz",
        ".png", ".jpg", ".jpeg", ".gif", ".svg"
    )):
        return False
    return True

def same_tutorial_directory(root_url, candidate_url):
    """
    True if candidate_url is in the same directory as root_url.
    Example:
      root: .../tutorial18/index.php
      section: .../tutorial18/section1.php   -> True
      other: .../tutorial19/...             -> False
    """
    r = urlparse(root_url)
    c = urlparse(candidate_url)

    if r.netloc != c.netloc:
        return False

    # Directory path: everything up to last "/"
    root_dir = r.path.rsplit("/", 1)[0] + "/"
    cand_dir = c.path.rsplit("/", 1)[0] + "/"
    return root_dir == cand_dir

# -----------------------------
# Fetching
# -----------------------------
def fetch_html(url):
    """Fetch HTML or return None if not 200."""
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            print(f"[fetch_html] status={r.status_code} url={url}")
            return None
        return r.text
    except requests.RequestException as e:
        print(f"[fetch_html] ERROR {type(e).__name__}: {e}")
        return None

# -----------------------------
# Text helpers
# -----------------------------
def slugify(text):
    text = re.sub(r"[^\w\s.-]", "", text).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:160] or "untitled"

def normalize_whitespace(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

# -----------------------------
# Index parsing (label_id fix)
# -----------------------------
def parse_index_entries(index_html):
    """
    Extract tutorial label + title + URL from the index page.
    The label_id exists ONLY on the index page.
    """
    soup = BeautifulSoup(index_html, "html.parser")
    entries = []
    seen = set()

    num_label = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")   # 7.10 Title
    letter_label = re.compile(r"^([a-zA-Z])\.\s+(.+)$")   # a. Title

    for a in soup.find_all("a", href=True):
        link_text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        url = normalize_url(INDEX_URL, a["href"])

        if not url or not is_allowed(url):
            continue
        if url.rstrip("/") == INDEX_URL.rstrip("/"):
            continue
        if url in seen:
            continue

        m = num_label.match(link_text)
        m2 = None if m else letter_label.match(link_text)
        if not m and not m2:
            continue

        seen.add(url)

        if m:
            label_id, title = m.group(1), m.group(2)
        else:
            label_id, title = m2.group(1).lower(), m2.group(2)

        entries.append({
            "label_id": label_id.strip(),
            "title": title.strip(),
            "url": url
        })

    return entries

# -----------------------------
# Extract sections from a single page
# -----------------------------
def extract_sections_from_html(html):
    """
    Extracts structured text from one HTML page:
      - page_title
      - sections: [{heading, text}]
      - full_text
    """
    soup = BeautifulSoup(html, "html.parser")

    # remove common non-content
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    main = soup.find("main") or soup.find(id="content") or soup.body or soup
    if not main:
        return {"page_title": "", "sections": [], "full_text": ""}

    h1 = soup.find("h1") or main.find("h1") or main.find("h2")
    page_title = h1.get_text(" ", strip=True) if h1 else ""

    sections = []
    current_heading = "Introduction"
    buf = []

    def flush():
        nonlocal buf, current_heading
        if buf:
            sections.append({
                "heading": current_heading,
                "text": normalize_whitespace("\n".join(buf))
            })
            buf = []

    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "pre", "li"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            heading = el.get_text(" ", strip=True)
            if heading:
                flush()
                current_heading = heading
            continue

        txt = el.get_text("\n", strip=True) if el.name == "pre" else el.get_text(" ", strip=True)
        txt = normalize_whitespace(txt)
        if txt and len(txt) >= MIN_TEXT_LEN:
            buf.append(txt)

    flush()

    full_text = normalize_whitespace(
        "\n\n".join(f"{s['heading']}\n{s['text']}" for s in sections)
    )

    return {"page_title": page_title, "sections": sections, "full_text": full_text}

# -----------------------------
# NEW: discover section pages for a tutorial
# -----------------------------
def find_section_links(root_url, html):
    """
    Look for links like section1.php, section2.php, etc. inside the same tutorial directory.
    Returns a list of absolute URLs.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    # common Amber naming patterns: section1.php, section2.php, section1, etc.
    section_re = re.compile(r"(?:^|/)(section\d+)(?:\.\w+)?$", re.IGNORECASE)

    for a in soup.find_all("a", href=True):
        u = normalize_url(root_url, a["href"])
        if not u or not is_allowed(u):
            continue
        if not same_tutorial_directory(root_url, u):
            continue

        # only accept section-ish pages
        path = urlparse(u).path
        if section_re.search(path):
            links.add(u)

    # Sort section pages in numeric order if possible (section1, section2, ...)
    def section_sort_key(url):
        m = re.search(r"section(\d+)", url, re.IGNORECASE)
        return int(m.group(1)) if m else 10**9

    return sorted(links, key=section_sort_key)

def crawl_tutorial_pages(root_url):
    """
    Crawl the main tutorial page + its section pages (if any).
    Returns ordered list of page URLs to extract.
    """
    main_html = fetch_html(root_url)
    time.sleep(DELAY)
    if not main_html:
        return []

    pages = [root_url]

    if CRAWL_SECTION_PAGES:
        section_pages = find_section_links(root_url, main_html)
        for u in section_pages:
            if u not in pages:
                pages.append(u)

    # safety cap
    return pages[:MAX_PAGES_PER_TUTORIAL]

# -----------------------------
# Main
# -----------------------------
def main():
    os.makedirs(PER_TUTORIAL_DIR, exist_ok=True)

    index_html = fetch_html(INDEX_URL)
    if not index_html:
        print("Failed to fetch tutorials index.")
        return

    entries = parse_index_entries(index_html)
    print(f"Found {len(entries)} tutorials with labels.")

    all_results = []

    for e in tqdm(entries, desc="Extracting tutorials"):
        # 1) Determine which pages belong to this tutorial (main + sections)
        page_urls = crawl_tutorial_pages(e["url"])
        if not page_urls:
            continue

        pages_data = []
        combined_full_text_parts = []
        combined_sections = []

        # 2) Extract content from each page
        for pu in page_urls:
            html = fetch_html(pu)
            time.sleep(DELAY)
            if not html:
                continue

            extracted = extract_sections_from_html(html)

            pages_data.append({
                "url": pu,
                "page_title": extracted["page_title"],
                "sections": extracted["sections"],
                "full_text": extracted["full_text"]
            })

            # Combine for one big tutorial doc
            if extracted["full_text"]:
                combined_full_text_parts.append(f"[Source: {pu}]\n{extracted['full_text']}")
            if extracted["sections"]:
                # keep section structure but annotate where it came from
                for s in extracted["sections"]:
                    combined_sections.append({
                        "source_url": pu,
                        "heading": s["heading"],
                        "text": s["text"]
                    })

        # 3) Build final tutorial object
        obj = {
            "label_id": e["label_id"],     
            "title": e["title"],
            "url": e["url"],                # root entry URL from index
            "pages": pages_data,            # each page extracted separately
            "sections": combined_sections,  # combined sections across all pages
            "full_text": "\n\n".join(combined_full_text_parts).strip()
        }

        filename = f"{e['label_id']}_{slugify(e['title'])}.json"
        with open(os.path.join(PER_TUTORIAL_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)

        all_results.append(obj)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\nDone.")
    print(f"Tutorials extracted: {len(all_results)}")
    print(f"Per-tutorial JSON directory: {PER_TUTORIAL_DIR}/")
    print(f"Combined JSON file: {OUT_JSON}")

if __name__ == "__main__":
    main()
