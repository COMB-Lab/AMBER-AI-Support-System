import os
import json
import time
import requests
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
import logging

# ----------------------------
# Configuration
# ----------------------------
BASE_URL = "http://archive.ambermd.org"
OUTPUT_DIR = "data"          # Root folder for JSON files
DELAY = 0.5
LAST_SCRAPED_FILE = "last_scraped.json"

# Ensure output folder exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# Fetch URL with retries
def fetch_url(url, retries=3, delay=5):
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException as e:
            logging.warning(f"Attempt {attempt+1}: Failed to fetch {url} - {e}")
        time.sleep(delay)
    return None


# Parse individual message
def parse_message(url):
    html = fetch_url(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    record = {
        "message_id": None,
        "subject": None,
        "author": None,
        "date_raw": None,
        "body": None,
        "url": url,
        "in_reply_to": None
    }

    for b in soup.find_all("b"):
        key = b.get_text(strip=True).strip(":").lower()
        value = b.next_sibling.strip() if b.next_sibling else ""

        if key == "subject":
            record["subject"] = value
        elif key == "from":
            record["author"] = value
        elif key == "date":
            record["date_raw"] = value
            try:
                dt = parsedate_to_datetime(value)
                record["message_id"] = int(dt.timestamp())
            except Exception:
                pass
        elif key == "in-reply-to":
            try:
                dt = parsedate_to_datetime(value)
                record["in_reply_to"] = int(dt.timestamp())
            except Exception:
                pass

    body_tag = soup.find("pre")
    record["body"] = body_tag.get_text("\n", strip=True) if body_tag else ""
    return record


# Scrape all messages for a given month
def scrape_month(year, month):
    index_url = f"{BASE_URL}/{year}{month:02d}/"
    html = fetch_url(index_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True) if a["href"].endswith(".html")]

    messages = []
    for link in links:
        msg_url = f"{index_url}{link}"
        record = parse_message(msg_url)
        if record:
            messages.append(record)
            time.sleep(DELAY)
    return messages


# Group messages into threads
def group_into_threads(messages):
    threads = {}
    by_id = {m["message_id"]: m for m in messages if m.get("message_id")}
    for msg in messages:
        if not msg.get("message_id"):
            continue
        parent_id = msg.get("in_reply_to")
        if parent_id and parent_id in by_id:
            root_id = parent_id
            while by_id.get(root_id, {}).get("in_reply_to"):
                root_id = by_id[root_id]["in_reply_to"]
        else:
            root_id = msg["message_id"]

        if root_id not in threads:
            threads[root_id] = {"thread_id": root_id, "subject": msg.get("subject"), "messages": []}

        if msg["message_id"] != root_id:
            msg.pop("subject", None)
            msg["in_reply_to"] = root_id

        threads[root_id]["messages"].append(msg)
    return threads


# Save thread JSON files in year folder
def save_threads(threads, year, month):
    year_dir = os.path.join(OUTPUT_DIR, str(year))   # Folder per year
    os.makedirs(year_dir, exist_ok=True)

    for thread in threads.values():
        thread_id = thread["thread_id"]
        file_name = f"{year}_{month:02d}_{thread_id}.json"
        file_path = os.path.join(year_dir, file_name)

        if os.path.exists(file_path):
            continue

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)
        logging.info(f"[SAVED] {file_path}")


# Track last scraped month
def read_last_scraped():
    if os.path.exists(LAST_SCRAPED_FILE):
        with open(LAST_SCRAPED_FILE, "r") as f:
            return json.load(f)
    return {"year": 2020, "month": 0}


def update_last_scraped(year, month):
    with open(LAST_SCRAPED_FILE, "w") as f:
        json.dump({"year": year, "month": month}, f)


# Main function: incremental scraping
def scrape_new_data(end_year=2025):
    last = read_last_scraped()
    total_threads = 0
    for year in range(last["year"], end_year + 1):
        start_month = last["month"] + 1 if year == last["year"] else 1
        for month in range(start_month, 13):
            logging.info(f"Scraping {year}-{month:02d} ...")
            messages = scrape_month(year, month)
            if not messages:
                continue
            threads = group_into_threads(messages)
            save_threads(threads, year, month)
            total_threads += len(threads)
            update_last_scraped(year, month)
    logging.info(f" Incremental scraping finished. Total threads scraped: {total_threads}")
    return total_threads


if __name__ == "__main__":
    scrape_new_data()
