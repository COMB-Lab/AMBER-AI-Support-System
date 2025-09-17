import requests
import time
from pathlib import Path

# Constants
URL = "http://archive.ambermd.org/202204/0000.html"
OUT_PATH = Path("data/html/202204/0000.html")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AmberFetcher/1.0)"}
MAX_RETRIES = 3
BACKOFF_SECONDS = 2

def fetch_email(url, out_path):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"Attempt {attempt} to fetch {url}")
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(response.text, encoding='utf-8')
                print(f"Success: Saved to {out_path}")
                return
            else:
                print(f"HTTP {response.status_code} received.")
        except requests.RequestException as e:
            print(f"Network error: {e}")

        if attempt < MAX_RETRIES:
            print(f"Retrying in {BACKOFF_SECONDS} seconds...")
            time.sleep(BACKOFF_SECONDS)

    print("Failed to fetch after multiple attempts.")


if __name__ == "__main__":
    fetch_email(URL, OUT_PATH)
