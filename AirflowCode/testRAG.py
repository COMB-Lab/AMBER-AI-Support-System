import os
import re
import sys
import traceback
import argparse
from pathlib import Path
from typing import List, Tuple

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DATA_DIR / "chroma_db"
COLLECTION_NAME = "amber_tutorials"

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
    """
    if space == "cosine":
        return f"{1 - dist:.4f} (cosine-sim approx)"
    return f"{dist:.4f} (distance; lower is better)"

# ----------------------------
# Optional cross-encoder reranker (memoized)
# ----------------------------
_RERANKER = None

def get_reranker():
    """Load CrossEncoder once and reuse. Returns None if unavailable."""
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        model_name = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        print(f"Loading reranker model: {model_name} ...")
        _RERANKER = CrossEncoder(model_name)
        return _RERANKER
    except Exception:
        print("⚠️ Failed to load cross-encoder reranker (will fallback to keyword overlap).")
        traceback.print_exc()
        _RERANKER = None
        return None

def try_cross_encoder_rerank(query: str, docs: List[str]) -> List[float]:
    """
    Return a list of reranker scores (same order as docs),
    or an empty list to signal fallback.
    """
    reranker = get_reranker()
    if reranker is None:
        return []

    try:
        pairs = [(query, d) for d in docs]
        scores = reranker.predict(pairs)
        scores = [float(s) for s in scores]
        # sanity check
        if len(scores) != len(docs):
            print("⚠️ Reranker returned unexpected number of scores:", len(scores), "expected", len(docs))
            return []
        return scores
    except Exception:
        print("⚠️ Cross-encoder failed during predict():")
        traceback.print_exc()
        return []

# ----------------------------
# Environment diagnostics
# ----------------------------
def print_env_info():
    print("Python:", sys.version.replace("\n", " "))
    try:
        import chromadb as _c
        print("chromadb:", getattr(_c, "__version__", "unknown"))
    except Exception:
        print("chromadb: import failed")
    try:
        import sentence_transformers as _s
        print("sentence-transformers:", getattr(_s, "__version__", "installed"))
    except Exception:
        print("sentence-transformers: not installed (ok if you expect fallback)")
    print("DB path:", DB_PATH)
    print("Collection name:", COLLECTION_NAME)
    print()

def main():
    parser = argparse.ArgumentParser(description="Quick RAG test harness (Chroma + optional cross-encoder)")
    parser.add_argument("--query", "-q", type=str, default=os.getenv("Q", "Why should SHAKE be disabled during minimization in AMBER?"), help="Query to run")
    args = parser.parse_args()
    question = args.query

    print_env_info()

    # Ensure DB path exists
    if not DB_PATH.exists():
        print(f"ERROR: DB path does not exist: {DB_PATH}")
        return

    client = chromadb.PersistentClient(path=str(DB_PATH))
    collections = client.list_collections()
    print("📚 Collections:", [c.name for c in collections])

    try:
        coll = client.get_collection(name=COLLECTION_NAME, embedding_function=EF)
    except Exception:
        print(f"ERROR: Could not open collection '{COLLECTION_NAME}'.")
        traceback.print_exc()
        return

    try:
        print(f"📦 Collection '{COLLECTION_NAME}' has {coll.count()} items")
    except Exception:
        # some chroma versions might not expose count() same way
        print("📦 (couldn't read count)")

    meta = coll.metadata or {}
    space = meta.get("hnsw:space", "unknown")
    print(f"🧭 hnsw:space = {space}\n")

    print(f"❓ Query: {question}\n")

    # Vector retrieve more candidates than we will display
    res = coll.query(
        query_texts=[question],
        n_results=N_CANDIDATES,
        include=["documents", "metadatas", "distances"],
    )

    ids = (res.get("ids") or [[]])[0]
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    packed = []
    for id_, doc, m, dist in zip(ids, docs, metas, dists):
        doc = doc or ""
        if len(doc) < MIN_DOC_CHARS:
            continue
        packed.append((id_, doc, m or {}, float(dist)))

    if not packed:
        print("No usable results found (documents too small or empty).")
        return

    # attempt cross-encoder rerank
    packed_docs = [p[1] for p in packed]
    ce_scores = try_cross_encoder_rerank(question, packed_docs)

    reranked = []
    if ce_scores:
        if len(ce_scores) != len(packed):
            print("⚠️ Inconsistent reranker output length; falling back to keyword overlap.")
            ce_scores = []
    if ce_scores:
        for (id_, doc, m, dist), ce in zip(packed, ce_scores):
            reranked.append((float(ce), id_, doc, m, dist))
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
        snippet = best_window_snippet(question, doc, window_chars=750)
        sim_display = format_similarity(space, dist)

        print(f"{rank}. {title}")
        print(f"   id: {id_}")
        print(f"   url: {url}")
        print(f"   vector: {sim_display}")
        print(f"   rerank_score: {rscore:.4f}")
        print(f"   best_snippet: {snippet}\n")

    # Optional: assemble a simple RAG answer
    top_snippets = [best_window_snippet(question, doc, 500) for _, _, doc, _, _ in reranked[:TOP_K]]
    answer = "\n\n".join(top_snippets).strip()
    if answer:
        print("=== Assembled RAG answer (top snippets) ===")
        print(answer)
    else:
        print("No snippets to assemble into an answer.")

if __name__ == "__main__":
    main()
