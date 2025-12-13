import os
import requests
from bs4 import BeautifulSoup
import json


BASE_URL = "https://ambermd.org/tutorials/"
RAW_DIR = "tutorial_data/raw_html"  # Folder to store raw HTML
os.makedirs(RAW_DIR, exist_ok=True)


def scrape_tutorial():
    response = requests.get(BASE_URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = []
    for li in soup.find_all("li"):
        a_tag = li.find("a")
        if a_tag and a_tag.get("href") and "tutorial" in a_tag["href"].lower():
            full_url = a_tag["href"] if a_tag["href"].startswith("http") else BASE_URL + a_tag["href"]
            links.append(full_url)

   
    with open(os.path.join(RAW_DIR, "tutorial_links.json"), "w") as f:
        json.dump(links, f)

    print(f"Found {len(links)} tutorial links.")
    return links


def scrape_and_save_html():
    links = scrape_tutorial()
    for i, url in enumerate(links, 1):
        try:
            r = requests.get(url)
            r.raise_for_status()
            file_name = f"tutorial_{i}.html"
            with open(os.path.join(RAW_DIR, file_name), "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"Saved {url} as {file_name}")
        except Exception as e:
            print(f"Error scraping {url}: {e}")

if __name__ == "__main__":
    scrape_and_save_html()
