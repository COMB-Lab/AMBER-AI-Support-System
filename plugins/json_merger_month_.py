# json_merger_month.py
import json
import sys
from pathlib import Path
from collections import defaultdict

PRINT_EVERY = 5000



def load_messages(input_dir: Path):
    by_url = {}
    parent_map = {}

    files = list(input_dir.rglob("*.json"))
    print(f"Loading {len(files)} message JSON files from {input_dir}...")

    for i, p in enumerate(files, start=1):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        url = data.get("url")
        if not url:
            continue

        by_url[url] = data

        parent = data.get("in_reply_to_url")
        if parent:
            parent_map[url] = parent

        if i % PRINT_EVERY == 0:
            print(f"Loaded {i}/{len(files)} | kept={len(by_url)} | parents={len(parent_map)}")

    print(f"Done loading. kept={len(by_url)} messages, parents={len(parent_map)}")
    return by_url, parent_map

def build_root_cache(by_url, parent_map):
    root_cache = {}

    def find_root(url):
        if url in root_cache:
            return root_cache[url]

        path = []
        cur = url
        seen = set()

        while True:
            if cur in root_cache:
                root = root_cache[cur]
                break

            p = parent_map.get(cur)
            # IMPORTANT: since we're month-scoped, if parent isn't in by_url,
            # we treat this message as a root (break cross-month threads).
            if not p or p not in by_url:
                root = cur
                break

            if p in seen:
                root = cur
                break

            seen.add(cur)
            path.append(cur)
            cur = p

        for x in path:
            root_cache[x] = root
        root_cache[url] = root
        return root

    urls = list(by_url.keys())
    print(f"Computing roots for {len(urls)} messages...")
    for i, u in enumerate(urls, start=1):
        find_root(u)
        if i % PRINT_EVERY == 0:
            print(f"Roots: {i}/{len(urls)}")

    print("Done computing roots.")
    return root_cache

def merge_month(month: str):
    input_dir = Path("data/json") / month
    output_dir = Path("data/threads")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"threads_{month}.json"

    by_url, parent_map = load_messages(input_dir)
    if not by_url:
        print(f"No messages found in {input_dir}")
        return

    root_cache = build_root_cache(by_url, parent_map)

    groups = defaultdict(list)
    for u, root in root_cache.items():
        groups[root].append(u)

    print(f"Built {len(groups)} month-threads. Building output list...")

    all_threads = []
    for i, (root_url, urls) in enumerate(groups.items(), start=1):
        root_msg = by_url[root_url]

        thread_id = root_msg.get("date_epoch")
        if thread_id is None:
            thread_id = abs(hash(root_url)) % (10**12)

        msgs = []
        for u in urls:
            m = by_url[u]
            msgs.append({
                "message_id": m.get("date_epoch"),
                "author": m.get("author") or "",
                "email": m.get("email") or "",
                "date_iso": m.get("date_iso") or "",
                "date_raw": m.get("date_raw") or "",
                "url": m.get("url") or "",
                "body": m.get("body") or "",
            })

        msgs.sort(key=lambda x: (x["message_id"] is None, x["message_id"] or 0))

        if isinstance(thread_id, int):
            for mm in msgs:
                if mm.get("message_id") != thread_id:
                    mm["in_reply_to"] = thread_id

        thread = {
            "thread_id": int(thread_id) if isinstance(thread_id, int) else thread_id,
            "subject": root_msg.get("subject") or "",
            "month": month,              # handy for Chroma partitioning
            "messages": msgs
        }
        all_threads.append(thread)

        if i % 1000 == 0:
            print(f"Built {i}/{len(groups)} threads...")

    output_file.write_text(json.dumps(all_threads, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_file}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python json_merger_month.py YYYYMM")
        raise SystemExit(2)
    merge_month(sys.argv[1])
