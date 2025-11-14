import json
import os
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import timezone
from typing import Optional, Dict, List

# ===== where data lives inside the container =====
DATA_DIR = Path(os.environ.get("DATA_DIR", "/opt/airflow/data")).resolve()
RAW_BASE   = DATA_DIR / "RawData"    # input: .../RawData/<YEAR>_Data/*.json
CLEAN_BASE = DATA_DIR / "CleanData"  # output: .../CleanData/AMBER<YEAR>/amber_<YYYYMM>/<thread_id>.json

MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12
}

def to_epoch_seconds(date_str: Optional[str]) -> int:
    """Convert an email Date header into UTC epoch seconds."""
    if not date_str:
        return 0
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0

def normalize_subject(subject: Optional[str]) -> str:
    """
    Normalize a subject so originals and replies group together:
    - remove [AMBER] tag
    - strip 'Re:' prefixes
    - collapse spaces + lowercase
    """
    if not subject:
        return "unknown"
    s = subject.strip()

    if s.lower().startswith("[amber]"):
        rb = s.find("]")
        if rb != -1:
            s = s[rb + 1 :].strip()

    while s[:3].lower() == "re:":
        s = s[3:].strip()

    return " ".join(s.split()).lower()

def month_num(m: str) -> int:
    m3 = (m or "")[:3].title()
    return MONTH_MAP.get(m3, 0)  # 0 -> will format as 00 if unknown

def createThreadLevel(groupedData, threadKey) -> Dict:
    thread_id = None
    subject = None
    messages = []

    dataWorkingWith = groupedData.get(threadKey, [])

    for index, items in enumerate(dataWorkingWith):
        if index == 0:  # root message
            subject = items.get("subject")
            thread_id = items.get("message_id")

        messageDict = {
            "message_id": items.get("message_id"),
            "author": items.get("author_name"),
            "date_raw": items.get("date_raw"),
            "body": items.get("body_text"),
            "url": items.get("url"),
        }

        if index > 0:  # not the root
            messageDict["in_reply_to"] = thread_id

        messages.append(messageDict)

    return {
        "thread_id": thread_id,
        "subject": subject,
        "messages": messages,
    }

def populateJSONFile(sortedData) -> List:
    finalizedData = []
    for items in sortedData:
        threads = createThreadLevel(sortedData, items)
        finalizedData.append(threads)
    return finalizedData

def processOneFile(workingWithJSONFile: Path, workingWithParentFolderName: Path, workingWithFolderName: str):
    # --- Load messages from the JSON file ---
    with open(workingWithJSONFile, "r", encoding="utf-8") as f:
        messages = json.load(f)

    # --- Normalize message_id and thread_id ---
    for message in messages:
        message["message_id"] = to_epoch_seconds(message.get("date_raw"))
        message["thread_id"] = normalize_subject(message.get("subject"))

    # --- Group messages by thread_key ---
    groupedThreads = {}
    for m in messages:
        new_key = m["thread_id"]
        matched_key = None

        # Try to find an existing bucket whose key contains/is contained by new_key
        for existing in groupedThreads.keys():
            if new_key in existing or existing in new_key:
                matched_key = existing
                break

        bucket_key = matched_key or new_key
        groupedThreads.setdefault(bucket_key, []).append(m)

    # --- Sort threads by earliest message_id ---
    sorted_threads = sorted(
        groupedThreads.items(),
        key=lambda x: min(m["message_id"] for m in x[1]),
        reverse=False,
    )
    groupedThreads_sorted = dict(sorted_threads)

    # --- Convert grouped threads into structured JSON data ---
    threadLevelDict = populateJSONFile(groupedThreads_sorted)

    # --- Create output subfolder: CLEAN_BASE/AMBER<YEAR>/amber_<YYYYMM> ---
    subfolder = workingWithParentFolderName / workingWithFolderName
    subfolder.mkdir(parents=True, exist_ok=True)

    # --- Write each thread as its own JSON ---
    for thread in threadLevelDict:
        thread_id = thread["thread_id"] or 0  # int from epoch seconds
        file_path = subfolder / f"{thread_id}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(thread, f, indent=2, ensure_ascii=False)

    print(f"Wrote data to folder: {subfolder}")

def main():
    # INPUT: /opt/airflow/data/RawData/<YEAR>_Data/*.json
    # OUTPUT ROOT: /opt/airflow/data/CleanData/AMBER<YEAR>/amber_<YYYYMM>/
    for year_folder in RAW_BASE.glob("*_Data"):
        if year_folder.is_dir():
            year = year_folder.stem.replace("_Data", "")
            parent_folder = CLEAN_BASE / f"AMBER{year}"
            for json_file in year_folder.glob("*.json"):
                parts = json_file.stem.split("_")
                if len(parts) < 2:
                    print(f"Skipping unexpected filename: {json_file.name}")
                    continue
                month_name = parts[1]
                month_idx = month_num(month_name)
                workingWithFolderName = f"amber_{year}{month_idx:02d}"

                processOneFile(json_file, parent_folder, workingWithFolderName)

if __name__ == "__main__":
    main()
