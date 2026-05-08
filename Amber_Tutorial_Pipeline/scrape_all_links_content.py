import json
import os
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scraper.pdf_scraper import download_pdf
from processing.pdf_extractor import extract_pdf_text
from processing.chunker import chunk_text


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

INPUT_FILE = "all_scraped_links.json"
OUTPUT_FOLDER = "scraped_all_links_output"
OUTPUT_FILE = os.path.join(OUTPUT_FOLDER, "all_links_tutorials.json")

# Additional tutorial3 pages required by user request
MANDATORY_URLS = [
    "https://ambermd.org/tutorials/advanced/tutorial3/index.php",
    "https://ambermd.org/tutorials/advanced/tutorial3/py_script/section4.php",
    "https://ambermd.org/tutorials/advanced/tutorial3/py_script/section5.php",
    "https://ambermd.org/tutorials/advanced/tutorial3/py_script/section6.php",
]


def is_pdf_url(url):
    url_lower = url.lower()
    return url_lower.endswith(".pdf") or ".pdf" in urlparse(url).path


def should_skip_url(url):
    """Skip URLs that are not web pages or PDFs"""
    url_lower = url.lower()
    # Skip data files, scripts, and other non-page content
    skip_extensions = ['.nc', '.out', '.ncrst', '.in', '.inpcrd', '.pdb', '.txt', 
                      '.tar', '.gz', '.zip', '.exe', '.sh', '.py', '.f', '.sh', 
                      '.c', '.cpp', '.f90', '.h', '.o', '.a', '.so', '.lib']
    for ext in skip_extensions:
        if url_lower.endswith(ext):
            return True
    return False


def normalize_url(url):
    # Basic normalization to avoid close duplicates (remove fragments/trailing slash normalization)
    parsed = urlparse(url.strip())
    if not parsed.scheme:
        return url
    path = parsed.path.rstrip("/")
    if path == "":
        path = "/"
    normalized = parsed._replace(path=path, fragment="", params="", query="").geturl()
    return normalized


def fetch_text_from_html(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 404:
            raise FileNotFoundError(f"404 Not Found: {url}")
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "text" not in content_type and "html" not in content_type:
            # In case of unexpected non-html content, fallback to raw text.
            return r.text
        soup = BeautifulSoup(r.content, "html.parser")
        return soup.get_text(separator="\n", strip=True)
    except requests.exceptions.Timeout:
        raise TimeoutError(f"Timeout fetching {url}")
    except requests.exceptions.ConnectionError:
        raise ConnectionError(f"Connection error fetching {url}")


def scrape_url(url):
    if is_pdf_url(url):
        logging.info(f"Processing PDF: {url}")
        try:
            pdf_path = download_pdf(url)
            raw_text = extract_pdf_text(pdf_path)
            source_type = "pdf"
        except Exception as e:
            raise RuntimeError(f"Error reading PDF {url}: {e}")
    else:
        logging.info(f"Processing HTML: {url}")
        raw_text = fetch_text_from_html(url)
        source_type = "html"

    chunks = chunk_text(raw_text or "")
    return {
        "url": url,
        "source_type": source_type,
        "raw_text": raw_text,
        "chunks": [{"id": f"chunk_{i}", "text": c} for i, c in enumerate(chunks)],
    }


def main():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    if not os.path.exists(INPUT_FILE):
        logging.error(f"Input file not found: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    urls = set()

    # all_scraped_links.json has key -> [links] mapping
    # Filter for only ambermd links
    for source_url, linked_urls in data.items():
        if "ambermd" in source_url.lower():
            urls.add(normalize_url(source_url))
        for linked_url in linked_urls:
            if "ambermd" in linked_url.lower():
                urls.add(normalize_url(linked_url))

    # Add mandatory tutorial3 pages (ensure these are always included)
    for required in MANDATORY_URLS:
        urls.add(normalize_url(required))

    scraped = []
    visited = set()

    for url in sorted(urls):
        if url in visited:
            continue
        visited.add(url)

        # Skip URLs that are not web pages or PDFs
        if should_skip_url(url):
            logging.debug(f"Skipping non-page URL: {url}")
            continue

        # Some urls in all_scraped_links can be non-HTTP/unsupported, skip them.
        if not url.startswith("http://") and not url.startswith("https://"):
            logging.warning(f"Skipping unsupported URL scheme: {url}")
            continue

        try:
            page_data = scrape_url(url)
            scraped.append(page_data)
            logging.info(f"Scraped: {url}")

        except FileNotFoundError as e:
            logging.warning(f"Skipped 404: {e}")
            continue

        except (requests.exceptions.RequestException, TimeoutError, ConnectionError) as e:
            logging.warning(f"Skipping unreachable URL {url}: {e}")
            continue

        except Exception as e:
            logging.warning(f"Skipping URL {url} due to error: {e}")
            continue

    # Save aggregated output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(scraped, f, indent=2, ensure_ascii=False)

    logging.info(f"Saved scraped data to {OUTPUT_FILE}")
    logging.info(f"Total URLs scraped: {len(scraped)}")


if __name__ == "__main__":
    main()
