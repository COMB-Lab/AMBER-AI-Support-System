import os
import re
import json
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from tqdm import tqdm

# --- CONFIG ---
BASE_DIR = Path(__file__).resolve().parent

OUT_DIR = BASE_DIR / "amber_tutorials_output"
PER_TUTORIAL_DIR = OUT_DIR / "jsons_html"
INDEX_URL = "https://ambermd.org/tutorials/"


def clean_html_fragment(tag):

    # Remove unwanted tags inside the specific fragment
    for trash in tag.select("script, style, noscript, .hnav, .vnav"):
        trash.decompose()

    # Get string and strip extra whitespace
    text = str(tag).strip()
    return text


def fetch_soup(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            content_type = r.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type:
                return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def get_tutorial_index_data(index_soup):

    entries = []
    seen_urls = set()

    # Get "1.1" or '1.2'
    label_regex = re.compile(r"^(\d+(?:\.\d+)*|[a-zA-Z](?:\.\d+)?)\.?\s+")

    for a in index_soup.find_all("a", href=True):
        url = urljoin(INDEX_URL, a["href"])
        text = a.get_text(strip=True)

        is_tutorial_class = "tutorial" in a.get("class", [])
        match = label_regex.match(text)

        if (is_tutorial_class or match) and url not in seen_urls:
            if "ambermd.org" in url and not url.endswith(('.pdf', '.zip', '.tar.gz')):
                # Extract ID if present (e.g., "1.1")
                pid = match.group(1) if match else "N/A"

                # Clean title
                clean_title = label_regex.sub("", text)

                entries.append({
                    "url": url,
                    "id": pid,
                    "title": clean_title
                })
                seen_urls.add(url)
    return entries


def find_sub_pages(base_url, soup):

    sub_pages = []
    base_dir = base_url.rsplit('/', 1)[0]
    if not base_dir.endswith('/'): base_dir += '/'

    skip_exts = ('.pdf', '.zip', '.tar.gz', '.tgz', '.gz', '.in', '.out',
                 '.rst', '.prmtop', '.pdb', '.png', '.jpg', '.gif')

    for a in soup.find_all("a", href=True):
        href = a['href']
        if href.startswith('#') or href.startswith('mailto:'): continue

        full_url = urljoin(base_url, href)
        # remove fragments
        full_url = urlparse(full_url)._replace(fragment="").geturl()

        # Check if valid sub-page
        if full_url.startswith(base_dir) and full_url != base_url:
            if not full_url.lower().endswith(skip_exts):
                # Avoid duplicates
                if full_url not in sub_pages:
                    sub_pages.append(full_url)
    return sub_pages


def parse_sections(soup, page_title):

    # Locate the main content area (AmberMD specific layout)
    content = (soup.find("td", style=re.compile(r"width:760px")) or
               soup.find("div", class_="content") or
               soup.find("div", {"id": "content"}) or
               soup.body)

    if not content:
        return []

    # Pre-clean global navigation elements
    for tag in content.select("nav, header, footer, .tutorial_toc, script, style"):
        tag.decompose()

    sections = []

    # Buffer for current section
    current_heading = page_title if page_title else "Introduction"
    current_html_buffer = []

    # Iterate over direct children to group by header

    for element in content.children:
        if isinstance(element, NavigableString):
            text = str(element).strip()
            if text:
                current_html_buffer.append(text)
            continue

        if isinstance(element, Tag):
            # Check if this tag is a Header
            is_header = element.name in ['h1', 'h2', 'h3', 'h4']

            if is_header:
                # Save previous section
                if current_html_buffer:
                    sections.append({
                        "heading": current_heading,
                        "text": "\n".join(current_html_buffer)
                    })

                # Start new section
                current_heading = element.get_text(strip=True)
                current_html_buffer = []
            else:
                # It's content
                html_snippet = clean_html_fragment(element)
                if html_snippet:
                    current_html_buffer.append(html_snippet)

    # Append the final buffer
    if current_html_buffer:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_html_buffer)
        })

    # Fallback: If no sections detected (e.g. strict table layout), dump everything
    if not sections and content.get_text(strip=True):
        sections.append({
            "heading": "Main Content",
            "text": clean_html_fragment(content)
        })

    return sections

def combine_all_tutorials():

    combined_data = []

    master = "0_master_amber_combined.json"
    master_path = PER_TUTORIAL_DIR / master

    # Get all .json files in the directory
    json_files = list(PER_TUTORIAL_DIR.glob("*.json"))

    # Remove the master json if it exists
    json_files = [f for f in json_files if f.name != master]

    # read
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                combined_data.append(data)
        except Exception as e:
            print(f"Error reading {json_file}: {e}")

    # write
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(combined_data, f, indent=2, ensure_ascii=False)

    print(f"Master JSON created at: {master_path}")


# --- MAIN LOGIC ---

def main():
    PER_TUTORIAL_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching Index...")
    index_soup = fetch_soup(INDEX_URL)
    if not index_soup: return

    tutorials_list = get_tutorial_index_data(index_soup)
    print(f"Found {len(tutorials_list)} tutorials.")

    for item in tqdm(tutorials_list):
        # Generate UUID
        tutorial_data = {
            "id": str(uuid.uuid4()),  # Crucial UUID added here
            "tutorial_label": item['id'],
            "tutorial_title": item['title'],
            "pages": []
        }

        # Queue for crawling pages within this specific tutorial
        queue = [(item['url'], item['id'], item['title'])]
        visited = set()

        while queue:
            curr_url, curr_id, curr_title = queue.pop(0)

            clean_url = curr_url.split('#')[0]
            if clean_url in visited:
                continue
            visited.add(clean_url)

            soup = fetch_soup(curr_url)
            if not soup: continue

            # Determine the best title for the page
            actual_page_title = curr_title
            if soup.title and soup.title.string:
                actual_page_title = soup.title.string.strip()
            elif soup.find('h1'):  # Fallback to the first H1 tag
                actual_page_title = soup.find('h1').get_text(strip=True)


            page_sections = parse_sections(soup, actual_page_title)

            # Generate UUID for this page
            tutorial_data["pages"].append({
                "id": str(uuid.uuid4()),
                "url": curr_url,
                "page_label_id": curr_id,
                "page_title": actual_page_title,
                "sections": page_sections
            })

            sub_links = find_sub_pages(curr_url, soup)
            for link in sub_links:
                if link not in visited:
                    queue.append((link, curr_id, "Sub-page"))

        # Sanitize filename (handling the "N/A" slash issue)
        safe_id = re.sub(r'[^\w\-]', '_', str(item['id']))
        safe_title = re.sub(r'[^\w\-]', '_', item['title'])[:50]

        if not safe_title:
            safe_title = "tutorial"

        out_file = PER_TUTORIAL_DIR / f"{safe_id}_{safe_title}.json"

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(tutorial_data, f, indent=2, ensure_ascii=False)

    combine_all_tutorials()

if __name__ == "__main__":
    main()