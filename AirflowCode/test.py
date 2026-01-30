# test.py
import os
import re
from pathlib import Path
from typing import List, Tuple

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# ----------------------------
# Config (match your project)
# ----------------------------
DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "chroma_db"
COLLECTION_NAME = "amber_tutorials"

# Use same EF you used originally (DefaultEmbeddingFunction)
EF = DefaultEmbeddingFunction()

# Retrieval / rerank knobs
N_CANDIDATES = int(os.getenv("N_CANDIDATES", "30"))   # pull more from vector search
TOP_K = int(os.getenv("TOP_K", "5"))                  # show top K after rerank
MIN_DOC_CHARS = int(os.getenv("MIN_DOC_CHARS", "200"))


# ----------------------------
# Helpers: tokenization + snippet extraction
# ----------------------------
_word_re = re.compile(r"[a-zA-Z0-9_]+")
def tokenize(s: str) -> List[str]:
    return [t.lower() for t in _word_re.findall(s or "")]

def keyword_overlap_score(query: str, doc: str) -> float:
    """
    Strong fallback scorer when you don't have a cross-encoder installed.
    Uses a weighted overlap of query tokens with doc tokens.
    """
    q = tokenize(query)
    d = tokenize(doc)

    if not q or not d:
        return 0.0

    dq = set(q)
    dd = set(d)
    overlap = dq.intersection(dd)

    # weight longer tokens higher (e.g., "minimization", "pmemd", "maxcyc")
    score = 0.0
    for tok in overlap:
        w = 1.0 + min(len(tok), 12) / 12.0
        score += w

    # normalize by query size (so bigger queries aren't unfairly penalized)
    return score / (len(dq) ** 0.5)

def best_window_snippet(query: str, text: str, window_chars: int = 700) -> str:
    """
    Find the best window of text that contains the most query tokens.
    This makes the preview actually show the relevant part (e.g. minimization parameters).
    """
    if not text:
        return ""

    q_tokens = set(tokenize(query))
    if not q_tokens:
        return (text[:window_chars] + ("…" if len(text) > window_chars else ""))

    # split into rough "sentences/lines"
    parts = re.split(r"(?<=[\.\?\!])\s+|\n+", text)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return (text[:window_chars] + ("…" if len(text) > window_chars else ""))

    # score each part by how many query tokens it contains
    scored: List[Tuple[float, str]] = []
    for p in parts:
        ptoks = set(tokenize(p))
        overlap = len(q_tokens.intersection(ptoks))
        if overlap:
            scored.append((overlap, p))

    # if nothing overlaps, fallback
    if not scored:
        return (text[:window_chars] + ("…" if len(text) > window_chars else ""))

    # take top few parts and stitch a snippet
    scored.sort(key=lambda x: x[0], reverse=True)
    snippet = " ".join(p for _, p in scored[:6])
    snippet = snippet.strip()

    if len(snippet) > window_chars:
        snippet = snippet[:window_chars].rstrip() + "…"
    return snippet

def format_similarity(space: str, dist: float) -> str:
    """
    Chroma distances depend on hnsw:space.
    For cosine: similarity ~= 1 - distance.
    For l2: distance (lower is better).
    For ip: distance may represent inner product (higher is better),
    but depends on implementation; we just display raw.
    """
    if space == "cosine":
        return f"{1 - dist:.4f} (cosine-sim approx)"
    return f"{dist:.4f} (distance; lower is better)"


# ----------------------------
# Optional cross-encoder reranker
# ----------------------------
def try_cross_encoder_rerank(query: str, docs: List[str]) -> List[float]:
    """
    If sentence-transformers is installed, use a cross-encoder for reranking.
    Otherwise return empty list to signal fallback.
    """
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        model_name = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        reranker = CrossEncoder(model_name)
        pairs = [(query, d) for d in docs]
        scores = reranker.predict(pairs)
        return [float(s) for s in scores]
    except Exception:
        return []


def main():
    print(f"🔗 DB path: {DB_PATH}")
    client = chromadb.PersistentClient(path=str(DB_PATH))

    collections = client.list_collections()
    print("📚 Collections:", [c.name for c in collections])

    coll = client.get_collection(name=COLLECTION_NAME, embedding_function=EF)
    print(f"📦 Collection '{COLLECTION_NAME}' has {coll.count()} items")

    # Print collection metadata so you can see hnsw:space if present
    meta = coll.metadata or {}
    space = meta.get("hnsw:space", "unknown")
    print(f"🧭 hnsw:space = {space}")

    question = os.getenv("Q", "how do I prepare input files and run minimization in AMBER?")
    print(f"\n❓ Query: {question}\n")

    # Vector retrieve more candidates than you display
    res = coll.query(
        query_texts=[question],
        n_results=N_CANDIDATES,
        include=["documents", "metadatas", "distances"],
    )

    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    # Basic guardrails
    packed = []
    for id_, doc, m, dist in zip(ids, docs, metas, dists):
        doc = doc or ""
        if len(doc) < MIN_DOC_CHARS:
            continue
        packed.append((id_, doc, m or {}, float(dist)))

    if not packed:
        print("No usable results found (documents too small or empty).")
        return

    # Cross-encoder rerank if available; else fallback overlap scorer
    packed_docs = [p[1] for p in packed]
    ce_scores = try_cross_encoder_rerank(question, packed_docs)

    reranked = []
    if ce_scores:
        for (id_, doc, m, dist), ce in zip(packed, ce_scores):
            reranked.append((ce, id_, doc, m, dist))
        reranked.sort(key=lambda x: x[0], reverse=True)
        rerank_label = "cross-encoder"
    else:
        for (id_, doc, m, dist) in packed:
            s = keyword_overlap_score(question, doc)
            reranked.append((s, id_, doc, m, dist))
        reranked.sort(key=lambda x: x[0], reverse=True)
        rerank_label = "keyword-overlap (fallback)"

    print(f"✅ Rerank method: {rerank_label}")
    print(f"🔎 Candidates: {len(packed)} | Showing top {TOP_K}\n")

    for rank, (rscore, id_, doc, m, dist) in enumerate(reranked[:TOP_K], 1):
        title = m.get("title", "(no title)")
        url = m.get("url", "(no url)")

        # Show a targeted snippet (not just the doc start)
        snippet = best_window_snippet(question, doc, window_chars=750)
        sim_display = format_similarity(space, dist)

        print(f"{rank}. {title}")
        print(f"   id: {id_}")
        print(f"   url: {url}")
        print(f"   vector: {sim_display}")
        print(f"   rerank_score: {rscore:.4f}")
        print(f"   best_snippet: {snippet}\n")


if __name__ == "__main__":
    main()
