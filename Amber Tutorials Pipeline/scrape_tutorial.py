import requests
from bs4 import BeautifulSoup

def scrape_tutorial(url):
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else url

    chunks = []
    current_section = "Introduction"

    for tag in soup.find_all(["h2", "h3", "p", "pre", "li"]):
        if tag.name in ["h2", "h3"]:
            current_section = tag.get_text(strip=True)
        else:
            text = tag.get_text(" ", strip=True)

            # Remove navigation / junk
            if len(text) < 50:
                continue

            chunks.append({
                "title": title,
                "section": current_section,
                "content": text,
                "url": url,
                "source": "amber_tutorial"
            })

    return chunks
