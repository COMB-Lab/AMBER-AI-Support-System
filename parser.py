import pathlib
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone


def parse(input_path: pathlib.Path, output_path: pathlib.Path):

    # Read HTML content from a file
    with open(input_path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    print(soup.prettify())

    # Dictionary
    data = {
        "message_id": None,
        "url": None,
        "subject": None,
        "author_name": None,
        "author_email_raw": None,
        "author_email_deobfuscated": None,
        "date_raw": None,
        "date_iso": None,
        "date_utc": None,
        "received_raw": None,
        "thread_id": None,
        "body_text": None,
        "attachments": [],
        "nav_links": {
            "this_message": None,
            "next_message_title": None,
            "next_in_thread_title": None,
            "replies_titles": []
        }
    }

    # Subject
    # Fetch the raw data
    subject_tag = soup.find('h1')
    if subject_tag:
        data["subject"] = subject_tag.get_text(strip=True)

    # Author - And Email
    # Fetch the raw data
    author_tag = soup.find('span', id='from')
    if author_tag:
        # Remove Whitespace
        author_string = author_tag.get_text(strip=True)
        # Remove "From:"
        author_string = author_string.replace("From:", "").strip()

        # Split the name from the email part
        parts = author_string.split('<')
        data["author_name"] = parts[0].strip()

        # makes sure there's an email
        if len(parts) > 1:
            # Remove >
            data["author_email_raw"] = parts[1].replace('>', '').strip()
            # De-obfuscate the email by replacing the first dot with an @
            data["author_email_deobfuscated"] = data["author_email_raw"].replace('.', '@', 1)

    # Date
    # Fetch the raw data
    date_tag = soup.find('span', id='date')
    if date_tag:
        raw_date_string = date_tag.get_text(strip=True)
        # Remove "Date:"
        data["date_raw"] = raw_date_string.replace("Date:", "").strip()

    if data["date_raw"]:
        # Parse the date string.
        # Format: "Fri, 1 Apr 2022 12:17:04 +0300"
        dt_object = datetime.strptime(data["date_raw"], "%a, %d %b %Y %H:%M:%S %z")

        dt_utc = dt_object.astimezone(timezone.utc)

        # Format to ISO
        data["date_iso"] = dt_object.isoformat()

        # Convert to UTC and format to ISO 8601 with 'Z'
        data["date_utc"] = dt_object.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Convert to epoch timestamp (integer)
        epoch_time = int(dt_utc.timestamp())
        data["message_id"] = epoch_time

    # Body
    # First find the mail tag (This is where the body is located)
    mail_tag = soup.find('div', class_='mail')
    if mail_tag:
        # Then find the start of the actual body without metadeta
        start_tag = mail_tag.find("a", {"name": "start"})

        if start_tag:
            # Find all strings and merge them together
            raw_body = ' '.join(start_tag.find_all_next(string=True)).strip()

            # Now split the body by the -------------------------------
            body_parts = raw_body.split('_______________________________________________')

            # Now just keep the first part
            data["body_text"] = body_parts[0].strip()

    # Attachments
    if mail_tag:
        # Find all image tags within the mail body
        attachment_tags = mail_tag.find_all('img')
        for tag in attachment_tags:

            # The filename is in "alt"
            filename = tag.get('alt')
            if filename:
                data["attachments"].append({"filename": filename, "mime": ""})

    # Received Raw
    rec_tag = soup.find('span', id='received')
    if rec_tag:
        rec_string = rec_tag.get_text(strip=True)
        rParts = rec_string.split('on')
        data["received_raw"] = rParts[1].strip()

    # Thread ID
    if subject_tag:
        thread_string = subject_tag.get_text(strip=True)

        # Take out the [AMBER]
        sParts = thread_string.split("[AMBER]")
        data["thread_id"] = sParts[1].strip()

    # Navigation Link
    foot = soup.find('div', class_='foot')
    if foot:
        # This finds the first <a> with the tile I want
        next_msg_tag = foot.select_one('a[title^="Next message in the list"]')
        next_thread_tag = foot.select_one('a[title^="Next message in this discussion thread"]')

        data["nav_links"]["this_message"] = "Message body"
        if next_msg_tag:
            data["nav_links"]["next_message_title"] = next_msg_tag.get_text(strip=True)
        if next_thread_tag:
            data["nav_links"]["next_in_thread_title"] = next_thread_tag.get_text(strip=True)

    # Replies
    if foot:
        # Select all titles with this messages
        reply = foot.select('a[title^="Message sent in reply to this message"]')

        # Since there can be 0 or an infinite amount of replies, we do a for loop
        for tag in reply:
            # For each tag in reply, place text into the list of the replies in nav links
            data["nav_links"]["replies_titles"].append(tag.get_text(strip=True))

    # --- Save to JSON ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved JSON to {output_path}")

def main():

    # This test case is AI Generated for simplicity

    # Define the input and output for a single test file
    # You would change these paths to process any file you want
    input_file = pathlib.Path("data/html/202204/0000.html")
    output_file = pathlib.Path("data/json/202204/0000.json")

    print("--- Running single file test ---")
    parse(input_file, output_file)
    print("\n--- Test complete ---")
    print(f"Check the output file at: {output_file}")

if __name__ == "__main__":
    main()
