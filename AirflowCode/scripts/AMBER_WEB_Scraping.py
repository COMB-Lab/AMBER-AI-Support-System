import time
from pathlib import Path
import shutil
import calendar
import json
import os
import re
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup, Comment
from email.utils import parsedate_to_datetime
from datetime import timezone
from zoneinfo import ZoneInfo


class AmberData:
    def __init__(self, year):
        self.year = year
        self.months = {}   # month -> month URL (or yyyymm)
        self.messages = {}  # month -> [ "0000.html", "0001.html", ... ]
        self.cleanData = {}  # month -> [ {parsed message dict}, ... ]

    def addMonths(self, month, value):
        self.months[month] = value

    def addMonthMessages(self, month, value):
        self.messages.setdefault(month, []).append(value)

    def getMonthValue(self, month):
        return self.months.get(month)

    def getMessageValue(self, month):
        return self.messages.get(month, [])

    def getCleanDataValue(self,key):
        return self.cleanData.get(key)

    def __str__(self):
        return f"AmberData(Year={self.year}, Months={list(self.months.keys())})"


dataUrl = "http://archive.ambermd.org/"
response = requests.get(dataUrl)
soup = BeautifulSoup(response.text, "html.parser")
dataDictionary = {}

workingWithYear = "2020"
workingWithMonth = "Jan"
workingWithFileName = "amber_2020_Jan.json"

yearStart = 2020
yearEnd = 2025
'''
Year: AmberObject(Year)
        self.year = year
        self.months = {
                Mar: 202203
                }   # month -> link
        self.messages = {
                Mar: [0000.html,0001.html,...]
                }  # month -> [msg]
        self.cleanData = {
             "message_id": None,
             "url": url,
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
                 "replies_titles": [],
                 "in_reply_to_title": None,
                 "in_reply_to_link": None
            }
        }     
'''


def getData():
    allHeader3 = soup.find_all("h3")
    year = None
    ad = None

    for h3 in allHeader3:
        text = h3.get_text(strip=True)

        if text.isdigit():
            # Save the previous year object if it exists
            if ad is not None:
                dataDictionary[f"{year}"] = ad
            year = text
            ad = AmberData(year)

        else:
            # Find the <a> tag for this month in the siblings
            a = h3.find_next("a")
            if a and a.get("href", "").startswith("./"):
                link = urljoin(dataUrl, a["href"])
                ad.addMonths(text, link)

    # Add the last year
    if ad is not None:
        dataDictionary[f"{year}"] = ad

    print("Populating Messages...")

    # Gets a single Year/ Month Review
    # getReviews(dataDictionary[workingWithYear], workingWithMonth)
    print("Success!")

    print("Populating Clean Data...")

    # Populates a single data
    # populateCleanData(workingWithYear, workingWithMonth)

    # Populates ONLY 2020–2025
    for year_str in sorted(dataDictionary.keys(), key=int):
        y = int(year_str)
        if yearStart <= y <= yearEnd:
            amberObj = dataDictionary[year_str]
            out_dir = Path(f"RawData/{year_str}_Data")
            out_dir.mkdir(parents=True, exist_ok=True)

            for month in sorted(amberObj.months.keys(), key=lambda m: int(month_num(m))):
                print(f"Working on {year_str} {month} ...")
                file_name = f"{year_str}_{month}.json"

                populateCleanData(year_str, month)
                export_month_to_json(year_str, month, file_name)

                # then move into the year folder
                src = Path(file_name)
                dst = out_dir / file_name
                shutil.move(str(src), str(dst))
                time.sleep(0.5)

    print("Success!")


def getReviews(ad, month):
    urlLink = ad.getMonthValue(month)
    reviewResponse = requests.get(urlLink)
    ReviewSoup = BeautifulSoup(reviewResponse.text, "html.parser")

    allMessages = ReviewSoup.find_all("a", href=True)

    for msg in allMessages:
        if msg["href"].startswith("0"):
            link = urljoin(urlLink, msg["href"])
            ad.addMonthMessages(month, link)
    print(f"Added {ad.year}: {month}")


def populateMessages():
    for yearKey, amberObj in dataDictionary.items():
        for month in amberObj.months.keys():
            # populate links for this month
            getReviews(amberObj, month)


def populateCleanData(year_key, month_key):
    amberObj = dataDictionary[year_key]
    if amberObj.cleanData is None:
        amberObj.cleanData = {}

    # ensure messages for this month
    if not amberObj.getMessageValue(month_key):
        getReviews(amberObj, month_key)

    month_url = amberObj.getMonthValue(month_key)

    for msg_link in amberObj.getMessageValue(month_key):
        full_url = msg_link if msg_link.startswith("http") else urljoin(month_url, msg_link)
        record = newRecord(full_url)

        try:
            resp = requests.get(full_url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # message_id = amber-YYYYMM-####
            msg_id = os.path.splitext(os.path.basename(urlparse(full_url).path))[0]
            mm = month_num(month_key)
            record["message_id"] = f"amber-{year_key}{mm}-{msg_id}"

            # --- HTML comments → metadata
            metadata = {}
            for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
                txt = c.strip()
                if "=" in txt:
                    k, v = txt.split("=", 1)
                    metadata[k.strip()] = v.strip().strip('"')

            # Subject / Author
            record["subject"] = record["subject"] or metadata.get("subject")
            raw_name = metadata.get("name", "")
            record["author_name"] = re.sub(r"\s+via\s+amber$", "", raw_name, flags=re.IGNORECASE).strip()
            record["author_email_raw"] = metadata.get("email")
            record["author_email_deobfuscated"] = deob_email(record["author_email_raw"])

            # Dates from `sent`
            sent_raw = metadata.get("sent")
            if sent_raw:
                try:
                    dt = parsedate_to_datetime(sent_raw)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    record["date_raw"] = sent_raw
                    record["date_iso"] = dt.isoformat()
                    record["date_utc"] = dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
                except Exception:
                    pass

            # Received → pretty local format
            recv_raw = metadata.get("received")
            if recv_raw:
                try:
                    dt_r = parsedate_to_datetime(recv_raw)
                    if dt_r.tzinfo is None:
                        # assume the archive timestamp is already in PDT
                        dt_r = dt_r.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
                    record["received_raw"] = "Received on " + dt_r.strftime("%a %b %d %Y - %H:%M:%S %Z")
                except Exception:
                    record["received_raw"] = f"Received on {recv_raw}"

            # Thread id (normalized subject)
            record["thread_id"] = clean_thread_id(record["subject"])

            # Body text (cut before footer if present)
            record["body_text"] = extract_body_text(soup, sent_raw)

            # Nav links first (so errors later won't wipe them)
            record["nav_links"] = extract_nav_links(soup, base_url=resp.url)

            # Attachments (now returns full URLs); protect so a hiccup doesn't kill nav links
            try:
                record["attachments"] = extract_attachments(soup, base_url=resp.url)
            except Exception as att_err:
                record["attachments"] = []
                record["nav_links"] = record.get("nav_links", {}) or {}
                record["nav_links"]["attachments_error"] = str(att_err)
        except Exception as e:
            # Capture error in nav_links for debugging; keep the record
            record["nav_links"] = record.get("nav_links", {}) or {}
            record["nav_links"]["error"] = str(e)

        amberObj.cleanData.setdefault(month_key, []).append(record)
        print(f"Added {record['message_id']}")


def month_num(month_key: str) -> str:
    month_key = month_key.strip()
    try:
        i = list(calendar.month_abbr).index(month_key)
    except ValueError:
        try:
            i = list(calendar.month_name).index(month_key)
        except ValueError:
            # fallback if month_key is invalid
            return "99"
    return str(i).zfill(2)


def deob_email(raw: str | None) -> str | None:
    if not raw: return None
    # keep raw with dot form; deobfuscated swaps the FIRST dot to @
    return raw.replace(".", "@", 1) if "." in raw else raw


def clean_thread_id(subject: str | None) -> str | None:
    if not subject: return None
    # remove leading [AMBER] and quote marks, lower
    s = re.sub(r"^\s*\[AMBER\]\s*", "", subject, flags=re.I)
    s = s.strip().strip('"').strip()
    # normalize inner quotes to lower-case version of subject
    return s.lower()


def extract_body_text(soup: BeautifulSoup, sent_raw: str | None) -> str | None:
    mail_div = soup.select_one("div.mail")
    if not mail_div:
        return None

    # full text with line breaks
    text = mail_div.get_text("\n", strip=True)

    # start at the sent_raw date line
    if sent_raw and sent_raw in text:
        _, after = text.split(sent_raw, 1)
        body = after.strip()
    else:
        body = text

    # cut at footer markers
    for marker in ["_______________________________________________", "Received on"]:
        if marker in body:
            body = body.split(marker, 1)[0].strip()

    return body


def extract_attachments(soup: BeautifulSoup, base_url: str) -> list:
    out = []

    # honor <base href> if present
    base_tag = soup.find("base", href=True)
    effective_base = base_tag["href"] if base_tag else base_url

    def infer_mime(filename: str) -> str | None:
        ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
        if ext == 'png': return 'image/png'
        if ext in ('jpg', 'jpeg'): return 'image/jpeg'
        if ext == 'gif': return 'image/gif'
        if ext == 'pdf': return 'application/pdf'
        return None

    # 1) <a href="att-0000/...">
    for a in soup.select('div.mail a[href]'):
        href = a.get('href', '')
        if 'att-' in href:
            full_url = urljoin(effective_base, href)
            filename = href.split('/')[-1]
            out.append({
                "filename": filename,
                "mime": infer_mime(filename),
                "url": full_url
            })

    # 2) <img src="att-0000/...">
    for img in soup.select('div.mail img[src]'):
        src = img.get('src', '')
        if 'att-' in src:
            full_url = urljoin(effective_base, src)
            filename = src.split('/')[-1]
            out.append({
                "filename": filename,
                "mime": infer_mime(filename),
                "url": full_url
            })

    # Deduplicate by URL
    seen = set()
    unique = []
    for item in out:
        u = item.get("url")
        if u and u not in seen:
            seen.add(u)
            unique.append(item)

    return unique


def norm(s):
    return " ".join((s or "").split())


def extract_nav_links(soup, base_url: str | None = None):

    this_message = None
    next_message_title = None
    next_in_thread_title = None
    replies_titles = []
    inReplyToTitle = None
    inReplyToLink = None

    base_tag = soup.find("base", href=True)
    effective_base = base_tag["href"] if base_tag else (base_url or "")

    # 1) "This message"
    a = soup.select_one("a#options1")
    if a:
        this_message = norm(a.get_text(" ", strip=True)) or "Message body"

    # 2) Next message / next in thread (prefer title attr that has author+subject)
    for a in soup.select("div.head a, div.foot a"):
        txt = (a.get_text(" ", strip=True) or "").lower()
        title_attr = norm(a.get("title"))
        # print(f"a: {a}")
        # print(f"txt: {txt}")
        # print(f"title_attr: {title_attr}")
        if "next message" in txt and (title_attr or txt):
            next_message_title = title_attr or norm(a.get_text(" ", strip=True))
        elif "next in thread" in txt and (title_attr or txt):
            next_in_thread_title = title_attr or norm(a.get_text(" ", strip=True))
        elif "in reply to" in txt and (title_attr or txt):
            inReplyToTitle = title_attr or norm(a.get_text(" ", strip=True))
            href = a.get("href")
            inReplyToLink = urljoin(effective_base, href) if href else None

    # 3) Replies
    #   Look in both head & foot nav blocks.
    for section in soup.select("div.head, div.foot"):
        for li in section.find_all("li"):
            dfn = li.find("dfn")
            if not dfn:
                continue
            if dfn.get_text(strip=True).lower() in ("reply", "replies"):
                for a in li.find_all("a", href=True):
                    t = norm(a.getText())
                    if t:
                        replies_titles.append(t)

    seen = set()
    replies_titles = [t for t in replies_titles if not (t in seen or seen.add(t))]

    return {
        "this_message": this_message,
        "next_message_title": next_message_title,
        "next_in_thread_title": next_in_thread_title,
        "replies_titles": replies_titles,
        "in_reply_to_title": inReplyToTitle,
        "in_reply_to_link": inReplyToLink
    }


def newRecord(url: str) -> dict:
    return {
        "message_id": None,
        "url": url,
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
            "replies_titles": [],
            "in_reply_to_title": None,
            "in_reply_to_link": None
        }
    }


def export_month_to_json(year_key: str, month_key: str, out_path: str):
    amberObj = dataDictionary[year_key]
    data = amberObj.getCleanDataValue(month_key) or []

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(data)} messages to {out_path}")


def export_range_to_json(start_year: int, end_year: int, out_path: str):
    export_data = {}
    for year in range(start_year, end_year + 1):
        year_str = str(year)
        if year_str in dataDictionary:
            export_data[year_str] = dataDictionary[year_str].cleanData
        else:
            print(f"No data for {year_str}")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    print(f"Wrote years {start_year}-{end_year} to {out_path}")


def export_all_to_json(out_path: str):
    export_data = {}
    for year, amberObj in dataDictionary.items():
        export_data[year] = amberObj.cleanData

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    print(f"Wrote archive to {out_path}")


def printData():
    for yearKey, amberObj in dataDictionary.items():
        print(f"Year {yearKey}:")
        for month in amberObj.months.keys():
            print(f"  {month}:")
            for link in amberObj.getMessageValue(month):
                print(f"    {link}")


getData()

# export_month_to_json(workingWithYear, workingWithMonth, workingWithFileName)

# export_range_to_json(2022, 2025, "amber_2022_2025.json")

# export_all_to_json("AmberCleanData.json")
'''
for i, msg in enumerate(msgs, start=1):
    print(f"\nMessage {i}:")
    for k, v in msg.items():
        print(f"  {k}: {v}")
'''
