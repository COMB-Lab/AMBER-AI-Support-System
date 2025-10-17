#!/usr/bin/env python3
"""Parse a single Amber archive HTML message into JSON.

Usage:
  python scripts/parse_single_email.py --in data/html/202204/0000.html

Writes JSON to data/json/202204/0000.json by default.
"""
from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
from datetime import timezone
from pathlib import Path


def deobfuscate_email(raw: str) -> str:
    raw = raw.strip()
    if "@" in raw:
        return raw
    parts = raw.split('.')
    if len(parts) >= 3:
        user = '.'.join(parts[:-2])
        domain = '.'.join(parts[-2:])
        if user:
            return f"{user}@{domain}"
    # fallback: return original
    return raw


def extract_meta(content: str, name: str) -> str | None:
    m = re.search(rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)["\']', content, flags=re.I)
    if m:
        return html.unescape(m.group(1).strip())
    return None


def extract_comment(content: str, key: str) -> str | None:
    m = re.search(rf'<!--\s*{re.escape(key)}="([^"]+)"\s*-->', content)
    if m:
        return m.group(1).strip()
    return None


def extract_between(start_rx: str, end_rx: str, content: str) -> str | None:
    m = re.search(start_rx + r"(.*?)" + end_rx, content, flags=re.S)
    if m:
        return m.group(1)
    return None


def clean_html_to_text(html_fragment: str) -> str:
    # Normalize line breaks
    fragment = re.sub(r'(?i)<br\s*/?>', '\n', html_fragment)
    # Remove scripts/styles
    fragment = re.sub(r'<(script|style)[\s\S]*?</\1>', '', fragment, flags=re.I)
    # Remove remaining tags
    text = re.sub(r'<[^>]+>', '', fragment)
    # Unescape HTML entities
    text = html.unescape(text)
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def find_attachments(content: str) -> list[dict]:
    attachments = []
    # <img src="att-0000/image.png" alt="image.png" />
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']+)["\']', content, flags=re.I):
        src = m.group(1)
        filename = Path(src).name
        mime, _ = mimetypes.guess_type(filename)
        attachments.append({"filename": filename, "mime": mime or "application/octet-stream"})

    # <a href="att-0000/image.png">image.png</a>
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a>', content, flags=re.I):
        href = m.group(1)
        text = m.group(2).strip()
        if href.startswith('att-') or href.startswith('att-'):
            filename = Path(href).name
            mime, _ = mimetypes.guess_type(filename)
            attachments.append({"filename": filename, "mime": mime or "application/octet-stream"})

    # Deduplicate by filename while preserving order
    seen = set()
    out = []
    for a in attachments:
        if a['filename'] not in seen:
            seen.add(a['filename'])
            out.append(a)
    return out


def extract_nav_links(content: str) -> dict:
    nav = {}
    # Next message
    m = re.search(r'<li>\s*<dfn>Next message</dfn>:\s*<a[^>]+title=["\']([^"\']+)["\']', content)
    if m:
        nav['next_message_title'] = html.unescape(m.group(1))
    # Next in thread
    m = re.search(r'<li>\s*<dfn>Next in thread</dfn>:\s*<a[^>]+title=["\']([^"\']+)["\']', content)
    if m:
        nav['next_in_thread_title'] = html.unescape(m.group(1))
    # Replies (multiple)
    replies = []
    for m in re.finditer(r'<li>\s*<dfn>Reply</dfn>:\s*<a[^>]+title=["\']([^"\']+)["\']', content):
        replies.append(html.unescape(m.group(1)))
    if replies:
        nav['replies_titles'] = replies
    # This message link label
    nav['this_message'] = 'Message body'
    return nav


def parse_file(in_path: Path, url: str | None = None) -> dict:
    content = in_path.read_text(encoding='utf-8', errors='replace')

    # Basic fields
    subject = extract_meta(content, 'Subject') or extract_between(r'<h1[^>]*>', r'</h1>', content) or ''
    subject = subject.strip()

    # author: prefer comment, fallback to meta Author or address block
    author_name = extract_comment(content, 'name') or None
    author_email_raw = extract_comment(content, 'email') or None

    if not author_email_raw:
        # try mailto in the from span
        m = re.search(r'<span[^>]+id=["\']from["\'][^>]*>(.*?)</span>', content, flags=re.S)
        if m:
            s = m.group(1)
            mm = re.search(r'href=["\']mailto:([^"\'?]+)', s)
            if mm:
                author_email_raw = mm.group(1)
            else:
                # maybe plain text
                mm = re.search(r'>([^<]+@[^<]+)<', s)
                if mm:
                    author_email_raw = mm.group(1).strip()

    # If still no author_name, try meta Author
    if not author_name:
        meta_author = extract_meta(content, 'Author')
        if meta_author:
            # meta_author often like 'Name (email)'
            m = re.match(r'([^\(]+)\s*\(([^\)]+)\)', meta_author)
            if m:
                author_name = m.group(1).strip()
                if not author_email_raw:
                    author_email_raw = m.group(2).strip()
            else:
                author_name = meta_author

    author_email_raw = (author_email_raw or '').strip()
    author_email_deobfuscated = deobfuscate_email(author_email_raw) if author_email_raw else ''

    # Date
    date_raw = ''
    m = re.search(r'<span[^>]+id=["\']date["\'][^>]*>\s*<dfn>[^<]+</dfn>:\s*([^<]+)</span>', content, flags=re.I)
    if m:
        date_raw = m.group(1).strip()
    else:
        date_raw = extract_comment(content, 'sent') or ''

    # Convert to ISO and UTC using email.utils if possible
    date_iso = ''
    date_utc = ''
    message_epoch = None
    try:
        from email.utils import parsedate_to_datetime

        if date_raw:
            dt = parsedate_to_datetime(date_raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            date_iso = dt.isoformat()
            date_utc = dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            try:
                # epoch seconds as int (UTC)
                message_epoch = int(dt.astimezone(timezone.utc).timestamp())
            except Exception:
                message_epoch = None
    except Exception:
        pass

    # received
    received_raw = ''
    m = re.search(r'<span[^>]+id=["\']received["\'][^>]*>\s*<dfn>[^<]+</dfn>\s*([^<]+)</span>', content, flags=re.I)
    if m:
        received_raw = m.group(1).strip()
    else:
        received_raw = extract_between(r'<!-- received="', r'" -->', content) or ''

    # thread id: use subject (strip mailing list tags)
    thread_id = re.sub(r'^\[.*?\]\s*', '', subject).strip()

    # Body extraction: try to get content between the start anchor and received span
    body_html = None
    m = re.search(r'<a name=["\']start["\'][^>]*>\s*</a>(.*?)<span[^>]+id=["\']received["\']', content, flags=re.S)
    if m:
        body_html = m.group(1)
    else:
        # fallback: extract whole mail div
        m = re.search(r'<div[^>]+class=["\']mail["\'][^>]*>(.*?)</div>\s*<!-- body="end" -->', content, flags=re.S)
        if m:
            body_html = m.group(1)

    body_text = clean_html_to_text(body_html or '')

    attachments = find_attachments(content)

    nav_links = extract_nav_links(content)

    # message id and url inference
    inferred_msg = None
    m = re.search(r'/([0-9]{6})/([0-9]{4})\.html', str(in_path).replace('\\', '/'))
    if m:
        inferred_msg = f"amber-{m.group(1)}-{m.group(2)}"

    if not url:
        # try to infer from path
        if m:
            url = f"http://archive.ambermd.org/{m.group(1)}/{m.group(2)}.html"
        else:
            url = ''

    # Assign numeric message_id based on epoch when available
    mid = message_epoch if message_epoch is not None else (inferred_msg or '')

    result = {
        "message_id": mid,
        "message_epoch": message_epoch,
        "url": url,
        "subject": subject,
        "author_name": author_name or '',
        "author_email_raw": author_email_raw or '',
        "author_email_deobfuscated": author_email_deobfuscated or '',
        "date_raw": date_raw or '',
        "date_iso": date_iso or '',
        "date_utc": date_utc or '',
        "received_raw": received_raw or '',
        "thread_id": thread_id or '',
        "body_text": body_text or '',
        "attachments": attachments,
        "nav_links": nav_links,
    }

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Parse a single downloaded Amber HTML into JSON')
    parser.add_argument('--in', dest='in_path', type=Path, required=True, help='Input HTML file')
    parser.add_argument('--url', dest='url', default=None, help='Original URL (optional)')
    parser.add_argument('--out', dest='out_path', type=Path, default=None, help='Output JSON file path')
    args = parser.parse_args(argv)

    in_path: Path = args.in_path
    if not in_path.exists():
        print(f"Input file not found: {in_path}")
        raise SystemExit(2)

    # Default output: mirror data/html -> data/json
    if args.out_path:
        out_path = args.out_path
    else:
        parts = in_path.parts
        # find the index of 'data' if present
        try:
            idx = parts.index('data')
            rel = Path(*parts[idx + 1:])
        except ValueError:
            rel = in_path.name
        out_path = Path('data') / 'json' / rel.with_suffix('.json')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    parsed = parse_file(in_path, url=args.url)
    out_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Wrote JSON: {out_path} ({len(out_path.read_bytes())} bytes)")


if __name__ == '__main__':
    main()
