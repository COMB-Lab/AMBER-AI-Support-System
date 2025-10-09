#!/usr/bin/env python3
"""
Link AMBER per-message JSONs into per-thread JSON files using a graph approach.

Input  (from parse stage):
  <json_in>/YYYYMM/NNNN.json  (contains url, subject, date_*, nav_links, body_text, author_name)

Output (thread files):
  <json_out>/YYYY/MM/<thread_id>.json
    where thread_id = epoch(time of root (or adopted parent) message in UTC)

How threads are built:
  - Build an undirected graph over month messages (nodes = NNNN).
  - Add edges from real thread signals when available:
      * nav_links.in_reply_to_link
      * nav_links.replies_links (list)
      * nav_links.next_in_thread_link
  - Fallback: connect consecutive messages with the same normalized subject
    in chronological order (with a max time gap).
  - Connected components = threads.
  - Root selection prefers a non-reply subject; otherwise earliest by epoch.
  - If a component is reply-only (or a single reply), search previous months
    for a parent with the same normalized subject and adopt its epoch as thread_id.
  - Write threads under the year/month of the chosen thread_id and safely merge
    when appending across months.

CLI:
  --json-in   (root of per-message JSON, e.g., data/json)
  --json-out  (root to write thread files, e.g., data/json)
  --since/--until  YYYY-MM inclusive bounds
  --cleanup   delete <json_in>/YYYYMM/*.json after successful writing
"""

import argparse
import json
import re
import sys
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import timezone, datetime

A_MSG_DIR  = re.compile(r"^\d{6}$")       # YYYYMM
A_MSG_FILE = re.compile(r"^\d{4}\.json$") # 0000.json

# --- Helpers for reply detection and month math ---
REPLY_PREFIX = re.compile(r"^\s*re\s*:\s*", flags=re.I)

def is_reply_subject(s: str | None) -> bool:
    return bool(REPLY_PREFIX.match(s or ""))

def prev_month_str(yyyymm: str, n_back: int = 1) -> str | None:
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    m -= n_back
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}{m:02d}" if y > 0 else None

def ym_to_int(ym: str | None) -> int | None:
    if not ym:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})", ym)
    return int(m.group(1)) * 100 + int(m.group(2)) if m else None

def iter_months(in_root: Path, since: str | None, until: str | None):
    s = ym_to_int(since) or 0
    u = ym_to_int(until) or 999999
    for d in sorted(in_root.glob("*")):
        if d.is_dir() and A_MSG_DIR.match(d.name):
            ym = int(d.name)
            if s <= ym <= u:
                yield d.name

def norm_subject(s: str | None) -> str:
    if not s:
        return ""
    # strip [AMBER] once
    s = re.sub(r"^\s*\[AMBER\]\s*", "", s, flags=re.I)
    # strip many leading reply/fwd prefixes
    while True:
        t = re.sub(r"^(re|fwd?|fw)\s*:\s*", "", s, flags=re.I)
        if t == s:
            break
        s = t
    return re.sub(r"\s+", " ", s).strip().lower()

def epoch_from_record(rec: dict) -> int | None:
    # Prefer date_raw; fall back to date_iso/date_utc
    dt = None
    for k in ("date_raw", "date_iso", "date_utc"):
        v = rec.get(k)
        if not v:
            continue
        try:
            dt = parsedate_to_datetime(v)
            break
        except Exception:
            continue
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())

def id_from_url(u: str | None):
    if not u:
        return None
    m = re.search(r"/(\d{6})/(\d{4})\.html$", u)
    if not m:
        return None
    return m.group(1), m.group(2)  # yyyymm, nnnn

def load_month_records(in_root: Path, yyyymm: str) -> dict:
    """Return { 'NNNN': rec } with helper fields added: _epoch, _subj_norm."""
    src = in_root / yyyymm
    out = {}
    for p in sorted(src.glob("*.json")):
        if not A_MSG_FILE.match(p.name):
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        mid = rec.get("id_in_month") or p.stem  # '0000'
        rec["_epoch"] = epoch_from_record(rec) or 0
        rec["_subj_norm"] = norm_subject(rec.get("subject"))
        out[mid] = rec
    return out

def build_graph(records: dict, yyyymm: str):
    """Return (adj, parent_hint)"""
    adj = {rid: set() for rid in records}
    parent_hint = {rid: None for rid in records}

    def link(a, b):
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)

    for rid, rec in records.items():
        nav = rec.get("nav_links") or {}

        # 1) in_reply_to_link (most reliable)
        ymid = id_from_url(nav.get("in_reply_to_link"))
        if ymid and ymid[0] == yyyymm and ymid[1] in records:
            parent_hint[rid] = ymid[1]
            link(rid, ymid[1])

        # 2) replies_links (if parser provided)
        for href in nav.get("replies_links", []) or []:
            ymid = id_from_url(href)
            if ymid and ymid[0] == yyyymm and ymid[1] in records:
                link(rid, ymid[1])

        # 3) next_in_thread_link (if parser provided)
        nxt = nav.get("next_in_thread_link")
        ymid = id_from_url(nxt) if nxt else None
        if ymid and ymid[0] == yyyymm and ymid[1] in records:
            link(rid, ymid[1])

    # 4) Fallback: chain same-subject neighbors by time (robust when links are missing)
    #    but avoid merging threads that share a subject weeks apart
    by_subj = {}
    for rid, rec in records.items():
        by_subj.setdefault(rec["_subj_norm"], []).append(rid)
    MAX_GAP_SECS = 14 * 24 * 3600  # 14 days; tune as needed
    for subj, ids in by_subj.items():
        if not subj:
            continue
        ids.sort(key=lambda m: (records[m]["_epoch"], m))
        for a, b in zip(ids, ids[1:]):
            if abs(records[b]["_epoch"] - records[a]["_epoch"]) <= MAX_GAP_SECS:
                link(a, b)

    return adj, parent_hint

def connected_components(adj: dict, records: dict):
    seen = set()
    comps = []
    def epoch(mid): return records[mid]["_epoch"]
    for rid in sorted(adj.keys(), key=lambda m: (epoch(m), m)):
        if rid in seen:
            continue
        comp = []
        stack = [rid]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(n for n in adj[cur] if n not in seen)
        comps.append(comp)
    return comps

def strip_amber_tag(s: str) -> str:
    """Remove leading [AMBER] or [amber] tag from subject lines."""
    if not s:
        return ""
    return re.sub(r"^\s*\[amber\]\s*", "", s, flags=re.I).strip()

def lookup_previous_parent_epoch(in_root: Path, yyyymm: str, subj_norm: str, max_back: int = 3) -> int | None:
    """
    Scan up to `max_back` previous months for any message whose normalized subject equals `subj_norm`.
    Prefer a non-reply; otherwise take the earliest (by epoch). Returns the epoch or None.
    """
    best_non_reply = None
    best_any = None

    def consider(rec):
        nonlocal best_non_reply, best_any
        ep = rec.get("_epoch") or 0
        if not ep:
            return
        best_any = ep if best_any is None or ep < best_any else best_any
        if not is_reply_subject(rec.get("subject")):
            best_non_reply = ep if best_non_reply is None or ep < best_non_reply else best_non_reply

    for k in range(1, max_back + 1):
        prev = prev_month_str(yyyymm, k)
        if not prev:
            break
        month_dir = in_root / prev
        if not month_dir.exists():
            continue
        for p in month_dir.glob("*.json"):
            if not A_MSG_FILE.match(p.name):
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            rec["_epoch"] = epoch_from_record(rec) or 0
            rec["_subj_norm"] = norm_subject(rec.get("subject"))
            if rec["_subj_norm"] == subj_norm:
                consider(rec)

    return best_non_reply if best_non_reply is not None else best_any

def write_threads_for_month(in_root: Path, out_root: Path, yyyymm: str) -> int:
    records = load_month_records(in_root, yyyymm)
    if not records:
        return 0

    adj, parent_hint = build_graph(records, yyyymm)
    comps = connected_components(adj, records)

    def epoch(mid): return records[mid]["_epoch"]

    written = 0
    for comp in comps:
        comp_set = set(comp)

        # Choose root: prefer a non-reply among candidates with no parent inside the component
        roots = [m for m in comp if not (parent_hint.get(m) in comp_set)]
        def _non_reply(mid: str) -> bool:
            return not is_reply_subject(records[mid].get("subject"))
        root_candidates = roots if roots else comp
        non_reply_candidates = [m for m in root_candidates if _non_reply(m)]
        root = min(non_reply_candidates, key=epoch) if non_reply_candidates else min(root_candidates, key=epoch)

        # If component is reply-only (or single reply), try to adopt a parent from previous months
        comp_has_non_reply = any(_non_reply(m) for m in comp)
        adopt_parent_epoch = None
        if not comp_has_non_reply:
            earliest = min(comp, key=epoch)
            subj_norm = records[earliest]["_subj_norm"]
            if subj_norm:
                adopt_parent_epoch = lookup_previous_parent_epoch(in_root, yyyymm, subj_norm, max_back=3)

        # Final thread_id: prefer adopted parent if found
        thread_id = adopt_parent_epoch or epoch(root)
        if not thread_id:
            # skip if no epoch
            continue

        # Build messages, setting in_reply_to for non-root messages
        ordered = sorted(comp, key=epoch)
        msgs_out = []
        for mid in ordered:
            r = records[mid]
            me = r["_epoch"]
            if not me:
                continue
            m = {
                "message_id": me,
                "author": r.get("author_name"),
                "date_raw": r.get("date_raw") or r.get("date_iso") or r.get("date_utc"),
                "body": r.get("body_text"),
                "url": r.get("url"),
            }
            if mid != root:
                m["in_reply_to"] = thread_id
            msgs_out.append(m)

        # Subject comes from the chosen root's original subject, with [AMBER] stripped if present
        orig_subject = records[root].get("subject") or ""
        cleaned_subject = strip_amber_tag(orig_subject)
        new_obj = {
            "thread_id": thread_id,
            "subject": cleaned_subject if cleaned_subject else orig_subject,
            "messages": msgs_out,
        }
        if not new_obj["subject"]:
            new_obj["subject"] = records[root].get("subject") or ""

        # Place thread file under the month of the chosen thread_id
        dt = datetime.fromtimestamp(thread_id, timezone.utc)
        out_dir = out_root / f"{dt.year:04d}" / f"{dt.month:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{thread_id}.json"

        # Safe merge if file already exists (e.g., cross-month append)
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing.get("messages"), list):
                    seen = {m.get("message_id") for m in existing["messages"]}
                    merged = existing["messages"] + [m for m in new_obj["messages"] if m.get("message_id") not in seen]
                    merged.sort(key=lambda m: m.get("message_id", 0))
                    existing["messages"] = merged
                    if not existing.get("subject"):
                        existing["subject"] = new_obj["subject"]
                    new_obj = existing
            except Exception:
                # If merge fails, fall back to writing new_obj fresh
                pass

        out_path.write_text(json.dumps(new_obj, indent=2, ensure_ascii=False), encoding="utf-8")
        written += 1

    return written

def cleanup_month(in_root: Path, yyyymm: str) -> int:
    month_dir = in_root / yyyymm
    removed = 0
    for p in month_dir.glob("*.json"):
        try:
            p.unlink()
            removed += 1
        except Exception:
            pass
    try:
        if month_dir.exists() and not any(month_dir.iterdir()):
            month_dir.rmdir()
    except Exception:
        pass
    return removed

def main():
    ap = argparse.ArgumentParser(description="Write thread JSONs into json/YYYY/MM/<thread_id>.json using graph linking.")
    ap.add_argument("--json-in",  required=True, help="Root of per-message JSON (e.g., data/json)")
    ap.add_argument("--json-out", required=True, help="Root to write thread files (e.g., data/json)")
    ap.add_argument("--since", help="YYYY-MM inclusive start")
    ap.add_argument("--until", help="YYYY-MM inclusive end")
    ap.add_argument("--cleanup", action="store_true", help="Delete per-message JSON after writing threads")
    args = ap.parse_args()

    in_root  = Path(args.json_in)
    out_root = Path(args.json_out)

    months = list(iter_months(in_root, args.since, args.until))
    if not months:
        print("No per-message JSON months found. Run parse stage first.", file=sys.stderr)
        sys.exit(1)

    for yyyymm in months:
        n = write_threads_for_month(in_root, out_root, yyyymm)
        print(f"==> {yyyymm} wrote {n} thread file(s) under {out_root}")
        if args.cleanup and n > 0:
            removed = cleanup_month(in_root, yyyymm)
            print(f"==> {yyyymm} cleanup removed {removed} per-message JSONs")

if __name__ == "__main__":
    main()