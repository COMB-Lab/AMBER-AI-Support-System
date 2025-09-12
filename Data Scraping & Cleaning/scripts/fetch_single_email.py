import sys
import time
from pathlib import Path

import requests
from requests.exceptions import RequestException, Timeout

URL = "http://archive.ambermd.org/202204/0000.html"
OUT_PATH = Path("data/html/202204/0000.html")

# 1) Keep a single place to define headers/timeout
HEADERS = {"User-Agent": "MyScraper/0.1"}
TIMEOUT_SECONDS = 10


def fetch_once(url: str, headers: dict, timeout: int) -> requests.Response:
    """
    Perform exactly one HTTP GET and return the Response.
    Intentionally lets RequestException/Timeout bubble to caller
    so the retry loop can decide what to do.
    """
    return requests.get(url, headers=headers, timeout=timeout)


def main():
    max_attempts = 3
    backoff_base_seconds = 1

    for attempt_num in range(1, max_attempts + 1):
        try:
            # 2) Call the single-attempt helper so exceptions are centralized
            response = fetch_once(URL, headers=HEADERS, timeout=TIMEOUT_SECONDS)

            # 3) Handle 200 success: write EXACT bytes for “exact HTML”
            if response.status_code == 200:
                OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
                OUT_PATH.write_bytes(response.content)  # exact raw bytes
                print(f"Saved to {OUT_PATH}")
                return  # stop cleanly

            # 4) Handle 4xx: don’t retry (usually a client error like 404)
            if 400 <= response.status_code < 500:
                print(f"Client error {response.status_code}; not retrying.")
                sys.exit(1)

            # 5) Handle 5xx or other unusual statuses: retry with backoff
            print(
                f"Server/temporary error {response.status_code} on attempt "
                f"{attempt_num}/{max_attempts}"
            )

        except (Timeout, RequestException) as e:
            # 6) Network-level exceptions: retry with backoff
            print(
                f"Network error on attempt {attempt_num}/{max_attempts}: {e.__class__.__name__} — {e}"
            )

        # 7) Exponential backoff only if there’s another attempt left
        if attempt_num < max_attempts:
            sleep_seconds = backoff_base_seconds * (2 ** (attempt_num - 1))
            print(f"Retrying after {sleep_seconds}s...")
            time.sleep(sleep_seconds)

    # 8) If we’re here, all attempts failed
    print(f"Request failed after {max_attempts} attempts.")
    sys.exit(1)


if __name__ == "__main__":
    main()