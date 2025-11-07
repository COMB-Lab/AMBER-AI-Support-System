from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import markdownify


BASE_URL = "https://ambermd.org"
INDEX_URL = f"{BASE_URL}/tutorials/"
OUTPUT_DIR = Path("amber_tutorials/amber_tutorials_output/")
USER_AGENT = "scraper/1.1"
REQUEST_DELAY_SECONDS = 0.5
REQUEST_TIMEOUT = 20

# Scrapes HTML TXT content
def scraping_html(url: str) -> Optional[str]:
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print("Error!")
        return None

# Parses the tutorial index HTML to find all unique and valid tutorial links.
def parse_index_links(html: str) -> List[str]:
    # Change to soup object
    soup = BeautifulSoup(html, "lxml")
    # We will use a set instead of a list since duplicates are automatically handled
    links: Set[str] = set()

    # for each link, loop
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        # See if this is a valid tutorial
        if 'tutorial' in href.lower() or href.startswith('basic/') or href.startswith('advanced/'):
            full_url = urljoin(INDEX_URL, href)
            parsed = urlparse(full_url)

            # Check if we are still in the AMBER website
            if "ambermd.org" in parsed.netloc:
                normalized_url = parsed.scheme + "://" + parsed.netloc + parsed.path
                links.add(normalized_url)
    return sorted(list(links))


# Scrapes the content from the html into readable material
def extract_and_clean_content(html: str, url: str) -> Dict:
    soup = BeautifulSoup(html, "lxml")
    # Find Title
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else "Untitled Tutorial"

    # Find Main content or as a failsafe just grab everything
    main_content = soup.find("td", style=re.compile(r"width:760px")) or soup.body

    # In a weird case that there is no main content
    if not main_content:
        return {"title": title, "markdown_content": "", "url": url}

    # Remove these elements
    for tag_or_selector in ["header", "nav", "footer", ".hnav", ".vnav", ".tutorial_toc"]:
        for element in main_content.select(tag_or_selector):
            # Delete element
            element.decompose()

    # change back to html
    markdown_content = markdownify.markdownify(str(main_content), heading_style="ATX").strip()

    return {"title": title, "markdown_content": markdown_content, "url": url}

# Had issues with file names so I used slug to make sure that there are no "illegal" file names
def create_title_slug(title: str) -> str:
    # Remove any character that is a "/" or ":" and not a letter, number, or space
    slug = re.sub(r'[:/]', ' ', title)
    slug = re.sub(r'[^A-Za-z0-9 ]+', '', slug)

    # Convert to lowercase, split by spaces, and join with underscores
    slug = "_".join(slug.lower().split())
    return slug

#save file
def save_tutorial_as_json(data: Dict):
    if not data or not data.get("markdown_content"):
        print("No content to save.")
        return

    # Create a descriptive filename from the tutorial's title
    slug = create_title_slug(data["title"])
    filename = f"{slug}.json"
    filepath = OUTPUT_DIR / filename

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Successfully saved content to {filepath}")
    except IOError as e:
        print(f"Error saving file {filepath}: {e}")

# Main function for testing
def main(limit: Optional[int] = None):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Starting AmberMD tutorial scraper.")
    print(f"Output will be saved in: {OUTPUT_DIR.resolve()}\n")

    index_html = scraping_html(INDEX_URL)

    links = parse_index_links(index_html)
    print(f"Found {len(links)} unique tutorial links to process.\n")

    processed_count = 0
    for url in links:
        if limit and processed_count >= limit:
            print(f"Reached processing limit of {limit}. Stopping.")
            break

        print(f"Processing ({processed_count + 1}/{len(links)}): {url}")

        tutorial_html = scraping_html(url)
        if not tutorial_html:
            print(f"Failed to scrape content.")
            continue

        scraped_data = extract_and_clean_content(tutorial_html, url)

        save_tutorial_as_json(scraped_data)

        processed_count += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nScraping complete. Processed {processed_count} tutorials.")

# Limit amount to test
if __name__ == "__main__":
    main(limit=10)