import os
import json
import time
import requests
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime
from datetime import datetime
import logging


BASE_URL = "http://archive.ambermd.org"
START_YEAR = 2020
END_YEAR = 2025
OUTPUT_DIR = "/opt/airflow/data"    
DELAY = 0.5              
LOG_FILE = "/opt/airflow/dags/scraper.log" 

# Logging setup
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Create data directory if it doesn’t exist
os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_url(url, retries=3, delay=5):
    """Fetch a URL with retries and backoff."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException as e:
            logging.warning(f"Request failed ({url}): {e}")
        time.sleep(delay)
    logging.error(f"Failed to fetch after {retries} retries: {url}")
    return None


def parse_message(url):
    """Parse a single message page."""
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

    # Extract headers from <b> tags
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

    # Extract message body
    body_tag = soup.find("pre")
    record["body"] = body_tag.get_text("\n", strip=True) if body_tag else ""

    return record


def normalize_subject(subject):
    """Normalize subject to remove 'Re:' or 'Fwd:' prefixes for thread linking."""
    import re
    if not subject:
        return ""
    return re.sub(r'^(re:\s*|fwd:\s*)+', '', subject.strip(), flags=re.IGNORECASE)


def scrape_month(year, month):
    """Scrape all messages from a specific month."""
    index_url = f"{BASE_URL}/{year}{month:02d}/"
    html = fetch_url(index_url)
    if not html:
        logging.warning(f"No index found for {year}-{month:02d}")
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


def group_into_threads(messages):
    
    threads = {}
    by_id = {m["message_id"]: m for m in messages if m.get("message_id")}

    for msg in messages:
        if not msg.get("message_id"):
            continue

        parent_id = msg.get("in_reply_to")
        subject_key = normalize_subject(msg.get("subject"))

        if parent_id and parent_id in by_id:
            root_id = parent_id
        else:
            root_id = None
            for t_id, t in threads.items():
                if normalize_subject(t["subject"]) == subject_key:
                    root_id = t_id
                    break
            if not root_id:
                root_id = msg["message_id"]

        if root_id not in threads:
            threads[root_id] = {
                "thread_id": root_id,
                "subject": msg.get("subject"),
                "messages": []
            }

        if msg["message_id"] != root_id:
            msg.pop("subject", None)
            msg["in_reply_to"] = root_id

        threads[root_id]["messages"].append(msg)
    return threads


def save_threads(threads, year, month):
    
    year_folder = os.path.join(OUTPUT_DIR, str(year))
    os.makedirs(year_folder, exist_ok=True)

    for thread in threads.values():
        thread_id = thread["thread_id"]
        file_name = f"{year}_{month:02d}_{thread_id}.json"
        file_path = os.path.join(year_folder, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)
        logging.info(f"Saved {file_name}")




def scrape_new_data():
    """
    Incrementally scrape new data.
    - On first run: scrape all 2020–2025.
    - On later runs: scrape new months only.
    """
    logging.info("Starting scraping job...")

    # Track which months have already been scraped
    state_file = os.path.join(OUTPUT_DIR, "scraper_state.json")
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            state = json.load(f)
    else:
        state = {"completed_months": []}

    completed = set(state["completed_months"])
    new_completed = []

    for year in range(START_YEAR, END_YEAR + 1):
        for month in range(1, 13):
            month_key = f"{year}-{month:02d}"
            if month_key in completed:
                continue  # Skip already processed months

            logging.info(f"Scraping {month_key} ...")
            messages = scrape_month(year, month)
            if not messages:
                continue

            threads = group_into_threads(messages)
            save_threads(threads, year, month)

            new_completed.append(month_key)
            state["completed_months"].append(month_key)

            # Update state file
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)

    logging.info(f"Scraping complete. Added {len(new_completed)} new months.")
    return True


if __name__ == "__main__":
    scrape_new_data()
