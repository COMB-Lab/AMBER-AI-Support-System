import requests
from bs4 import BeautifulSoup
import os
import json

from scraper.amber_crawler import extract_links
from scraper.pdf_scraper import download_pdf
from processing.pdf_extractor import extract_pdf_text
from processing.chunker import chunk_text
from storage.chroma_store import store_chunks


BASE_URL = "https://ambermd.org/tutorials/"

# Folder to store scraped JSON for all tutorials
OUTPUT_FOLDER = "scraped_all_tutorials_output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def run_pipeline():

    print("Starting Amber tutorial scrape")

    links = extract_links(BASE_URL)
    all_tutorials = []

    for item in links:

        url = dict(item)["url"]
        source_type = dict(item)["type"]

        print("Processing:", url)

        try:

            if source_type == "pdf":

                pdf_path = download_pdf(url)

                text = extract_pdf_text(pdf_path)

            else:

                r = requests.get(url)

                soup = BeautifulSoup(r.text, "html.parser")

                text = soup.get_text()

            chunks = chunk_text(text)

            store_chunks(chunks, url, source_type)

            json_data = {
                "url": url,
                "source_type": source_type,
                "raw_text": text,
                "chunks": [{"id": f"chunk_{i}", "text": c} for i, c in enumerate(chunks)]
            }

            all_tutorials.append(json_data)

            print(f"Queued JSON data for {url}")

        except Exception as e:

            print("Skipping:", url)
            print(e)

    # Save all tutorials into a single JSON file
    output_file = os.path.join(OUTPUT_FOLDER, "all_tutorials.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_tutorials, f, indent=2)

    print(f"Saved consolidated JSON → {output_file}")


if __name__ == "__main__":
    run_pipeline()