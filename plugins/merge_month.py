# merge_month.py
import json
import sys
import os
from pathlib import Path
from collections import defaultdict

# ---- CRITICAL FIX: absolute data root ----
DATA_ROOT = Path(os.environ.get("AMBER_DATA_ROOT", "/opt/chromadb/data/data"))

JSON_ROOT = DATA_ROOT / "json"
THREADS_ROOT = DATA_ROOT / "threads"


def load_month_messages(month: str):
    in_dir = JSON_ROOT / month
    by_url = {}
    parent = {}

    files = sorted(in_dir.glob("*.json"))
    print(f"[MERGE] Loading {len(files)} JSON messages from {in_dir}")

    for p in files:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        url = m.get("url")
        if not url:
            continue

        by_url[url] = m

        purl = m.get("in_reply_to_url")
        if purl:
            parent[url] = purl

    return by_url, parent


def merge_month(month: str):
    by_url, parent = load_month_messages(month)
    if not by_url:
        print("[MERGE] No messages found; nothing to merge.")
        return

    root_cache = {}

    def find_root(u: str) -> str:
        if u in root_cache:
            return root_cache[u]

        path = []
        cur = u
        seen = set()

        while True:
            if cur in root_cache:
                r = root_cache[cur]
                break

            p = parent.get(cur)

            # Month-scoped behavior:
            # if parent isn't present in THIS month dataset, stop here.
            if not p or p not in by_url:
                r = cur
                break

            if p in seen:
                r = cur
                break

            seen.add(cur)
            path.append(cur)
            cur = p

        for x in path:
            root_cache[x] = r
        root_cache[u] = r
        return r

    groups = defaultdict(list)
    for u in by_url.keys():
        groups[find_root(u)].append(u)

    threads = []
    for root_url, urls in groups.items():
        root_msg = by_url[root_url]

        thread_id = root_msg.get("date_epoch")
        if thread_id is None:
            thread_id = abs(hash(root_url)) % (10**12)

        messages = []
        for u in urls:
            m = by_url[u]
            messages.append({
                "message_id": m.get("date_epoch"),
                "author": m.get("author") or "",
                "email": m.get("email") or "",
                "date_iso": m.get("date_iso") or "",
                "date_raw": m.get("date_raw") or "",
                "url": m.get("url") or "",
                "body": m.get("body") or "",
            })

        messages.sort(key=lambda x: (x["message_id"] is None, x["message_id"] or 0))

        threads.append({
            "thread_id": int(thread_id) if isinstance(thread_id, int) else thread_id,
            "subject": root_msg.get("subject") or "",
            "month": month,
            "messages": messages,
        })

    THREADS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = THREADS_ROOT / f"threads_{month}.json"
    out_path.write_text(json.dumps(threads, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[MERGE DONE] Wrote {out_path} ({len(threads)} threads)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python merge_month.py YYYYMM")
        raise SystemExit(2)
    merge_month(sys.argv[1])
