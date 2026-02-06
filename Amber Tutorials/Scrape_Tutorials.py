
import os
import re
import json
import time
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


# ============================================================
# CONFIGURATION
# ============================================================

# Main index page listing all Amber tutorials
INDEX_URL = "https://ambermd.org/tutorials/"

# We only allow links from this domain and path
BASE_DOMAIN = "ambermd.org"
ALLOWED_PREFIX = "/tutorials/"

# Output locations
OUT_DIR = "output"
PER_TUTORIAL_DIR = os.path.join(OUT_DIR, "tutorials")
OUT_JSON = os.path.join(OUT_DIR, "amber_tutorials.json")

# Networking / scraping controls
REQUEST_TIMEOUT = (10, 30)   # (connect timeout, read timeout)
DELAY = 0.3                  # polite delay between requests
MIN_TEXT_LEN = 20            # ignore extremely short fragments


# ============================================================
# HTTP SESSION
# ============================================================
# Use a persistent session with browser-like headers.
# This avoids 403 errors and makes requests appear non-bot-like.

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


# ============================================================
# URL HELPERS
# ============================================================

def normalize_url(base, href):
    """
    Convert relative URLs into absolute URLs and remove fragments.
    Example:
      "/tutorials/foo/index.php#section1"
      → "https://ambermd.org/tutorials/foo/index.php"
    """
    if not href:
        return None
    href = href.strip()
    if href.startswith(("mailto:", "javascript:")):
        return None

    absolute = urljoin(base, href)
    absolute, _ = urldefrag(absolute)
    return absolute


def is_allowed(url):
    """
    Ensure we only scrape:
    - HTTPS/HTTP links
    - ambermd.org
    - /tutorials/*
    - non-binary files (no PDFs, images, archives)
    """
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


# ============================================================
# FETCHING HTML
# ============================================================

def fetch_html(url):
    """
    Fetch a web page and return its HTML text.
    Any non-200 response is treated as failure.
    """
    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        if response.status_code != 200:
            print(f"[fetch_html] status={response.status_code} url={url}")
            return None
        return response.text

    except requests.RequestException as e:
        print(f"[fetch_html] ERROR {type(e).__name__}: {e}")
        return None


# ============================================================
# TEXT CLEANING HELPERS
# ============================================================

def slugify(text):
    """
    Convert a title into a filesystem-safe filename.
    """
    text = re.sub(r"[^\w\s.-]", "", text).strip()
    text = re.sub(r"\s+", "_", text)
    return text[:160] or "untitled"


def normalize_whitespace(text):
    """
    Normalize whitespace:
    - collapse excessive spaces
    - remove extra blank lines
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


# ============================================================
# INDEX PARSING (LABEL FIX)
# ============================================================

def parse_index_entries(index_html):
    """
    Parse the Amber tutorials index page.

    Extracts:
      - label_id (e.g. "1", "1.1", "7.10", "a")
      - title
      - URL

    This is the ONLY place where label_id exists.
    """
    soup = BeautifulSoup(index_html, "html.parser")
    entries = []
    seen_urls = set()

    # Match numbered labels: "7.10 Free Energies"
    num_label = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")

    # Match lettered sublabels: "a. Using PACKMOL..."
    letter_label = re.compile(r"^([a-zA-Z])\.\s+(.+)$")

    for a in soup.find_all("a", href=True):
        link_text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        url = normalize_url(INDEX_URL, a["href"])

        if not url or not is_allowed(url):
            continue
        if url.rstrip("/") == INDEX_URL.rstrip("/"):
            continue
        if url in seen_urls:
            continue

        match_num = num_label.match(link_text)
        match_letter = None if match_num else letter_label.match(link_text)

        if not match_num and not match_letter:
            continue

        seen_urls.add(url)

        if match_num:
            label_id, title = match_num.group(1), match_num.group(2)
        else:
            label_id, title = match_letter.group(1).lower(), match_letter.group(2)

        entries.append({
            "label_id": label_id.strip(),
            "title": title.strip(),
            "url": url
        })

    return entries


# ============================================================
# TUTORIAL PAGE EXTRACTION
# ============================================================

def extract_sections(html):
    """
    Extract structured instructional content from a tutorial page.

    Output:
      - page_title
      - sections: [{heading, text}]
      - full_text (flattened)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove navigation and non-content elements
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    main = soup.find("main") or soup.find(id="content") or soup.body
    if not main:
        return {"page_title": "", "sections": [], "full_text": ""}

    # Identify page title
    h1 = soup.find("h1") or main.find("h1") or main.find("h2")
    page_title = h1.get_text(" ", strip=True) if h1 else ""

    sections = []
    current_heading = "Introduction"
    buffer = []

    def flush():
        """
        Save the accumulated text under the current heading.
        """
        nonlocal buffer
        if buffer:
            sections.append({
                "heading": current_heading,
                "text": normalize_whitespace("\n".join(buffer))
            })
            buffer.clear()

    # Walk the page in reading order
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "pre", "li"]):
        if el.name in ("h1", "h2", "h3", "h4"):
            new_heading = el.get_text(" ", strip=True)
            if new_heading:
                flush()
                current_heading = new_heading
            continue

        text = (
            el.get_text("\n", strip=True)
            if el.name == "pre"
            else el.get_text(" ", strip=True)
        )
        text = normalize_whitespace(text)

        if text and len(text) >= MIN_TEXT_LEN:
            buffer.append(text)

    flush()

    full_text = normalize_whitespace(
        "\n\n".join(f"{s['heading']}\n{s['text']}" for s in sections)
    )

    return {
        "page_title": page_title,
        "sections": sections,
        "full_text": full_text
    }


# ============================================================
# MAIN PIPELINE
# ============================================================

def main():
    """
    End-to-end pipeline:
      index → tutorial pages → structured JSON
    """
    os.makedirs(PER_TUTORIAL_DIR, exist_ok=True)

    index_html = fetch_html(INDEX_URL)
    if not index_html:
        print("Failed to fetch tutorials index.")
        return

    entries = parse_index_entries(index_html)
    print(f"Found {len(entries)} tutorials with labels.")

    all_results = []

    for entry in tqdm(entries, desc="Extracting tutorials"):
        html = fetch_html(entry["url"])
        time.sleep(DELAY)
        if not html:
            continue

        extracted = extract_sections(html)

        tutorial_obj = {
            "label_id": entry["label_id"],
            "title": entry["title"],
            "url": entry["url"],
            "page_title": extracted["page_title"],
            "sections": extracted["sections"],
            "full_text": extracted["full_text"]
        }

        filename = f"{entry['label_id']}_{slugify(entry['title'])}.json"
        with open(os.path.join(PER_TUTORIAL_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(tutorial_obj, f, indent=2, ensure_ascii=False)

        all_results.append(tutorial_obj)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print("\nPipeline complete.")
    print(f"Tutorials extracted: {len(all_results)}")
    print(f"Per-tutorial JSON directory: {PER_TUTORIAL_DIR}/")
    print(f"Combined JSON file: {OUT_JSON}")


if __name__ == "__main__":
    main()
