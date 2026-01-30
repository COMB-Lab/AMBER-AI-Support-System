# extract_amber_tutorials_fixed.py
#
# PURPOSE
# -------
# This script scrapes the official Amber tutorials from:
#   https://ambermd.org/tutorials/
#
# It performs the following pipeline:
#   1. Discover tutorial links from the index page
#   2. Filter out non-tutorial navigation links
#   3. Download each tutorial page
#   4. Extract only instructional content (no menus, scripts, headers)
#   5. Organize the content into structured sections
#   6. Save results as JSON (one file per tutorial + one combined file)
#


import os             
import re              
import json            
import time           
from urllib.parse import urljoin, urlparse, urldefrag  # URL normalization

# ============================================================
# Third-party libraries
# ============================================================

import requests        # HTTP requests
from bs4 import BeautifulSoup  # HTML parsing
from tqdm import tqdm  # Progress bar (visual feedback)

# ============================================================
# Configuration / Constants
# ============================================================

# Main tutorials index page
INDEX_URL = "https://ambermd.org/tutorials/"

# Restrict crawling to Amber domain only
BASE_DOMAIN = "ambermd.org"

# Only allow URLs under /tutorials/
ALLOWED_PREFIX = "/tutorials/"

# Output locations
OUT_DIR = "output"
PER_TUTORIAL_DIR = os.path.join(OUT_DIR, "tutorials")
OUT_JSON = os.path.join(OUT_DIR, "amber_tutorials.json")


REQUEST_TIMEOUT = (5, 20)  
DELAY = 0.15               


MIN_TEXT_LEN = 20

# ============================================================
# HTTP session (reuse connections + identify ourselves)
# ============================================================

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "amber-tutorial-extractor/1.1 (academic research)"
})

# ============================================================
# URL utilities
# ============================================================

def normalize_url(base, href):
    """
    Convert relative URLs to absolute URLs and remove fragments (#...).

    Returns None for:
    - empty links
    - mailto / javascript links
    """
    if not href:
        return None

    href = href.strip()
    if href.startswith(("mailto:", "javascript:")):
        return None

    # Make absolute URL
    url = urljoin(base, href)

    # Remove fragment (#section)
    url, _ = urldefrag(url)
    return url


def is_allowed(url):
    """
    Decide whether a URL is safe and relevant to crawl.

    Rules:
    - Must be http or https
    - Must be on ambermd.org
    - Must be under /tutorials/
    - Must NOT be a binary asset (pdf, image, zip, etc)
    """
    p = urlparse(url)

    if p.scheme not in ("http", "https"):
        return False

    if p.netloc != BASE_DOMAIN:
        return False

    if not p.path.startswith(ALLOWED_PREFIX):
        return False

    # Skip non-HTML files
    if p.path.lower().endswith((
        ".pdf", ".zip", ".tar", ".gz",
        ".png", ".jpg", ".jpeg", ".gif", ".svg"
    )):
        return False

    return True

# ============================================================
# Networking
# ============================================================

def fetch_html(url):
    """
    Download HTML content from a URL.

    Returns:
    - HTML text if successful
    - None if request fails or returns non-200 status
    """
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            return None
        return response.text
    except requests.RequestException:
        return None

# ============================================================
# Filename helper
# ============================================================

def slugify(text):
    """
    Convert a title into a filesystem-safe filename.
    """
    text = re.sub(r"[^\w\s.-]", "", text).strip()
    text = re.sub(r"\s+", "_", text)
    return (text[:160] or "untitled")

# ============================================================
# Step 1: Parse tutorial index
# ============================================================

def parse_index_entries(index_html):
    """
    Extract only REAL tutorial links from the tutorials index page.

    Keeps entries like:
      - "1 Building Systems"
      - "1.1 Preparing Structure"
      - "7.10 Grid Inhomogeneous Solvation Theory"
      - "a. Using PACKMOL-Memgen"

    Skips:
      - navigation links
      - overview pages
      - duplicate links
      - index page itself
    """
    soup = BeautifulSoup(index_html, "html.parser")

    entries = []
    seen_urls = set()

    # Numeric labels: 1, 1.1, 7.10, etc
    num_label_re = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")

    # Letter labels: a., b., c., etc
    letter_label_re = re.compile(r"^([a-zA-Z])\.\s+(.+)$")

    for a in soup.find_all("a", href=True):
        link_text = a.get_text(" ", strip=True)
        url = normalize_url(INDEX_URL, a["href"])

        if not url or not is_allowed(url):
            continue

        # Skip index page itself
        if url.rstrip("/") == INDEX_URL.rstrip("/"):
            continue

        # Keep only labeled tutorial entries
        m = num_label_re.match(link_text)
        m2 = None if m else letter_label_re.match(link_text)

        if not m and not m2:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        if m:
            label, title = m.group(1), m.group(2).strip()
        else:
            label, title = m2.group(1).lower(), m2.group(2).strip()

        entries.append({
            "label": label,
            "title": title,
            "url": url
        })

    return entries

# ============================================================
# remove duplicate lines
# ============================================================

def dedupe_lines(text):
    """
    Remove repeated identical lines.
    Useful for pages that repeat blocks of text.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    output = []
    seen = set()

    for ln in lines:
        if not ln.strip():
            output.append("")
            continue

        if ln in seen:
            continue

        seen.add(ln)
        output.append(ln)

    cleaned = "\n".join(output)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

# ============================================================
# Step 2: Extract tutorial content
# ============================================================

def extract_sections(html):
    """
    Extract structured instructional content from a tutorial page.

    Output:
    {
      page_title: str,
      sections: [{heading, text}],
      full_text: str
    }
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove obvious non-content elements
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    # Identify main content area
    main = soup.find("main") or soup.find(id="content") or soup.body or soup

    # Extract page title
    h1 = soup.find("h1") or main.find("h1") or main.find("h2")
    page_title = h1.get_text(" ", strip=True) if h1 else ""

    sections = []
    current_heading = "Introduction"
    buffer = []

    def flush():
        """Save accumulated text as a section."""
        nonlocal buffer, current_heading
        if buffer:
            sections.append({
                "heading": current_heading,
                "text": "\n".join(buffer).strip()
            })
            buffer = []

    # Walk through content in reading order
    for el in main.find_all(["h1", "h2", "h3", "p", "pre", "li"]):

        # Headings define section boundaries
        if el.name in ("h1", "h2", "h3"):
            heading_text = el.get_text(" ", strip=True)
            if heading_text:
                flush()
                current_heading = heading_text
            continue

        # Paragraph / list / code block text
        text = el.get_text("\n", strip=True)
        if text and len(text) >= MIN_TEXT_LEN:
            buffer.append(text)

    flush()

    # Combine sections into a single text block
    full_text = "\n\n".join(
        s["heading"] + "\n" + s["text"] for s in sections
    )

    full_text = dedupe_lines(full_text)

    return {
        "page_title": page_title,
        "sections": sections,
        "full_text": full_text
    }

# ============================================================
# Main pipeline
# ============================================================

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PER_TUTORIAL_DIR, exist_ok=True)

    index_html = fetch_html(INDEX_URL)
    if not index_html:
        print("Failed to fetch tutorial index.")
        return

    entries = parse_index_entries(index_html)
    print(f"Found {len(entries)} tutorial entries (filtered).")

    results = []

    for entry in tqdm(entries, desc="Extracting tutorials"):
        html = fetch_html(entry["url"])
        time.sleep(DELAY)

        if not html:
            continue

        extracted = extract_sections(html)

        obj = {
            "label": entry["label"],
            "title": entry["title"],
            "url": entry["url"],
            "page_title": extracted["page_title"],
            "sections": extracted["sections"],
            "full_text": extracted["full_text"]
        }

        # Save per-tutorial JSON
        filename = f"{entry['label']}_{slugify(entry['title'])}.json"
        with open(os.path.join(PER_TUTORIAL_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)

        results.append(obj)

    # Save combined dataset
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\nDone.")
    print(f"Tutorial pages extracted: {len(results)}")
    print(f"Per-tutorial JSON files: {PER_TUTORIAL_DIR}/")
    print(f"Combined JSON file: {OUT_JSON}")

# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
