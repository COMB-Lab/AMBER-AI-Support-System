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

MAX_PAGES_PER_TUTORIAL = 50   
CRAWL_SECTION_PAGES = True

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

def within_same_tutorial_tree(root_url, candidate_url):
    """
    True if candidate_url is anywhere under the same tutorial folder as root_url.
    Example:
      root: .../tutorial3/index.php
      ok:   .../tutorial3/section2.php
      ok:   .../tutorial3/py_script/section1.php
      no:   .../tutorial4/...
    """
    r = urlparse(root_url)
    c = urlparse(candidate_url)

    if r.netloc != c.netloc:
        return False

    tutorial_root = r.path.rsplit("/", 1)[0] + "/"   # .../tutorial3/
    return c.path.startswith(tutorial_root)

# -----------------------------
# Fetching
# -----------------------------
def fetch_html(url):
    """Fetch HTML and return (html_text_or_None, status_code_or_None)."""
    try:
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            print(f"[fetch_html] status={r.status_code} url={url}")
            return None, r.status_code
        return r.text, r.status_code
    except requests.RequestException as e:
        print(f"[fetch_html] ERROR {type(e).__name__}: {e}")
        return None, None

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

    num_label = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")   
    letter_label = re.compile(r"^([a-zA-Z])\.\s+(.+)$")   

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
def extract_sections_from_html(url, html):
    """
    Extract structured text from one HTML page:
      - page_title
      - sections: [{heading, text}]
      - full_text
      - external_resources: []
    """
    soup = BeautifulSoup(html, "html.parser")

    # remove common non-content
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    main = soup.find("main") or soup.find(id="content") or soup.body or soup
    if not main:
        return {"page_title": "", "sections": [], "full_text": "", "external_resources": []}

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

    return {"page_title": page_title, "sections": sections, "full_text": full_text, "external_resources": []}

# -----------------------------
# Crawl tutorial pages (BFS)
# -----------------------------
def crawl_tutorial_pages(root_url):
    """
    Crawl root page + any linked section pages under the same tutorial folder,
    including subfolders like py_script/.

    Also returns a list of missing pages (404, etc.) that were linked.
    """
    visited = set()
    pages = []
    missing = []

    q = deque([root_url])

    
    section_re = re.compile(r"(?:^|/)(section\d+(?:[._-]\d+)?)\.php$", re.IGNORECASE)

    while q and len(pages) < MAX_PAGES_PER_TUTORIAL:
        url = q.popleft()
        if url in visited:
            continue
        visited.add(url)

        html, status = fetch_html(url)
        time.sleep(DELAY)

        if status != 200 or not html:
            missing.append({"url": url, "status": status})
            continue

        pages.append(url)

        if not CRAWL_SECTION_PAGES:
            continue

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            u = normalize_url(url, a["href"])
            if not u or not is_allowed(u):
                continue
            if not within_same_tutorial_tree(root_url, u):
                continue

            # only follow section-like pages to keep crawl focused
            if section_re.search(urlparse(u).path):
                if u not in visited:
                    q.append(u)

    return pages, missing

# -----------------------------
# Main
# -----------------------------
def main():
    os.makedirs(PER_TUTORIAL_DIR, exist_ok=True)

    index_html, status = fetch_html(INDEX_URL)
    if not index_html:
        print("Failed to fetch tutorials index.")
        return

    entries = parse_index_entries(index_html)
    print(f"Found {len(entries)} tutorials with labels.")

    all_results = []

    for e in tqdm(entries, desc="Extracting tutorials"):
        page_urls, missing_pages = crawl_tutorial_pages(e["url"])
        if not page_urls:
            continue

        pages_data = []
        combined_full_text_parts = []
        combined_sections = []

        for pu in page_urls:
            html, status = fetch_html(pu)
            time.sleep(DELAY)
            if status != 200 or not html:
                # already tracked in crawl_tutorial_pages, but safe to keep
                continue

            extracted = extract_sections_from_html(pu, html)

            pages_data.append({
                "url": pu,
                "page_label_id": e["label_id"],
                "page_title": extracted["page_title"],
                "sections": extracted["sections"],
                "full_text": extracted["full_text"],
                "external_resources": extracted.get("external_resources", [])
            })

            if extracted["full_text"]:
                combined_full_text_parts.append(f"[Source: {pu}]\n{extracted['full_text']}")

            for s in extracted["sections"]:
                combined_sections.append({
                    "source_url": pu,
                    "page_label_id": e["label_id"],
                    "heading": s["heading"],
                    "text": s["text"]
                })

        obj = {
            "label_id": e["label_id"],
            "title": e["title"],
            "url": e["url"],
            "pages": pages_data,
            "sections": combined_sections,
            "full_text": "\n\n".join(combined_full_text_parts).strip(),
            "missing_pages": missing_pages
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
