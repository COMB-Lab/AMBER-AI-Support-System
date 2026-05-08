import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load the tutorials JSON
with open('scraped_all_tutorials_output/all_tutorials.json', 'r') as f:
    tutorials = json.load(f)

# Dictionary to store links for each tutorial
tutorial_links = {}

# Function to get all links from a URL
def get_links(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        links = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Make absolute URL
            absolute_url = urljoin(url, href)
            links.add(absolute_url)
        return url, list(links)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return url, []

# Process each tutorial in parallel
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(get_links, tutorial['url']) for tutorial in tutorials]
    for future in tqdm(as_completed(futures), total=len(tutorials)):
        url, links = future.result()
        tutorial_links[url] = links

# Save to new JSON file
with open('tutorial_links.json', 'w') as f:
    json.dump(tutorial_links, f, indent=2)

print("Scraping complete. Links saved to tutorial_links.json")