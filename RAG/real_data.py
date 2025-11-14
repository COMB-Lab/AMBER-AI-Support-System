from typing import Tuple, List
from RAG.data_schema import Message
import json

def load_query_and_messages(json_path: str) -> Tuple[str, List[Message]]:
    with open(json_path, "r", encoding="utf-8") as f:
        threads = json.load(f)

    all_messages = []
    query = ""

    for thread in threads:
        raw_subject = thread.get("subject", "")
        query = raw_subject.replace("Re: ", "").replace("[AMBER] ", "").strip()
        query = f"What is being discussed regarding {query.lower()}?"

        thread_id = thread.get("thread_id", "")
        for msg in thread.get("messages", []):
            message = Message(
                thread_id=thread_id,
                message_id=msg.get("message_id", ""),
                subject=raw_subject,
                author=msg.get("author", ""),
                date_iso=msg.get("date_raw", ""),
                body=msg.get("body", ""),
                url=msg.get("url"),
                in_reply_to=msg.get("in_reply_to", None)
            )
            all_messages.append(message)

    return query, all_messages
