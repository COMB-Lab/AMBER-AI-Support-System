import json
from email.utils import parsedate_to_datetime
from datetime import timezone
from typing import Optional, Dict, List


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
            s = s[rb+1:].strip()

    while s[:3].lower() == "re:":
        s = s[3:].strip()

    return " ".join(s.split()).lower()


def createThreadLevel(groupedData, threadKey) -> Dict:
    thread_id = None
    subject = None
    messages = []

    dataWorkingWith = groupedData.get(threadKey)

    for index, items in enumerate(dataWorkingWith):
        if index == 0:  # root message
            subject = items["subject"]
            thread_id = items["message_id"]

        messageDict = {
            "message_id": items["message_id"],
            "author": items["author_name"],
            "date_raw": items["date_raw"],
            "body": items["body_text"],
            "url": items["url"]
        }

        if index > 0:  # not the root
            messageDict["in_reply_to"] = thread_id

        messages.append(messageDict)

    return {
        "thread_id": thread_id,
        "subject": subject,
        "messages": messages
    }


def populateJSONFile(sortedData) -> List:
    finalizedData = []
    for items in sortedData:
        threads = createThreadLevel(sortedData, items)
        finalizedData.append(threads)
    return finalizedData


def main():

    # Load Messages in List
    with open("amber_2024_Mar.json", "r", encoding="utf-8") as f:
        messages = json.load(f)

    # Override message_id to Epoch time and thread_id to normalized
    for message in messages:
        message["message_id"] = to_epoch_seconds(message.get("date_raw"))
        message["thread_id"] = normalize_subject(message.get("subject"))

    # Group messages by thread_key
    groupedThreads = {}
    for m in messages:
        new_key = m["thread_id"]
        matched_key = None

        # try to find an existing bucket whose key contains/is contained by new_key
        for existing in groupedThreads.keys():
            if new_key in existing or existing in new_key:
                matched_key = existing
                break

        bucket_key = matched_key or new_key
        groupedThreads.setdefault(bucket_key, []).append(m)

    # Sort by message_id
    sorted_threads = sorted(
        groupedThreads.items(),
        key=lambda x: min(m["message_id"] for m in x[1]),
        reverse=False
    )

    groupedThreads_sorted = dict(sorted_threads)

    threadLevelDict = populateJSONFile(groupedThreads_sorted)

    with open("thread_level.json", "w", encoding="utf-8") as f:
        json.dump(threadLevelDict, f, indent=2, ensure_ascii=False)

    print("Wrote data to thread_level.json")


main()
