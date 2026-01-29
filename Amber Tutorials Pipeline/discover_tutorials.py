import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

def discover_tutorial_links():
    r = requests.get("https://ambermd.org/tutorials/", timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)

        # Keep only real tutorial links
        if href.startswith("/") and "tutorials" in href and len(text) > 3:
            links.add(urljoin("https://ambermd.org", href))

    return sorted(list(links))
