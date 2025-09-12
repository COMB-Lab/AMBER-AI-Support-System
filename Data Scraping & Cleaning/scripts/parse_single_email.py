#!/usr/bin/env python3
"""
Parse a single Amber archive HTML email into structured JSON.

Usage:
  python scripts/parse_single_email.py \
    --in data/html/202204/0000.html \
    --url http://archive.ambermd.org/202204/0000.html \
    --out data/json/202204/0000.json

If --out is omitted, the JSON is only printed to stdout.
"""

import argparse
import json
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment
from email.utils import parsedate_to_datetime


def deobfuscate_email(raw: str) -> str:
    """
    Very common obfuscation in this archive:
      'user.gmail.com'  -> 'user@gmail.com'
      'user.yahoo.com'  -> 'user@yahoo.com'
    General heuristic:
      - if there's no '@' and it ends with '.<domain>.<tld>',
        replace the FIRST '.' with '@'.
    """
    if "@" in raw:
        return raw
    # common providers first (safer)
    for provider in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com"):
        if raw.endswith("." + provider):
            return raw.replace("." + provider, "@" + provider, 1)
    # generic fallback: split on first dot
    parts = raw.split(".", 1)
    if len(parts) == 2:
        return parts[0] + "@" + parts[1]
    return raw


def comment_kv_index(soup: BeautifulSoup) -> dict:
    """
    Build a small index of key="value" pairs embedded in HTML comments like:
      <!-- isosent="20220401091704" -->
      <!-- name="Erdem Yeler" -->
      <!-- email="erdemyeler.gmail.com" -->
      <!-- id="..."> (Message-Id)
    We keep the last occurrence of each key.
    """
    kv = {}
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        # extract key="value" pairs
        for m in re.finditer(r'([a-zA-Z_]+)\s*=\s*"([^"]*)"', c):
            kv[m.group(1)] = m.group(2)
    return kv


def text_between_start_and_received(mail_div: BeautifulSoup) -> str:
    """
    The message body starts after the anchor with id="start" and typically ends
    before the <span id="received"> stamp. Convert <br> to newlines.
    """
    start = mail_div.select_one("#start")
    if not start:
        # Fallback: just take the whole mail div text
        return mail_div.get_text("\n", strip=True)

    # Work on a small copy to safely mutate
    sub = BeautifulSoup(str(mail_div), "html.parser")

    # Remove headers block to avoid 'From'/'Date' duplicating into body
    addr = sub.select_one("address.headers")
    if addr:
        addr.decompose()

    # Remove 'received' stamp so it doesn't pollute the body
    rec = sub.select_one("span#received")
    if rec:
        rec.decompose()

    # Convert <br> to newline explicitly (BeautifulSoup's get_text can use a separator,
    # but converting <br> tags helps keep intended line structure)
    for br in sub.find_all("br"):
        br.replace_with("\n")

    # After cleanup, locate the 'start' anchor again and take the following content
    start2 = sub.select_one("#start")
    if not start2:
        return sub.get_text("\n", strip=True)

    # Collect text from siblings after the anchor until the end of the mail block
    lines = []
    for sib in start2.next_siblings:
        # only gather visible text
        if getattr(sib, "get_text", None):
            lines.append(sib.get_text())
        else:
            s = str(sib)
            if s.strip():
                lines.append(s)
    body = "".join(lines)

    # Normalize whitespace: collapse Windows newlines, trim trailing spaces
    body = re.sub(r"\r\n?", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def guess_attachments(mail_div: BeautifulSoup, base_url: str) -> list:
    """
    Find attachment links under att-XXXX paths, infer filename and MIME type.
    """
    atts = []
    seen = set()
    for a in mail_div.find_all("a", href=True):
        href = a["href"]
        if href.startswith("att-"):
            full = urljoin(base_url, href)
            filename = os.path.basename(urlparse(full).path)
            mime, _ = mimetypes.guess_type(full)
            at = {"filename": filename}
            if mime:
                at["mime"] = mime
            key = (filename, at.get("mime"))
            if key not in seen:
                seen.add(key)
                atts.append(at)
    return atts


def nav_info(soup: BeautifulSoup) -> dict:
    """
    Extract navigation titles:
      - 'this_message' (label text for the anchor to body)
      - 'next_message_title' (from link title w/ accesskey="d")
      - 'next_in_thread_title' (from link title w/ accesskey="t")
      - 'replies_titles' (titles of reply links)
    We look in both the top (#navbar) and footer (#navbarfoot) maps.
    """
    def first_map():
        for mid in ("#navbar", "#navbarfoot"):
            m = soup.select_one(mid)
            if m:
                yield m

    out = {"this_message": None,
           "next_message_title": None,
           "next_in_thread_title": None,
           "replies_titles": []}

    for m in first_map():
        # "This message" anchor label
        if out["this_message"] is None:
            this_link = m.find("a", attrs={"id": "options1"}) or m.find("a", string=re.compile("Message body", re.I))
            if this_link:
                out["this_message"] = (this_link.get_text(strip=True) or "Message body")

        # Next message / next in thread (access keys are common in this archive)
        if out["next_message_title"] is None:
            nxt = m.find("a", attrs={"accesskey": "d"})
            if nxt and nxt.has_attr("title"):
                out["next_message_title"] = nxt["title"]

        if out["next_in_thread_title"] is None:
            nxtt = m.find("a", attrs={"accesskey": "t"})
            if nxtt and nxtt.has_attr("title"):
                out["next_in_thread_title"] = nxtt["title"]

        # Replies: list items where <dfn>Reply</dfn> is present
        for li in m.find_all("li"):
            d = li.find("dfn")
            if d and "reply" in d.get_text(strip=True).lower():
                for a in li.find_all("a"):
                    title = a.get("title")
                    if title:
                        out["replies_titles"].append(title)

    # Final tidy defaults
    if out["this_message"] is None:
        out["this_message"] = "Message body"
    return out


def make_thread_id(subject: str) -> str:
    """
    Normalize to a lowercase thread key, strip leading [AMBER] or similar tags.
    """
    s = re.sub(r"^\[[^\]]+\]\s*", "", subject).strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default="data/html/202204/0000.html")
    ap.add_argument("--url", dest="url", default="http://archive.ambermd.org/202204/0000.html")
    ap.add_argument("--out", dest="out_path", default=None)
    args = ap.parse_args()

    html_path = Path(args.in_path)
    if not html_path.exists():
        raise SystemExit(f"Input HTML not found: {html_path}")

    html_bytes = html_path.read_bytes()
    soup = BeautifulSoup(html_bytes, "html.parser")

    # Common fields
    subject = (soup.select_one("div.head h1") or soup.title)
    subject = subject.get_text(strip=True) if subject else None

    mail_div = soup.select_one("div.mail")
    if not mail_div:
        raise SystemExit("Could not find <div class='mail'> in HTML.")

    # Comment-derived fields
    kv = comment_kv_index(soup)
    # Example keys we often find: name, email, subject, isosent, isoreceived, id
    author_name = kv.get("name")
    author_email_raw = kv.get("email")
    message_id_comment = kv.get("id")  # this is like an email Message-Id

    # Fallbacks if comments are missing
    if not author_email_raw:
        a = mail_div.select_one("address.headers #from a[href^='mailto:']")
        if a:
            author_email_raw = a.get_text(strip=True)

    author_email_deobf = deobfuscate_email(author_email_raw) if author_email_raw else None

    # Dates
    # date_raw: the human-readable Date span
    date_span = mail_div.select_one("address.headers #date")
    date_raw = date_span.get_text(strip=True) if date_span else None

    # date_iso: from date_raw parsed via stdlib (keeps original timezone)
    date_iso = None
    date_utc = None
    if date_raw:
        try:
            dt = parsedate_to_datetime(date_raw)  # timezone-aware if present
            date_iso = dt.isoformat()
            date_utc = dt.astimezone(tz=None).astimezone(tz=dt.tzinfo).isoformat()  # no-op, just explicit
            # Proper UTC:
            date_utc = dt.astimezone(tz=None).astimezone(tz=__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            pass

    # If we have 'isosent' (e.g., 20220401091704), it's UTC without timezone info.
    if kv.get("isosent"):
        iso = kv["isosent"]
        # Format to 'YYYY-MM-DDTHH:MM:SSZ'
        if re.match(r"^\d{14}$", iso):
            date_utc = f"{iso[0:4]}-{iso[4:6]}-{iso[6:8]}T{iso[8:10]}:{iso[10:12]}:{iso[12:14]}Z"

    # received_raw (the little stamp at the end of the mail block)
    received_span = mail_div.select_one("span#received")
    received_raw = received_span.get_text(" ", strip=True) if received_span else None

    # Body text
    body_text = text_between_start_and_received(mail_div)

    # Attachments
    attachments = guess_attachments(mail_div, base_url=args.url)

    # Navigation info
    nav = nav_info(soup)

    # Message id string you want in output (your example uses a stable pattern)
    # We'll base it on the URL path: 'amber-YYYYMM-####'
    msg_id = None
    try:
        # http://archive.ambermd.org/202204/0000.html -> amber-202204-0000
        path = urlparse(args.url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 2 and parts[-1].endswith(".html"):
            yyyymm = parts[-2]
            num = parts[-1].split(".")[0]
            msg_id = f"amber-{yyyymm}-{num}"
    except Exception:
        pass

    # Thread id
    thread_id = make_thread_id(subject or "")

    data = {
        "message_id": msg_id,
        "url": args.url,
        "subject": subject,
        "author_name": author_name,
        "author_email_raw": author_email_raw,
        "author_email_deobfuscated": author_email_deobf,
        "date_raw": date_raw,
        "date_iso": date_iso,
        "date_utc": date_utc,
        "received_raw": received_raw,
        "thread_id": thread_id,
        "body_text": body_text,
        "attachments": attachments,
        "nav_links": {
            "this_message": nav.get("this_message"),
            "next_message_title": nav.get("next_message_title"),
            "next_in_thread_title": nav.get("next_in_thread_title"),
            "replies_titles": nav.get("replies_titles") or [],
        },
        # Optional: carry original HTML comment Message-Id if you want it for debugging
        "message_id_raw": message_id_comment,
    }

    # Print to stdout
    print(json.dumps(data, ensure_ascii=False, indent=2))

    # Optionally write to disk
    if args.out_path:
        outp = Path(args.out_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # You can also print a small success notice if you like.


if __name__ == "__main__":
    main()