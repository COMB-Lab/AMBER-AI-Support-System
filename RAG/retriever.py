from typing import List, Dict, Optional
from RAG.data_schema import Doc
from Database.amber_chroma_api import AmberChromaAPI

class ChromaRetriever:
    """
    Adapter over the Database team's AmberChromaAPI.
    Strategy:
      • Ask DB with threshold=0.0 (permissive) so nothing is dropped upstream.
      • Rank locally by score and return top-k.
    """
    def __init__(
        self,
        db_path: str = "./amber_chroma_db",
        collection_name: str = "amber_messages",
        default_threshold: float = 0.0
    ):
        self.api = AmberChromaAPI(db_path=db_path, collection_name=collection_name)
        self.default_threshold = default_threshold

    def _to_where(self, filters: Optional[Dict]) -> Optional[Dict]:
        if not filters:
            return None
        clauses = []
        for k, v in filters.items():
            if v is None:
                continue
            clauses.append({k: {"$in": v}} if isinstance(v, list) else {k: {"$eq": v}})
        return {"$and": clauses} if clauses else None

    def _map_results(self, out: dict) -> List[Doc]:
        docs_txt = out.get("documents", []) or []
        metas    = out.get("metadatas", []) or []
        scores   = out.get("scores", []) or []
        n = min(len(docs_txt), len(metas), len(scores) or len(docs_txt))
        rows = []
        for i in range(n):
            md = metas[i] or {}
            rows.append({
                "id": str(md.get("thread_id") or md.get("id") or f"row-{i}"),
                "text": docs_txt[i] or md.get("text", ""),
                "score": float(scores[i]) if i < len(scores) and scores else 0.0,
                "metadata": {
                    "title":       md.get("subject") or md.get("title"),
                    "url_or_path": md.get("url"),
                    "source_type": md.get("doc_type", "thread"),
                    "date":        md.get("date_iso"),
                    "thread_id":   md.get("thread_id"),
                    "author":      md.get("author"),
                },
            })
        rows.sort(key=lambda r: r["score"], reverse=True)  # high → low
        return [Doc(id=r["id"], text=r["text"], score=r["score"], metadata=r["metadata"]) for r in rows]

    def query(
        self,
        query_text: str,
        n_results: int = 6,
        filters: Optional[Dict] = None,
        threshold: Optional[float] = None
    ) -> List[Doc]:
        where = self._to_where(filters)
        out = self.api.query(query_text, n=max(n_results, 10), where=where, threshold=0.0)
        docs = self._map_results(out)
        if threshold is not None:
            docs = [d for d in docs if d.score >= threshold]
        return docs[:n_results]


# ---- Optional stub for --mode stub (keeps demo flexible) ----
class StubRetriever:
    """Very simple stub: returns first N messages as Docs (for JSON-only smoke tests)."""
    def __init__(self):
        self._docs: List[Doc] = []

    def add(self, messages: List):
        self._docs = []
        for i, m in enumerate(messages):
            body = getattr(m, "body", "")
            md = {
                "title": getattr(m, "subject", None),
                "url_or_path": getattr(m, "url", None),
                "source_type": "mailing_list",
                "date": getattr(m, "date_iso", None),
                "thread_id": getattr(m, "thread_id", i),
                "author": getattr(m, "author", None),
            }
            self._docs.append(Doc(id=str(md["thread_id"]), text=body, score=0.0, metadata=md))

    def query(self, query_text: str, n_results: int = 6, filters: Optional[Dict] = None) -> List[Doc]:
        return self._docs[:n_results]