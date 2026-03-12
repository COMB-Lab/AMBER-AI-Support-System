import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def extract_links(base_url):

    r = requests.get(base_url)
    soup = BeautifulSoup(r.text, "html.parser")

    links = []

    for a in soup.find_all("a", href=True):

        link = urljoin(base_url, a["href"])

        if "ambermd.org/tutorials" in link:

            if ".pdf" in link:
                links.append({"type": "pdf", "url": link})
            else:
                links.append({"type": "html", "url": link})

    return list(set(tuple(d.items()) for d in links))
