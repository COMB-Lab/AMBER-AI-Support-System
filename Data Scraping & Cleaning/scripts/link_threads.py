#!/usr/bin/env python3
import argparse, json, re
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from datetime import datetime

HTML_ROOT = Path("data/html")
OUT_ROOT = Path("data/json/threads")
OUT_ROOT.mkdir(parents=True, exist_ok=True)

A_MSG_ID = re.compile(r"/(\d{6})/(\d{4})\.html$")  # /YYYYMM/NNNN.html

def msg_id_from_url(u: str) -> tuple[str, str] | None:
    m = A_MSG_ID.search(urlparse(u).path)
    if not m: return None
    return m.group(1), m.group(2)  # yyyymm, nnnn

def normalize_subject(s: str) -> str:
    s = s.strip()
    # remove common prefixes repeatedly: Re:, Fwd:
    while True:
        t = re.sub(r"^(re|fwd|fw)\s*:\s*", "", s, flags=re.I)
        if t == s: break
        s = t
    return re.sub(r"\s+", " ", s)

def extract_nav_and_meta(html: str, fallback_url: str) -> dict:
    """
    Returns:
      {
        'id': 'NNNN', 'yyyymm': 'YYYYMM', 'url': '...',
        'subject': str, 'subject_clean': str,
        'date_iso': 'YYYY-MM-DDTHH:MM:SSZ' (best-effort),
        'in_reply_to': 'NNNN'|None, 'replies': [NNNN...], 'next_in_thread': 'NNNN'|None
      }
    """
    soup = BeautifulSoup(html, "html.parser")

    # URL + ids (from footer nav or fallback_url)
    url = fallback_url
    mm = msg_id_from_url(url)
    if not mm:
        # Try to find a canonical link if present
        link = soup.find("link", rel=lambda v: v and "canonical" in v.lower())
        if link and link.get("href"): 
            url = link["href"]
            mm = msg_id_from_url(url)
    if not mm:
        raise ValueError("Cannot determine YYYYMM/NNNN from URL or page.")
    yyyymm, nnnn = mm

    # Subject
    subj_el = soup.find(string=re.compile(r"\[AMBER\]|\S"))
    # More robust: header “This message: [ Message body ] …” is near top; but
    # most pages also include a <title> with subject.
    subject = soup.title.get_text(strip=True) if soup.title else (subj_el or "").strip()
    subject_clean = normalize_subject(subject)

    # Date (header often has 'Date: Tue, 2 May 2023 19:05:35 +0000')
    date_iso = None
    date_label = soup.find(string=re.compile(r"^\s*Date:\s*", re.I))
    if date_label and date_label.parent:
        raw = re.sub(r"^\s*Date:\s*", "", date_label, flags=re.I).strip()
        # best-effort parse; the archive uses RFC822-ish strings
        try:
            # remove parenthetical timezone names if any
            raw2 = re.sub(r"\(.*?\)$", "", raw).strip()
            dt = datetime.strptime(raw2[:25], "%a, %d %b %Y %H:%M:%S")
            date_iso = dt.isoformat() + "Z"
        except Exception:
            date_iso = None

    # Collect all nav anchors & map by exact text
    anchors = soup.find_all("a", href=True)
    by_text = {}
    for a in anchors:
        label = a.get_text(strip=True)
        href = a["href"].strip()
        by_text.setdefault(label, []).append(href)

    def first_id_for(label: str) -> str | None:
        for href in by_text.get(label, []):
            mmid = msg_id_from_url(href)
            if mmid and mmid[0] == yyyymm:
                return mmid[1]
        return None

    def all_ids_for(label: str) -> list[str]:
        ids = []
        for href in by_text.get(label, []):
            mmid = msg_id_from_url(href)
            if mmid and mmid[0] == yyyymm:
                ids.append(mmid[1])
        # de-dup preserve order
        seen, out = set(), []
        for i in ids:
            if i not in seen:
                seen.add(i); out.append(i)
        return out

    # Primary signals
    in_reply_to = first_id_for("In reply to")
    next_in_thread = first_id_for("Next in thread")
    replies = all_ids_for("Replies")

    # Fallback heuristic: if nothing, infer from subject prefix (last resort)
    if not in_reply_to and subject.lower().startswith(("re:", "fw:", "fwd:")):
        # Guess parent as the nearest previous id (NNNN-1) if it exists in month
        try:
            prev_num = f"{int(nnnn)-1:04d}"
            in_reply_to = prev_num
        except Exception:
            pass

    return {
        "id": nnnn,
        "yyyymm": yyyymm,
        "url": url,
        "subject": subject,
        "subject_clean": subject_clean,
        "date_iso": date_iso,
        "in_reply_to": in_reply_to,
        "replies": replies,
        "next_in_thread": next_in_thread,
    }

def build_threads_for_month(yyyymm: str):
    month_dir = HTML_ROOT / yyyymm
    assert month_dir.is_dir(), f"Missing folder: {month_dir}"

    # 1) parse all messages
    records = {}
    for p in sorted(month_dir.glob("*.html")):
        url_guess = f"http://archive.ambermd.org/{yyyymm}/{p.stem}.html"
        rec = extract_nav_and_meta(p.read_text(encoding="utf-8", errors="ignore"), url_guess)
        records[rec["id"]] = rec

    # 2) build parent/children maps
    children = {rid: [] for rid in records}
    parent = {rid: None for rid in records}
    for rid, r in records.items():
        if r["in_reply_to"] in records:
            parent[rid] = r["in_reply_to"]
            children[r["in_reply_to"]].append(rid)
        # also honor explicit Replies list
        for kid in r["replies"]:
            if kid in records and kid not in children[rid]:
                children[rid].append(kid)
                parent[kid] = parent.get(kid) or rid

    # 3) sort children of each node by date
    def sort_key(msg_id: str):
        di = records[msg_id].get("date_iso") or ""
        return di, msg_id
    for rid in children:
        children[rid].sort(key=sort_key)

    # 4) find roots
    roots = [rid for rid, par in parent.items() if not par]

    # 5) assemble threads (DFS)
    threads = []
    seen = set()
    for root in sorted(roots, key=sort_key):
        order = []
        stack = [root]
        while stack:
            cur = stack.pop(0)
            if cur in seen: 
                continue
            seen.add(cur)
            order.append(cur)
            stack[0:0] = children[cur]  # queue children (BFS-ish)

        threads.append({
            "month": yyyymm,
            "thread_id": f"{yyyymm}-{root}",
            "root_id": root,
            "subject": records[root]["subject_clean"],
            "size": len(order),
            "messages": order
        })

    # 6) write out
    out_path = OUT_ROOT / f"{yyyymm}.threads.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(threads, indent=2), encoding="utf-8")
    return out_path, len(threads)

def main():
    ap = argparse.ArgumentParser(description="Link Amber replies into threads for a given month")
    ap.add_argument("--month", required=True, help="YYYYMM (e.g., 202305)")
    args = ap.parse_args()
    out_path, n = build_threads_for_month(args.month)
    print(f"Wrote {n} threads → {out_path}")

if __name__ == "__main__":
    main()