import os
import time
import json
import uuid
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import markdownify


BASE_URL = "https://ambermd.org/tutorials/"
OUTPUT_DIR = "data_extraction_amber_tutorials"
DELAY_SECONDS = 1.5
TIMEOUT = 15
USER_AGENT = ""

# Create output folder
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -------- helper functions --------
def get_soup(url):
    """Fetches and parses a webpage into BeautifulSoup."""
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def canonicalize_url(base, link):
    """Converts relative links to absolute URLs."""
    return urljoin(base, link)

def html_to_markdown(html_fragment):
    """Converts HTML to Markdown for clean text extraction."""
    return markdownify.markdownify(html_fragment, heading_style="ATX").strip()

# -------- extract a single tutorial page --------
def extract_tutorial_page(url):
    """Extracts and cleans a single Amber tutorial page."""
    soup = get_soup(url)

    # Remove navigation and irrelevant elements
    for sel in ["header", "nav", "footer", ".sidebar", ".breadcrumbs"]:
        for node in soup.select(sel):
            node.decompose()

    # Extract title
    title_tag = soup.find(["h1", "title"])
    title = title_tag.get_text(strip=True) if title_tag else "Untitled Tutorial"

    # Extract main content area
    content = soup.find("main") or soup.find("article") or soup.body
    if content is None:
        raise ValueError("No main content found")

    # Extract images
    images = []
    for img in content.find_all("img"):
        src = img.get("src")
        if src:
            images.append(canonicalize_url(url, src))

    # Convert to Markdown
    md = html_to_markdown(str(content))

    # Return structured tutorial data
    return {
        "title": title,
        "markdown": md,
        "images": images,
        "url": url
    }

# -------- recursive crawl --------
visited_urls = set()

def crawl_tutorial(url, base_domain):
    """Recursively crawls all tutorial pages starting from base URL."""
    if url in visited_urls:
        return
    visited_urls.add(url)

    # Skip non-HTML files
    skip_ext = (".pdf", ".ipynb", ".zip", ".tar.gz", ".tgz")
    if url.lower().endswith(skip_ext):
        print(f" Skipping non-HTML file: {url}")
        return

    print(f" Fetching: {url}")
    try:
        # Extract and save tutorial page
        tutorial = extract_tutorial_page(url)
        file_id = uuid.uuid4().hex[:8]
        filename = f"{file_id}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(tutorial, f, indent=2, ensure_ascii=False)
        print(f" Saved: {filename}")
    except Exception as e:
        print(f" Error fetching {url}: {e}")
        return

    # Crawl internal tutorial links
    try:
        soup = get_soup(url)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = canonicalize_url(url, href)
            
            if full_url.startswith(base_domain) and full_url not in visited_urls:
                time.sleep(DELAY_SECONDS)
                crawl_tutorial(full_url, base_domain)
    except Exception as e:
        print(f" Error finding links on {url}: {e}")

# -------- main --------
if __name__ == "__main__":
    print(" Starting Amber tutorial extraction...")
    crawl_tutorial(BASE_URL, BASE_URL)
    print(f"\n Extraction complete! Data saved in: {OUTPUT_DIR}/")
