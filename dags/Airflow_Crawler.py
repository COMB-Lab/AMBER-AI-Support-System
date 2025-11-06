import requests
from bs4 import BeautifulSoup
import pathlib
from urllib.parse import urljoin
from Airflow_Scraper import scrape

BASE_URL = "http://archive.ambermd.org/"
OUTPUT_DIR = pathlib.Path("data") / "html"


def get_monthly_archive_links(start_year, end_year):

    # Gets all the monthly archive links from the main archive page.
    monthly_links = []
    response = requests.get(BASE_URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    for year in range(start_year, end_year + 1):
        year_links = soup.find_all('a', href=lambda href: href and str(year) in href)
        for link in year_links:
            monthly_links.append(urljoin(BASE_URL, link['href']))
    return monthly_links


def scrape_month(url):

    # Scrapes all the individual message links from a given month's archive page.
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    message_links = soup.select('a[href$=".html"]')

    for link in message_links:
        message_url = urljoin(url + '/', link['href'])

        parts = message_url.split('/')
        if len(parts) >= 2:
            year_month = parts[-2]
            filename = parts[-1]
            output_path = OUTPUT_DIR / year_month / filename
            scrape(message_url, output_path)