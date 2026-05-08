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

# Primary URLs to scrape - main ambermd pages and tutorial pages
PRIMARY_URLS = [
    "https://ambermd.org/",
    "https://ambermd.org/tutorials/",
    "https://ambermd.org/AmberMD.php",
    "https://ambermd.org/AmberTools.php",
    "https://ambermd.org/GetAmber.php",
    "https://ambermd.org/Manuals.php",
    "https://ambermd.org/Tutorials/BuildingSystems.php",
    "https://ambermd.org/tutorials/CHARMM-GUI.php",
    "https://ambermd.org/tutorials/Introductory.php",
    "https://ambermd.org/tutorials/Overview.php",
    # Tutorial 3 sections - User's specific request
    "https://ambermd.org/tutorials/advanced/tutorial3/index.php",
    "https://ambermd.org/tutorials/advanced/tutorial3/py_script/section4.php",
    "https://ambermd.org/tutorials/advanced/tutorial3/py_script/section5.php",
    "https://ambermd.org/tutorials/advanced/tutorial3/py_script/section6.php",
]

OUTPUT_FOLDER = "scraped_ambermd_output"
OUTPUT_FILE = os.path.join(OUTPUT_FOLDER, "ambermd_tutorials.json")


def is_pdf_url(url):
    url_lower = url.lower()
    return url_lower.endswith(".pdf") or ".pdf" in urlparse(url).path


def fetch_text_from_html(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 404:
            raise FileNotFoundError(f"404 Not Found: {url}")
        r.raise_for_status()
        content_type = r.headers.get("Content-Type", "")
        if "text" not in content_type and "html" not in content_type:
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

    scraped = []
    visited = set()

    for url in PRIMARY_URLS:
        if url in visited:
            continue
        visited.add(url)

        if not url.startswith("http://") and not url.startswith("https://"):
            logging.warning(f"Skipping unsupported URL scheme: {url}")
            continue

        try:
            page_data = scrape_url(url)
            scraped.append(page_data)
            logging.info(f"✓ Scraped: {url}")

        except FileNotFoundError as e:
            logging.warning(f"✗ Skipped 404: {e}")
            continue

        except (requests.exceptions.RequestException, TimeoutError, ConnectionError) as e:
            logging.warning(f"✗ Skipping unreachable URL {url}: {e}")
            continue

        except Exception as e:
            logging.warning(f"✗ Skipping URL {url} due to error: {e}")
            continue

    # Save aggregated output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(scraped, f, indent=2, ensure_ascii=False)

    logging.info(f"\n✓ Saved {len(scraped)} scraped URLs to {OUTPUT_FILE}")
    logging.info(f"Total data size: {os.path.getsize(OUTPUT_FILE) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
