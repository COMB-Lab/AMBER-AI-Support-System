# RAG/retriever.py
import os
from typing import List, Dict, Any

# Lazy import so devs without access don’t crash at import-time
def _get_amber_db():
    import sys
    sys.path.append("/opt/chromadb/data")
    from vector_db_maker import AmberChromaAPI
    return AmberChromaAPI

DEFAULT_DB_PATH = os.getenv("AMBER_CHROMA_DB_PATH", "/opt/chromadb/data/amber_chroma_db")
DEFAULT_COLLECTION = os.getenv("AMBER_CHROMA_COLLECTION", "amber_messages")
DEFAULT_TOP_K = int(os.getenv("AMBER_TOP_K", "4"))
DEFAULT_THRESHOLD = float(os.getenv("AMBER_THRESHOLD", "0.3"))

class AmberRetriever:
    def __init__(self,
                 db_path: str = DEFAULT_DB_PATH,
                 collection: str = DEFAULT_COLLECTION,
                 top_k: int = DEFAULT_TOP_K,
                 threshold: float = DEFAULT_THRESHOLD) -> None:
        AmberChromaAPI = _get_amber_db()
        self.api = AmberChromaAPI(db_path=db_path, collection_name=collection)
        self.top_k = top_k
        self.threshold = threshold

    def retrieve(self, query: str) -> List[Dict[str, Any]]:
        """Returns a list of chunks: [{'text': str, 'metadata': dict, 'score': float}, ...]"""
        res = self.api.query(query, n=self.top_k, threshold=self.threshold)
        docs = res.get("documents", [])
        metas = res.get("metadatas", [])
        scores = res.get("scores", [])
        out = []
        for i in range(min(len(docs), len(metas), len(scores))):
            out.append({"text": docs[i], "metadata": metas[i], "score": scores[i]})
        return out