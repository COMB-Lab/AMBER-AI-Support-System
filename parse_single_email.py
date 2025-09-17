from bs4 import BeautifulSoup
from pathlib import Path
import json
import re
from email.utils import parsedate_to_datetime
from datetime import timezone


HTML_PATH = Path("data/html/202204/0000.html")
OUT_PATH = Path("data/json/202204/0000.json")
URL = "http://archive.ambermd.org/202204/0000.html"
MESSAGE_ID = "amber-202204-0000"

def parse_email_html(html):
    soup = BeautifulSoup(html, "html.parser")


    subject_tag = soup.find("h1")
    subject = subject_tag.get_text(strip=True) if subject_tag else ""


    meta_tag = soup.find("i")
    meta_text = meta_tag.get_text(strip=True) if meta_tag else ""

    author_name = ""
    author_email_raw = ""
    date_raw = ""

    from_match = re.search(r"From:\s*(.*?)\s*\((.*?)\)", meta_text)
    if from_match:
        author_name = from_match.group(1)
        author_email_raw = from_match.group(2)

    email_deobfuscated = author_email_raw.replace(".", "@", 1) if "@" not in author_email_raw else author_email_raw

    date_match = re.search(r"Date:\s*(.*)", meta_text)
    if date_match:
        date_raw = date_match.group(1)

    try:
        dt = parsedate_to_datetime(date_raw)
        date_iso = dt.isoformat()
        date_utc = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        date_iso = ""
        date_utc = ""


    pre_tags = soup.find_all("pre")
    received_raw = ""
    body_text = ""

    if pre_tags:
        full_text = pre_tags[-1].get_text()
        lines = full_text.strip().splitlines()
        body_text = full_text.strip()
        for line in lines:
            if line.startswith("Received on"):
                received_raw = line.strip()
                break


    attachments = []
    for img in soup.find_all("img"):
        filename = Path(img.get("src", "")).name
        if filename:
            attachments.append({
                "filename": filename,
                "mime": "image/png"
            })


    replies = []
    next_title = ""
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if text.startswith("Re:"):
            replies.append(text)
        elif "Re:" in text:
            next_title = text

    return {
        "message_id": MESSAGE_ID,
        "url": URL,
        "subject": subject,
        "author_name": author_name,
        "author_email_raw": author_email_raw,
        "author_email_deobfuscated": email_deobfuscated,
        "date_raw": date_raw,
        "date_iso": date_iso,
        "date_utc": date_utc,
        "received_raw": received_raw,
        "thread_id": subject.lower(),
        "body_text": body_text,
        "attachments": attachments,
        "nav_links": {
            "this_message": "Message body",
            "next_message_title": next_title,
            "next_in_thread_title": next_title,
            "replies_titles": replies
        }
    }

def main():
    if not HTML_PATH.exists():
        print("HTML file not found.")
        return

    html = HTML_PATH.read_text(encoding="utf-8")
    parsed = parse_email_html(html)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(parsed, f, indent=2, ensure_ascii=False)

    print(f"Parsed email saved to {OUT_PATH}")

if __name__ == "__main__":
    main()
