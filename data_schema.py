from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Message:
    thread_id: str
    message_id: str
    subject: str
    author: str
    date_iso: str
    body: str
    url: str
    in_reply_to: Optional[str]

@dataclass
class Thread:
    thread_id: str
    messages: List[Message]
