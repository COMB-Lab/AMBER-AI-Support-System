import os
import json
import time
import re
import requests
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime


BASE_URL = "http://archive.ambermd.org"
START_YEAR = 2020
END_YEAR = 2025
OUTPUT_DIR = "data"   # Folder where JSON thread files will be saved
DELAY = 0.5           # Delay between requests to avoid overloading the server

os.makedirs(OUTPUT_DIR, exist_ok=True)  # Create output folder if it doesn't exist

# ----------------------------
# Fetch a URL with retry
# ----------------------------
def fetch_url(url, retries=3, delay=5):
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            pass
        time.sleep(delay)
    return None

# ----------------------------
# Parse a single message page
# ----------------------------
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

# ----------------------------
# Scrape all messages for a month
# ----------------------------
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

# ----------------------------
# Get subject (strip Re:/Fwd:)
# ----------------------------
def clean_subject(subject):
    if not subject:
        return ""
    return re.sub(r'^(re:\s*|fwd:\s*)+', '', subject.strip(), flags=re.IGNORECASE)

# ----------------------------
# Group messages into threads
# ----------------------------
def group_into_threads(messages):
    threads = {}
    by_id = {m["message_id"]: m for m in messages if m.get("message_id")}
    subject_map = {}

    for msg in messages:
        if not msg.get("message_id"):
            continue

        root_id = None

        # Case 1: Use in-reply-to if available
        parent_id = msg.get("in_reply_to")
        if parent_id and parent_id in by_id:
            root_id = parent_id
            while by_id.get(root_id, {}).get("in_reply_to"):
                root_id = by_id[root_id]["in_reply_to"]

        # Case 2: Fall back to normalized subject
        if not root_id:
            normalized_subject = clean_subject(msg.get("subject", ""))
            if normalized_subject in subject_map:
                root_id = subject_map[normalized_subject]
            else:
                root_id = msg["message_id"]
                subject_map[normalized_subject] = root_id

        # Initialize thread
        if root_id not in threads:
            threads[root_id] = {
                "thread_id": root_id,
                "subject": clean_subject(msg.get("subject")),
                "messages": []
            }

        # For replies, remove redundant subject and set in_reply_to
        if msg["message_id"] != root_id:
            msg.pop("subject", None)
            msg["in_reply_to"] = root_id

        threads[root_id]["messages"].append(msg)

    return threads

# ----------------------------
# Save threads to JSON files
# ----------------------------
def save_threads(threads, year, month):
    for thread in threads.values():
        thread_id = thread["thread_id"]
        file_name = f"{year}_{month:02d}_{thread_id}.json"
        file_path = os.path.join(OUTPUT_DIR, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)
        print(f"[SAVED] {file_name}")

# ----------------------------
# Main driver: scrape all years
# ----------------------------
def scrape_years(start_year=START_YEAR, end_year=END_YEAR):
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            print(f"Scraping {year}-{month:02d} ...")
            messages = scrape_month(year, month)
            if not messages:
                continue
            threads = group_into_threads(messages)
            save_threads(threads, year, month)

# ----------------------------
# Run scraper
# ----------------------------
if __name__ == "__main__":
    scrape_years()
