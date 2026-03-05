import os
from typing import List, Dict, Any, Optional

DEFAULT_PROMPT_DB = "/opt/chromadb/data/prompt_db"
DEFAULT_AMBER_DB = "/opt/chromadb/data/amber_chroma_db"

import sys
sys.path.append("/opt/chromadb/data")
from database_menu import AmberChromaAPI

class AmberRetriever:
    def __init__(
        self,
        db_path: str = DEFAULT_PROMPT_DB,
        top_k: int = 8,
        threshold: float = 0.35,
    ) -> None:
        self.db_path = db_path
        self.top_k = top_k
        self.threshold = threshold
        self.api = AmberChromaAPI(db_path=db_path)

    def retrieve(self, query: str, where: Optional[dict] = None) -> List[Dict[str, Any]]:
        """
        Returns list of dicts: {'text', 'metadata', 'score'/'similarity'}
        Uses AmberChromaAPI.query() which returns {'documents','metadatas','scores'}.
        """
        res = self.api.query(text=query, n=self.top_k, where=where, threshold=0.0)
        docs = res.get("documents", [])
        metas = res.get("metadatas", [])
        scores = res.get("scores", [])
        out = []
        for d, m, s in zip(docs, metas, scores):
            out.append({"text": d, "metadata": m or {}, "similarity": float(s)})
        return out