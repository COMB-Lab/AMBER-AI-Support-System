"""
Merge cross-month AMBER threads.

1) Read two consecutive month folders of thread JSONs (amber_YYYYMM).
2) For each thread in the later month that starts with "Re:", find matching
   root subject in the earlier month and append its messages there.
3) Write the merged threads back into the earlier month folder.

Base path inside container defaults to /opt/airflow/data/CleanData,
configurable via DATA_DIR env var.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# ---------- Config ----------
DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/airflow/data")).resolve()
CLEAN_BASE = DATA_DIR / "CleanData"  
# ----------------------------

def readData(folder: Path) -> List[dict]:
    """Read all thread JSON files from a month folder."""
    all_data: List[dict] = []
    if not folder.is_dir():
        return all_data
    for filename in os.listdir(folder):
        if filename.endswith(".json"):
            with open(folder / filename, "r", encoding="utf-8") as f:
                all_data.append(json.load(f))
    return all_data

def compareData(previousMonth: List[dict], currentMonth: List[dict]) -> None:
    """
    For each 'Re:' subject in currentMonth, find matching root (non-Re:) subject
    in previousMonth and merge messages into the previousMonth thread.
    """
    for curr in currentMonth:
        replySubject = (curr.get("subject") or "").strip()
        if replySubject.lower().startswith("re:"):
            replyCore = replySubject[3:].strip().lower()

            for prev in previousMonth:
                rootSubject = (prev.get("subject") or "").strip()
                if not rootSubject.lower().startswith("re:") and replyCore == rootSubject.lower():
                    # Found a matching root thread in previousMonth
                    existing_ids = {m.get("message_id") for m in prev.get("messages", []) if m.get("message_id") is not None}

                    # Only add non-duplicate messages
                    new_msgs = []
                    for m in curr.get("messages", []):
                        mid = m.get("message_id")
                        if mid not in existing_ids:
                            new_msgs.append(m)

                    # If we're adding at least one message and the first new message lacks in_reply_to, link it
                    if new_msgs:
                        if prev.get("messages") and "in_reply_to" not in (new_msgs[0] or {}):
                            try:
                                new_msgs[0]["in_reply_to"] = prev["messages"][0]["message_id"]
                            except (IndexError, KeyError, TypeError):
                                pass

                        prev.setdefault("messages", []).extend(new_msgs)
                    break  # stop scanning previousMonth threads for this curr

def writeToJSON(folder: Path, threads: List[dict]) -> None:
    """Overwrite all thread JSONs in the given month folder with 'threads'."""
    folder.mkdir(parents=True, exist_ok=True)
    for thread in threads:
        thread_id = thread.get("thread_id", "thread")
        out_path = folder / f"{thread_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(threads)} threads to {folder}")

def _parse_month_folder_name(name: str) -> Optional[Tuple[int, int]]:
    """
    Expect folder name like: amber_YYYYMM
    Return (YYYY, MM) or None if not matching.
    """
    if not name.startswith("amber_") or len(name) != len("amber_YYYYMM"):
        return None
    yyyymm = name.split("_", 1)[1]
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        return None
    year = int(yyyymm[:4])
    month = int(yyyymm[4:])
    if 1 <= month <= 12:
        return (year, month)
    return None

def _month_folders_in_chronological_order(base: Path) -> List[Path]:
    """
    Find all AMBER<YEAR>/amber_YYYYMM month folders under CLEAN_BASE,
    and return them sorted chronologically.
    """
    results: List[Tuple[int,int,Path]] = []
    if not base.is_dir():
        return []
    for year_dir in sorted(base.glob("AMBER*")):
        if not year_dir.is_dir():
            continue
        for month_dir in year_dir.glob("amber_*"):
            if month_dir.is_dir():
                parsed = _parse_month_folder_name(month_dir.name)
                if parsed:
                    y, m = parsed
                    results.append((y, m, month_dir))
    # sort by year, then month
    results.sort(key=lambda t: (t[0], t[1]))
    return [p for _, _, p in results]

def main():
    base = CLEAN_BASE
    if not base.exists():
        print(f"[WARN] Clean base not found: {base}")
        return

    month_folders = _month_folders_in_chronological_order(base)
    if len(month_folders) < 2:
        print("[INFO] Not enough month folders to merge.")
        return

    # Iterate consecutive pairs (prev, curr)
    for i in range(len(month_folders) - 1):
        prev_folder = month_folders[i]
        curr_folder = month_folders[i + 1]

        print(f"\nMerging replies from {curr_folder} -> {prev_folder}")
        previousMonth = readData(prev_folder)
        currentMonth = readData(curr_folder)

        if not previousMonth:
            print(f"[WARN] No threads found in previous month: {prev_folder}")
        if not currentMonth:
            print(f"[WARN] No threads found in current month: {curr_folder}")

        compareData(previousMonth, currentMonth)
        writeToJSON(prev_folder, previousMonth)

    print("\n[DONE] Cross-month merge complete.")

if __name__ == "__main__":
    main()
