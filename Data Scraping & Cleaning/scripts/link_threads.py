#!/usr/bin/env python3
"""
Build one JSON per thread into data/json/<YYYYMM>_thread_<epoch>.json
Optionally --cleanup removes data/json/YYYYMM/*.json (per-message) after success.
"""

import argparse, json, re, sys
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import timezone

DATA_ROOT = Path(__file__).resolve().parents[1] / "data"
JSON_IN_DEFAULT = DATA_ROOT / "json"           # per-message input
JSON_OUT_DEFAULT = DATA_ROOT / "json"          # flat thread files here

A_MSG_DIR  = re.compile(r"^\d{6}$")            # YYYYMM
A_MSG_FILE = re.compile(r"^\d{4}\.json$")      # 0000.json

def ym_to_int(ym: str | None) -> int | None:
    if not ym: return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", ym)
    return int(m.group(1))*100 + int(m.group(2)) if m else None

def iter_months(in_dir: Path, since: str | None, until: str | None):
    s = ym_to_int(since) or 0
    u = ym_to_int(until) or 999999
    for d in sorted(in_dir.glob("*")):
        if d.is_dir() and A_MSG_DIR.match(d.name):
            ym = int(d.name)
            if s <= ym <= u:
                yield d.name

def epoch_from_record(rec: dict) -> int | None:
    dr = rec.get("date_raw"); dt = None
    if dr:
        try: dt = parsedate_to_datetime(dr)
        except Exception: dt = None
    if not dt:
        for k in ("date_iso","date_utc"):
            v = rec.get(k)
            if not v: continue
            try:
                dt = parsedate_to_datetime(v); break
            except Exception: pass
    if not dt: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    else: dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())

def id_from_url(u: str | None):
    if not u: return None
    m = re.search(r"/(\d{6})/(\d{4})\.html$", u)
    return (m.group(1), m.group(2)) if m else None

def norm_subject(s: str | None) -> str:
    if not s: return ""
    s = re.sub(r"^\s*\[AMBER\]\s*", "", s, flags=re.I)
    while True:
        t = re.sub(r"^(re|fwd?|fw)\s*:\s*", "", s, flags=re.I)
        if t == s: break
        s = t
    return re.sub(r"\s+", " ", s).strip()

def build_threads_for_month(in_dir: Path, out_dir: Path, yyyymm: str) -> int:
    src = in_dir / yyyymm

    # 1) load records
    records = {}
    for p in sorted(src.glob("*.json")):
        if not A_MSG_FILE.match(p.name): continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        mid = rec.get("id_in_month") or p.stem
        records[mid] = rec
    if not records: return 0

    # 2) parent/children (same-month only)
    children = {rid: [] for rid in records}
    parent   = {rid: None for rid in records}
    for rid, rec in records.items():
        nav = rec.get("nav_links") or {}
        ymid = id_from_url(nav.get("in_reply_to_link"))
        if ymid and ymid[0] == yyyymm and ymid[1] in records:
            parent[rid] = ymid[1]
            if rid not in children[ymid[1]]: children[ymid[1]].append(rid)
        for link in nav.get("replies_links", []):
            ymid = id_from_url(link)
            if not ymid or ymid[0] != yyyymm: continue
            kid = ymid[1]
            if kid in records and rid not in children or kid not in children[rid]:
                children[rid].append(kid); parent[kid] = parent.get(kid) or rid
        if not parent[rid]:
            subj = (rec.get("subject") or "").lower()
            if subj.startswith(("re:","fwd:","fw:")):
                try:
                    prev = f"{int(rid)-1:04d}"
                    if prev in records and not parent[prev]:
                        parent[rid] = prev
                        if rid not in children[prev]: children[prev].append(rid)
                except Exception: pass

    # 3) sort children by time
    def sort_key(mid: str):
        return (epoch_from_record(records[mid]) or 0, mid)
    for rid in children:
        children[rid].sort(key=sort_key)

    # 4) roots
    roots = [rid for rid, par in parent.items() if not par]
    roots.sort(key=sort_key)

    # 5) write one file per thread into flat json dir
    written = 0
    for root in roots:
        order, q, seen = [], [root], set()
        while q:
            cur = q.pop(0)
            if cur in seen: continue
            seen.add(cur); order.append(cur)
            q[0:0] = children[cur]

        root_rec = records[root]
        root_epoch = epoch_from_record(root_rec)
        if root_epoch is None: continue

        thread_id = root_epoch
        subj = norm_subject(root_rec.get("subject"))

        msgs = []
        for mid in order:
            r = records[mid]
            me = epoch_from_record(r)
            if me is None: continue
            m = {
                "message_id": me,
                "author": r.get("author_name"),
                "date_raw": r.get("date_raw") or r.get("date_iso") or r.get("date_utc"),
                "body": r.get("body_text"),
                "url": r.get("url"),
            }
            if mid != root: m["in_reply_to"] = thread_id
            msgs.append(m)
        msgs.sort(key=lambda m: m["message_id"])

        outp = out_dir / f"{yyyymm}_thread_{thread_id}.json"
        outp.write_text(json.dumps({
            "thread_id": thread_id,
            "subject": subj or (root_rec.get("subject") or ""),
            "messages": msgs,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        written += 1
    return written

def cleanup_month(in_dir: Path, yyyymm: str) -> int:
    month_dir = in_dir / yyyymm
    removed = 0
    for p in month_dir.glob("*.json"):
        try: p.unlink(); removed += 1
        except Exception: pass
    try:
        if not any(month_dir.iterdir()): month_dir.rmdir()
    except Exception: pass
    return removed

def main():
    ap = argparse.ArgumentParser(description="Write flat thread JSONs into data/json/*.json")
    ap.add_argument("--json-in",  default=str(JSON_IN_DEFAULT))
    ap.add_argument("--json-out", default=str(JSON_OUT_DEFAULT))
    ap.add_argument("--since"); ap.add_argument("--until")
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()

    in_dir  = Path(args.json_in)
    out_dir = Path(args.json_out); out_dir.mkdir(parents=True, exist_ok=True)

    months = list(iter_months(in_dir, args.since, args.until))
    if not months:
        print("No per-message JSON months found. Run parse stage first.", file=sys.stderr)
        sys.exit(1)

    for yyyymm in months:
        n = build_threads_for_month(in_dir, out_dir, yyyymm)
        print(f"==> {yyyymm} wrote {n} thread files into {out_dir}")
        if args.cleanup and n > 0:
            removed = cleanup_month(in_dir, yyyymm)
            print(f"==> {yyyymm} cleanup removed {removed} per-message JSONs")

if __name__ == "__main__":
    main()