import os
import re
import json
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import markdownify
from bs4 import BeautifulSoup
from tqdm import tqdm

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent

OUT_DIR = BASE_DIR / "amber_tutorials_output"
PER_TUTORIAL_DIR = OUT_DIR / "jsons_markdown"
INDEX_URL = "https://ambermd.org/tutorials/"


def fetch_soup(url):
    try:
        # Using a browser-like header to avoid blocks
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)

        if r.status_code == 200:
            # Check if the page is actually a web page
            content_type = r.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type:
                return BeautifulSoup(r.text, "lxml")
            else:
                # skip raw files
                return None

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
    content = (soup.find("td", style=re.compile(r"width:760px")) or
               soup.find("div", class_="content") or
               soup.find("div", {"id": "content"}) or
               soup.body)

    if not content: return ""

    # Remove clutter
    for tag in content.select("nav, header, footer, .hnav, .vnav, .tutorial_toc, script, style"):
        tag.decompose()

    return markdownify.markdownify(str(content), heading_style="ATX").strip()


def find_sections(tutorial_base_url, soup):
    sections = []

    # Normalize base dir
    base_dir = tutorial_base_url.rsplit('/', 1)[0]
    if not base_dir.endswith('/'):
        base_dir += '/'

    skip_exts = ('.pdf', '.zip', '.tar.gz', '.tgz', '.gz',
                 '.in', '.out', '.rst', '.rst7', '.ncrst', '.nc',
                 '.prmtop', '.inpcrd', '.crd', '.mdcrd', '.top',
                 '.pdb', '.txt', '.png', '.jpg', '.jpeg', '.gif',
                 '.mol2', '.frcmod', '.lib', '.log', '.mdinfo', '.cpptraj')

    for a in soup.find_all("a", href=True):
        href = a['href']
        if href.startswith('#'):
            continue

        full_url = urljoin(tutorial_base_url, href)
        full_url = urlparse(full_url)._replace(fragment="").geturl()

        # Prevent double scrape
        full_url = full_url.replace("index.php", "").replace("index.html", "")
        normalized_base = tutorial_base_url.replace("index.php", "").replace("index.html", "")

        # Capture if within same directory structure
        if full_url.startswith(base_dir) and full_url != normalized_base:
            if not full_url.lower().endswith(skip_exts):
                if full_url not in sections:
                    sections.append(full_url)

    return sections


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

        # Deep Crawl / find sub sections
        visited = {url}
        queue = find_sections(url, soup)

        while queue:
            s_url = queue.pop(0)
            if s_url in visited:
                continue

            visited.add(s_url)
            s_soup = fetch_soup(s_url)
            if s_soup:
                s_md = extract_clean_markdown(s_soup)
                all_md.append(f"\n\n---\n### Section: {s_url}\n---\n\n{s_md}")

                # look for extra content
                new_links = find_sections(url, s_soup)
                for link in new_links:
                    if link not in visited and link not in queue:
                        queue.append(link)

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


if __name__ == "__main__":
    main()