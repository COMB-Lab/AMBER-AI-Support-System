#!/usr/bin/env python3
"""
Batch-parse AMBER HTML emails into normalized JSON files.

Inputs (by month):
  data/html/YYYYMM/NNNN.html

Outputs:
  data/json/YYYYMM/NNNN.json
"""

import argparse, json, re, sys
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from email.utils import parsedate_to_datetime
from datetime import timezone
from urllib.parse import urljoin

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
HTML_DIR_DEFAULT = DATA_ROOT / "html"
JSON_DIR_DEFAULT = DATA_ROOT / "json"

A_MSG_ID = re.compile(r"^(\d{4})(\d{2})$")
A_HTML = re.compile(r"^\d{4}\.html$")  # 0000.html

def ym_to_int(ym: str | None) -> int | None:
    if not ym: return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", ym)
    return int(m.group(1))*100 + int(m.group(2)) if m else None

def iter_months(in_dir: Path, since: str | None, until: str | None):
    s = ym_to_int(since) or 0
    u = ym_to_int(until) or 999999
    for d in sorted(in_dir.glob("*")):
        if not d.is_dir(): continue
        if not A_MSG_ID.match(d.name): continue
        ym = int(d.name)
        if ym < s or ym > u: continue
        yield d.name

def deob_email(raw: str | None) -> str | None:
    if not raw: return None
    return raw if "@" in raw else raw.replace(".", "@", 1)

def normalize_subject(s: str | None) -> str | None:
    if not s: return None
    s = re.sub(r"^\s*\[AMBER\]\s*", "", s, flags=re.I)
    # repeatedly strip Re/Fwd prefixes
    while True:
        t = re.sub(r"^(re|fwd?|fw)\s*:\s*", "", s, flags=re.I)
        if t == s: break
        s = t
    return re.sub(r"\s+", " ", s).strip().strip('"')

def extract_body_text(soup: BeautifulSoup, sent_raw: str | None) -> str | None:
    mail_div = soup.select_one("div.mail")
    if not mail_div:
        return None
    text = mail_div.get_text("\n", strip=True)
    body = text
    if sent_raw and sent_raw in text:
        # if the date header appears in the visible text, split after it
        _, after = text.split(sent_raw, 1)
        body = after.strip()
    for marker in ["_______________________________________________", "Received on"]:
        if marker in body:
            body = body.split(marker, 1)[0].strip()
    return body

def extract_attachments(soup: BeautifulSoup) -> list:
    out = []
    for a in soup.select('div.mail a[href]'):
        href = a.get('href', '')
        if 'att-' in href:
            filename = href.split('/')[-1]
            mime = None
            ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
            if ext == 'png': mime = 'image/png'
            elif ext in ('jpg','jpeg'): mime = 'image/jpeg'
            elif ext == 'gif': mime = 'image/gif'
            out.append({"filename": filename, "mime": mime})
    return out

def extract_nav_links(soup: BeautifulSoup, base_url: str) -> dict:
    from urllib.parse import urljoin as _join
    by_text = {}
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        href = a["href"].strip()
        by_text.setdefault(label, []).append(_join(base_url, href))

    def first_for(label: str) -> str | None:
        for u in by_text.get(label, []):
            return u
        return None

    def list_for(label: str) -> list[str]:
        return list(dict.fromkeys(by_text.get(label, [])))

    return {
        "this_message": first_for("This message"),
        "next_message_title": None,   # titles vary; not needed for linking from JSON
        "next_in_thread_title": None,
        "replies_titles": [],
        "in_reply_to_title": None,
        "in_reply_to_link": first_for("In reply to"),
        "replies_links": list_for("Replies"),
        "next_in_thread_link": first_for("Next in thread"),
    }

def parse_html_to_record(yyyymm: str, html_path: Path, archive_root="http://archive.ambermd.org/") -> dict:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    url = urljoin(archive_root, f"{yyyymm}/{html_path.stem}.html")

    # metadata often present in HTML comments: subject, name, email, sent, received
    meta = {}
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        txt = (c or "").strip()
        if "=" in txt:
            k, v = txt.split("=", 1)
            meta[k.strip().lower()] = v.strip().strip('"')

    subject = meta.get("subject") or (soup.title.get_text(strip=True) if soup.title else None)
    author_name = meta.get("name")
    author_email_raw = meta.get("email")
    author_email_deobfuscated = deob_email(author_email_raw)

    date_raw = meta.get("sent")
    date_iso = None
    date_utc = None
    if date_raw:
        try:
            dt = parsedate_to_datetime(date_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            date_iso = dt.isoformat()
            date_utc = dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        except Exception:
            pass

    received_raw = None
    if meta.get("received"):
        try:
            dt_r = parsedate_to_datetime(meta["received"])
            if dt_r.tzinfo is None:
                dt_r = dt_r.replace(tzinfo=timezone.utc)
            received_raw = "Received on " + dt_r.strftime("%a %b %d %Y - %H:%M:%S %Z")
        except Exception:
            received_raw = f"Received on {meta['received']}"

    thread_id = normalize_subject(subject)
    body_text = extract_body_text(soup, date_raw)
    attachments = extract_attachments(soup)
    nav_links = extract_nav_links(soup, url)

    return {
        "message_id": f"amber-{yyyymm}-{html_path.stem}",
        "url": url,
        "subject": subject,
        "author_name": author_name,
        "author_email_raw": author_email_raw,
        "author_email_deobfuscated": author_email_deobfuscated,
        "date_raw": date_raw,
        "date_iso": date_iso,
        "date_utc": date_utc,
        "received_raw": received_raw,
        "thread_id": thread_id,
        "body_text": body_text,
        "attachments": attachments,
        "nav_links": nav_links,
        "yyyymm": yyyymm,
        "id_in_month": html_path.stem,
    }

def main():
    ap = argparse.ArgumentParser(description="Parse AMBER HTML files to per-message JSON.")
    ap.add_argument("--in-dir", default=str(HTML_DIR_DEFAULT))
    ap.add_argument("--out-dir", default=str(JSON_DIR_DEFAULT))
    ap.add_argument("--since", help="YYYY-MM inclusive start")
    ap.add_argument("--until", help="YYYY-MM inclusive end")
    ap.add_argument("--limit", type=int, help="Max messages per month")
    ap.add_argument("--force", action="store_true", help="Overwrite existing JSON")
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    months = list(iter_months(in_dir, args.since, args.until))
    if not months:
        print("No input months found. Check --in-dir and run crawler/fetch first.", file=sys.stderr)
        sys.exit(1)

    for yyyymm in months:
        src = in_dir / yyyymm
        dst = out_dir / yyyymm
        dst.mkdir(parents=True, exist_ok=True)
        html_files = sorted([p for p in src.glob("*.html") if A_HTML.match(p.name)])
        if args.limit is not None:
            html_files = html_files[: max(0, args.limit)]

        wrote = skipped = 0
        for p in html_files:
            outp = dst / (p.stem + ".json")
            if outp.exists() and not args.force:
                skipped += 1; continue
            rec = parse_html_to_record(yyyymm, p)
            outp.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
            wrote += 1
        print(f"==> {yyyymm} parsed={wrote} skipped={skipped} -> {dst}")

if __name__ == "__main__":
    main()