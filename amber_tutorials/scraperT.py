import os
import re
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import markdownify
from bs4 import BeautifulSoup
from tqdm import tqdm

# --- CONFIG ---
INDEX_URL = "https://ambermd.org/tutorials/"
OUT_DIR = Path("amber_tutorials_output")
PER_TUTORIAL_DIR = OUT_DIR / "jsons"
DELAY = 0.4


def fetch_soup(url):
    try:
        # Using a browser-like header to avoid blocks
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def get_tutorial_links(index_soup):
    """Finds tutorials based on the structure in the provided HTML."""
    entries = []
    seen_urls = set()

    # This regex matches "1.1 ", "7.10 ", "a. ", etc.
    label_regex = re.compile(r"^(\d+(\.\d+)*|[a-zA-Z])\.\s+")

    for a in index_soup.find_all("a", href=True):
        url = urljoin(INDEX_URL, a["href"])
        text = a.get_text(strip=True)

        # Logic: It's a tutorial if it has class 'tutorial' OR matches the numbering pattern
        is_tutorial_class = "tutorial" in a.get("class", [])
        has_label_prefix = bool(label_regex.match(text))

        # Filter out navigation and parent index links
        if (is_tutorial_class or has_label_prefix) and url not in seen_urls:
            if "ambermd.org" in url and not url.endswith(('.pdf', '.zip', '.tar.gz')):
                entries.append({"url": url, "title": text})
                seen_urls.add(url)

    return entries


def extract_clean_markdown(soup):
    """Refined extraction for AmberMD's table-based layout."""
    # Target the specific content cell seen in the HTML
    content = soup.find("td", style=re.compile(r"width:760px")) or soup.find("div", {"id": "content"}) or soup.body

    if not content: return ""

    # Remove clutter
    for tag in content.select("nav, header, footer, .hnav, .vnav, .tutorial_toc, script, style"):
        tag.decompose()

    return markdownify.markdownify(str(content), heading_style="ATX").strip()


def find_sections(base_url, soup):
    """Look for section1.php, section2.php links in the same directory."""
    sections = []
    base_dir = base_url.rsplit('/', 1)[0]

    for a in soup.find_all("a", href=True):
        full_url = urljoin(base_url, a['href'])
        if base_dir in full_url and "section" in full_url.lower():
            if full_url not in sections and full_url != base_url:
                sections.append(full_url)

    # Sort numerically (section1, section2...)
    return sorted(sections, key=lambda x: int(re.findall(r'\d+', x)[-1]) if re.findall(r'\d+', x) else 0)


def main():
    PER_TUTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    index_soup = fetch_soup(INDEX_URL)
    if not index_soup: return

    tutorials = get_tutorial_links(index_soup)
    print(f"Found {len(tutorials)} tutorials.")

    for item in tqdm(tutorials):
        url = item['url']
        soup = fetch_soup(url)
        if not soup: continue

        # Start building the tutorial data
        main_md = extract_clean_markdown(soup)
        all_md = [f"# {item['title']}\nSource: {url}\n\n{main_md}"]

        # Deep Crawl: Find sub-sections
        section_urls = find_sections(url, soup)
        for s_url in section_urls:
            s_soup = fetch_soup(s_url)
            if s_soup:
                s_md = extract_clean_markdown(s_soup)
                all_md.append(f"\n\n---\n### Section: {s_url}\n---\n\n{s_md}")
                time.sleep(DELAY)

        # Save result
        safe_title = re.sub(r'[^\w\-]', '_', item['title'])[:50]
        result = {
            "id": str(uuid.uuid4()),
            "title": item['title'],
            "url": url,
            "full_markdown": "\n".join(all_md)
        }

        with open(PER_TUTORIAL_DIR / f"{safe_title}.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        time.sleep(DELAY)


if __name__ == "__main__":
    main()