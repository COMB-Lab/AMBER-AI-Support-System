import requests
from pathlib import Path
import time
import hashlib
import argparse
import sys
# The webpaage to fetch 
DEFAULT_URL = "http://archive.ambermd.org/202204/0000.html"
# The file path to save the HTML locally
DEFAULT_OUT = "data/html/202204/0000.html"
RETRIES = 3
BACKOFF = 2  # seconds
TIMEOUT = 10  # seconds

# Function to fetch HTML from URL with retries and backoff
def fetch_url(url):
    headers = {"User-Agent": "AmberEmailFetcher/1.0"}
    # to identify the request
    for attempt in range(1, RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            # If the response is HTTP 200 Ok, returns the HTML text
            # Otherwise, get an error message
            if response.status_code == 200:
                return response.text
            else:
                print(f"Attempt {attempt}: HTTP {response.status_code} for {url}")
        except requests.RequestException as e:
            print(f"Attempt {attempt}: Network error: {e}")
        if attempt < RETRIES:
            time.sleep(BACKOFF * attempt)
    return None

# Save HTML content to a file
def save_html(content, out_path):
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(content, encoding="utf-8")

# Compute SHA256 checksum of content
def sha256_checksum(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def main():
    # Get command-line arguments
    parser = argparse.ArgumentParser(description="Fetch a single Amber email HTML page.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Target URL to fetch")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output file path")
    args = parser.parse_args()

    # Fetch HTML
    html = fetch_url(args.url)
    # If it cannot get the html
    if not html:
        print("Failed to fetch the URL after retries.", file=sys.stderr)
        sys.exit(1)

    # Save HTML local network
    save_html(html, args.out)

    # Compute SHA256 checksum
    checksum = sha256_checksum(html)
    print(f"Downloaded HTML successfully: {args.out}")
    print(f"SHA256 checksum: {checksum}")

if __name__ == "__main__":
    main()
