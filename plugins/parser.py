import pathlib
import json
import re
from bs4 import BeautifulSoup
from datetime import timezone
from email.utils import parsedate_to_datetime

BASE_URL = "http://archive.ambermd.org"

def _infer_url_from_path(input_path: pathlib.Path) -> str:
    # expects .../data/html/200503/0000.html
    month_dir = input_path.parent.name
    filename = input_path.name
    return f"{BASE_URL}/{month_dir}/{filename}"

def _abs_url(current_url: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    # hypermail uses relative links like "0015.html"
    base = current_url.rsplit("/", 1)[0] + "/"
    return base + href.lstrip("./")

def _get_email_from_from_span(author_tag) -> str:
    # <span id="from"> ... <a href="mailto:someone?...">someone</a> ...
    a = author_tag.find("a", href=True)
    if not a:
        return ""
    href = a.get("href", "")
    if href.startswith("mailto:"):
        return href[len("mailto:"):].split("?", 1)[0]
    # fallback: visible text
    return a.get_text(strip=True)

def parse(input_path: pathlib.Path, output_path: pathlib.Path):
    html = input_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    url = _infer_url_from_path(input_path)

    data = {
        "schema_version": 1,
        "doc_type": "message",

        "url": url,
        "in_reply_to_url": None,

        "subject": None,
        "author": None,
        "email": None,

        "date_raw": None,
        "date_iso": None,      # UTC ISO
        "date_epoch": None,    # int epoch seconds

        "body": None,
    }

    # Subject (Hypermail uses <h1>AMBER: ...</h1>)
    h1 = soup.find("h1")
    if h1:
        data["subject"] = h1.get_text(strip=True)

    # Author / email
    from_span = soup.find("span", id="from")
    if from_span:
        # author name isn't always present; use text before '<' if it exists
        from_text = from_span.get_text(" ", strip=True)
        # e.g. "From: <tomjas.poczta.onet.pl>"
        data["author"] = from_text.replace("From", "").replace(":", "").strip() or None
        data["email"] = _get_email_from_from_span(from_span) or None

    # Date
    date_span = soup.find("span", id="date")
    if date_span:
        # e.g. "Date: Tue, 01 Mar 2005 08:18:55 +0100"
        raw = date_span.get_text(" ", strip=True)
        raw = re.sub(r"^\s*Date\s*:\s*", "", raw, flags=re.I).strip()
        data["date_raw"] = raw

        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_utc = dt.astimezone(timezone.utc)
            data["date_iso"] = dt_utc.isoformat()
            data["date_epoch"] = int(dt_utc.timestamp())
        except Exception:
            # keep raw, leave iso/epoch None
            pass

    # Body: everything after <a name="start"...> inside div.mail
    mail_div = soup.find("div", class_="mail")
    if mail_div:
        start = mail_div.find("a", {"name": "start"})
        if start:
            raw_body = " ".join(start.find_all_next(string=True)).strip()
        else:
            raw_body = mail_div.get_text("\n", strip=True)

        # cut off mailing list footer line if present
        raw_body = raw_body.split("The AMBER Mail Reflector", 1)[0]
        raw_body = raw_body.split("_______________________________________________", 1)[0]
        data["body"] = re.sub(r"\s+\n", "\n", raw_body).strip()

    # Parent link (message THIS message replies to)
    # In Hypermail, footer has:
    # <a title="Message sent in reply to this message" href="....">
    foot = soup.find("div", class_="foot")
    if foot:
        parent_tag = foot.select_one('a[title^="Message sent in reply to this message"]')
        if parent_tag and parent_tag.get("href"):
            data["in_reply_to_url"] = _abs_url(url, parent_tag["href"])

    # write JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
