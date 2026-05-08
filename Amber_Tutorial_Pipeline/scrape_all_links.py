import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load the tutorial_links JSON
with open('tutorial_links.json', 'r') as f:
    tutorial_links = json.load(f)

# Collect all unique links from the values
all_links = set()
for links in tutorial_links.values():
    all_links.update(links)

print(f"Total unique links to scrape: {len(all_links)}")

# Dictionary to store scraped links for each link
scraped_links = {}

# Function to get all links from a URL
def get_links(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        if len(response.content) < 100:  # Skip if content is too small, likely empty
            return url, []
        soup = BeautifulSoup(response.content, 'html.parser')
        links = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Make absolute URL
            absolute_url = urljoin(url, href)
            links.add(absolute_url)
        return url, list(links)
    except Exception as e:
        # Skip on error
        return url, []

# Process each link in parallel
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(get_links, link) for link in all_links]
    for future in tqdm(as_completed(futures), total=len(all_links)):
        url, links = future.result()
        if links:  # Only store if links were found
            scraped_links[url] = links

# Save to new JSON file
with open('all_scraped_links.json', 'w') as f:
    json.dump(scraped_links, f, indent=2)

print("Scraping complete. Links saved to all_scraped_links.json")