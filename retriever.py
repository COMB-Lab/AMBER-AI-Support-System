from typing import List, Dict, Optional
from data_schema import Message, Doc

class Retriever:
    def add(self, documents: List[Message]):
        raise NotImplementedError

    def query(self, query_text: str, n_results: int = 5, filters: Optional[Dict] = None) -> List[Doc]:
        raise NotImplementedError

class StubRetriever(Retriever):
    """Returns first N messages as docs. Good for smoke tests; not a real retriever."""
    def __init__(self):
        self._messages: List[Message] = []

    def add(self, documents: List[Message]):
        self._messages = documents

    def query(self, query_text: str, n_results: int = 5, filters: Optional[Dict] = None) -> List[Doc]:
        out: List[Doc] = []
        for m in self._messages[:n_results]:
            out.append(Doc(
                id=m.message_id or m.url or f"{m.thread_id}:{m.date_iso}",
                text=m.body,
                score=0.0,
                metadata={
                    "title": m.subject,
                    "url_or_path": m.url,
                    "source_type": "mailing_list",
                    "date": m.date_iso,
                    "thread_id": m.thread_id,
                    "author": m.author,
                }
            ))
        return out

class ChromaRetriever(Retriever):
    """Thin adapter to the Database team’s Chroma wrapper."""
    def __init__(self, client=None):
        self.client = client  # Inject the DB team's wrapper/module as needed

    def add(self, documents: List[Message]):
        # Usually unnecessary for a remote Chroma; kept for interface parity
        pass

    def query(self, query_text: str, n_results: int = 5, filters: Optional[Dict] = None) -> List[Doc]:
        # TODO: replace with real call to DB team's retriever, e.g.:
        # raw = self.client.retrieve(query=query_text, k=n_results, filters=filters)
        # return [Doc(id=r["id"], text=r["text"], score=r["score"], metadata=r["metadata"]) for r in raw]
        raise NotImplementedError("Hook up to DB team's Chroma wrapper here")