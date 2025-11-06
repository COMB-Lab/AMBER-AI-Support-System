import os
import time
import json
import uuid
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import markdownify  # pip install markdownify

# ---------------- CONFIG ----------------
BASE_URL = "https://ambermd.org/tutorials/"
OUTPUT_DIR = "data_extraction_amber_tutorials"
DELAY_SECONDS = 1.5
TIMEOUT = 15

# Create output folder
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -------- helper functions --------
def get_soup(url):
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def canonicalize_url(base, link):
    return urljoin(base, link)

def html_to_markdown(html_fragment):
    md = markdownify.markdownify(html_fragment, heading_style="ATX")
    return md.strip()

# -------- extract a single tutorial page --------
def extract_tutorial_page(url):
    soup = get_soup(url)

    # Remove header/footer/sidebars if present
    for sel in ["header", "nav", "footer", ".sidebar", ".breadcrumbs"]:
        for node in soup.select(sel):
            node.decompose()

    # Title
    title_tag = soup.find(["h1", "title"])
    title = title_tag.get_text(strip=True) if title_tag else "Untitled Tutorial"

    # Main content
    content = soup.find("main") or soup.find("article") or soup.body

    # Images
    images = []
    for img in content.find_all("img"):
        src = img.get("src")
        if src:
            images.append(canonicalize_url(url, src))

    # Markdown conversion
    md = html_to_markdown(str(content))

    # Final tutorial dict
    tutorial = {
        "title": title,
        "markdown": md,
        "images": images,
        "url": url
    }
    return tutorial

# -------- recursive crawl --------
visited_urls = set()

def crawl_tutorial(url, base_domain):
    if url in visited_urls:
        return
    visited_urls.add(url)

    print(f"Fetching: {url}")
    try:
        tutorial = extract_tutorial_page(url)
        file_id = uuid.uuid4().hex[:8]
        filename = f"{file_id}.json"
        with open(os.path.join(OUTPUT_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(tutorial, f, indent=2, ensure_ascii=False)
        print(f"Saved: {filename}")
    except Exception as e:
        print("Error fetching", url, e)
        return

    # Find internal tutorial links
    try:
        soup = get_soup(url)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full_url = canonicalize_url(url, href)
            if full_url.startswith(base_domain) and full_url not in visited_urls and "tutorial" in full_url:
                crawl_tutorial(full_url, base_domain)
                time.sleep(DELAY_SECONDS)
    except Exception as e:
        print("Error finding links on", url, e)

# -------- main --------
if __name__ == "__main__":
    crawl_tutorial(BASE_URL, BASE_URL)
