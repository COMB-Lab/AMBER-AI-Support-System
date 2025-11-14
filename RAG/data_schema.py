from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class Message:
    thread_id: str
    message_id: str
    subject: str
    author: str
    date_iso: str
    body: str
    url: str
    in_reply_to: Optional[str] = None

@dataclass
class Thread:
    thread_id: str
    messages: List[Message]

@dataclass
class Doc:
    id: str
    text: str
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
