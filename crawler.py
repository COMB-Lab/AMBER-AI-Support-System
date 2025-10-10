import re

import requests
import pathlib
import time
from bs4 import BeautifulSoup
from webScraper import scrape


BASE_URL = "http://archive.ambermd.org/"
OUTPUT_DIR = pathlib.Path("data") / "html"
START_YEAR = 2020
END_YEAR = 2025


def get_monthly_archive_links(start_year: int, end_year: int):
    print("Fetching list of monthly archives...")
    response = requests.get(BASE_URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    monthly_links = []
    # This finds links like './202204/'
    link_tags = soup.find_all('a', href=re.compile(r'^\./\d{6}/$'))

    for tag in link_tags:
        href = tag['href']
        # Extract the year from the link text (e.g., './202204/' -> '2022')
        year_str = href[2:6]
        year = int(year_str)
        if start_year <= year <= end_year:
            # Construct the full URL
            full_url = f"{BASE_URL}{href[2:]}"
            monthly_links.append(full_url)

    print(f"Found {len(monthly_links)} monthly archives between {start_year} and {end_year}.")
    return monthly_links


def scrape_month(month_url: str):
    print(f"--- Processing month: {month_url} ---")
    try:
        response = requests.get(month_url)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Could not fetch month page {month_url}: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # Links to indv messages
    message_tags = soup.find_all('a', href=re.compile(r'^\d{4}\.html$'))

    if not message_tags:
        print("No links found on this page.")
        return

    # Extract year and month
    year_month_str = month_url.strip('/').split('/')[-1]

    for tag in message_tags:
        message_filename = tag['href']
        message_url = f"{month_url}{message_filename}"

        # Where the file should be stored
        output_path = OUTPUT_DIR / year_month_str / message_filename

        print(f"Downloading {message_url}...")
        scrape(message_url, output_path)


def main():
    monthly_links = get_monthly_archive_links(START_YEAR, END_YEAR)

    # Sort to process in chronological order
    for link in sorted(monthly_links):
        scrape_month(link)



if __name__ == "__main__":
    main()