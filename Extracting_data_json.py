from pathlib import Path
import json
from bs4 import BeautifulSoup, Comment
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

IN_HTML = "data/html/202204/0000.html"
OUT_JSON = "data/json/202204/0000.json"
# The URL page of the website
BASE_URL = "http://archive.ambermd.org/202204/0000.html"

#Extract data of the email
def extract_email_data(html_content, url=BASE_URL):
    soup = BeautifulSoup(html_content, "html.parser")
    
    data = {}
    data["message_id"] = Path(url).stem
    data["url"] = url
    
    # Extract data from HTML 
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for c in comments:
        c = c.strip()
        if "=" in c:
            key, value = c.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"')
            if key == "name":
                data["author_name"] = value
            elif key == "email":
                data["author_email_raw"] = value
                # deobfuscate email
                data["author_email_deobfuscated"] = value.replace(".", "@") if "@" not in value else value
            elif key == "subject":
                data["subject"] = value
            elif key == "sent":
                data["date_raw"] = value
                dt = parsedate_to_datetime(value)
                data["date_iso"] = dt.isoformat()
                data["date_utc"] = dt.astimezone().isoformat()
    
    # Extract message body
    
    body_tag = soup.find("pre")
    if body_tag:
        data["body_text"] = body_tag.get_text().strip()
    else:
        # fallback: get all text after metadata table
        main_table = soup.find("table")
        if main_table:
            # skip  rows
            rows = main_table.find_all("tr")
            body_texts = []
            for row in rows:
                tds = row.find_all("td")
                if len(tds) == 2:
                    label, value = tds
                    if label.get_text().strip().lower() not in ["from", "subject", "date", "to"]:
                        body_texts.append(value.get_text().strip())
            data["body_text"] = "\n".join(body_texts)
    
    # Extract attachment of the image
    attachments = []
    for a in soup.find_all("a", href=True):
        if any(a["href"].lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
            attachments.append({"filename": Path(a["href"]).name, "mime": f"image/{Path(a['href']).suffix[1:]}"})
    if attachments:
        data["attachments"] = attachments
    
    # Get the message and link
    nav_links = {}
    next_msg = soup.find("a", string=lambda x: x and "Next message" in x)
    next_thread = soup.find("a", string=lambda x: x and "Next in thread" in x)
    replies = soup.find_all("a", string=lambda x: x and "Re:" in x)
    
    nav_links["this_message"] = "Message body"
    nav_links["next_message_title"] = next_msg.get_text(strip=True) if next_msg else ""
    nav_links["next_in_thread_title"] = next_thread.get_text(strip=True) if next_thread else ""
    nav_links["replies_titles"] = [r.get_text(strip=True) for r in replies] if replies else []
    
    data["nav_links"] = nav_links
    
    #  ID 
    data["thread_id"] = data.get("subject", "")
    
    return data

def main():
    html_file = Path(IN_HTML)
    if not html_file.exists():
        print(f"HTML file not found: {IN_HTML}")
        return

    html_content = html_file.read_text(encoding="utf-8")
    email_data = extract_email_data(html_content)

    # Save JSON
    out_file = Path(OUT_JSON)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(email_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Email data saved as JSON: {OUT_JSON}")
    print("Preview:", json.dumps(email_data, ensure_ascii=False, indent=2)[:500], "...")

if __name__ == "__main__":
    main()