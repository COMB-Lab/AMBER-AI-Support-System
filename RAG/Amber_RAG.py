import os
import re
import textwrap
import subprocess
import traceback
from typing import List, Dict, Any

from database_menu import AmberChromaAPI, EMBEDDER


# ---------------- CONFIG ---------------- #

DEFAULT_DB_PATH = os.getenv("CHROMA_DIR", "./prompt_db")
COLLECTION_NAME = "amber_messages"

N_CANDIDATES = 30
TOP_K = 5
MIN_DOC_CHARS = 60
WEIGHT = 1.0

# PDF config
PDF_PATH = os.getenv("AMBER_PDF", "./Amber25.pdf") 
PDF_CHUNK_SIZE = 1000    
PDF_CHUNK_OVERLAP = 150  
MAX_PDF_CHUNKS_IN_CONTEXT = 2  

OLLAMA_MODEL = "llama3.1"
OLLAMA_TIMEOUT = 180


# ---------------- TOKEN HELPERS ---------------- #

_word_re = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(s: str):
    return [t.lower() for t in _word_re.findall(s or "")]


def keyword_overlap_score(query: str, doc: str):
    q = set(tokenize(query))
    d = set(tokenize(doc))
    if not q or not d:
        return 0.0
    return len(q.intersection(d))


def best_window_snippet(query: str, text: str, window_chars: int = 750):
    if not text:
        return ""
    parts = re.split(r"(?<=[\.\?\!])\s+|\n+", text)
    parts = [p.strip() for p in parts if p.strip()]
    q_tokens = set(tokenize(query))

    scored = []
    for p in parts:
        overlap = len(q_tokens.intersection(set(tokenize(p))))
        if overlap:
            scored.append((overlap, p))

    if not scored:
        return text[:window_chars]

    scored.sort(key=lambda x: x[0], reverse=True)
    snippet = " ".join(p for _, p in scored[:6])
    return snippet[:window_chars]


# ---------------- PDF LOADER ---------------- #

def load_pdf_chunks(pdf_path: str, chunk_size: int = PDF_CHUNK_SIZE, overlap: int = PDF_CHUNK_OVERLAP) -> List[Dict]:
    """
    Extract text from a PDF and split it into overlapping chunks.
    Returns a list of dicts: {id, doc, meta, dist}
    'dist' is set to 0.0 as a placeholder — scoring is done later.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        print("⚠️  pypdf not installed. Run: pip install pypdf")
        return []

    if not os.path.isfile(pdf_path):
        print(f"⚠️  PDF not found: {pdf_path}")
        return []

    try:
        reader = PdfReader(pdf_path)
    except Exception as e:
        print(f"⚠️  Could not open PDF: {e}")
        return []

    # Pull text page-by-page, recording page numbers
    pages_text = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append((i, text))

    full_text = ""
    page_boundaries = []   # list of (char_offset, page_num)
    for page_num, text in pages_text:
        page_boundaries.append((len(full_text), page_num))
        full_text += text + "\n"

    def page_for_offset(offset: int) -> int:
        """Return the page number that contains character offset."""
        result = 1
        for boundary_offset, pnum in page_boundaries:
            if offset >= boundary_offset:
                result = pnum
            else:
                break
        return result

    # Chunk with overlap
    chunks = []
    start = 0
    chunk_idx = 0
    while start < len(full_text):
        end = start + chunk_size
        chunk_text = full_text[start:end].strip()
        if len(chunk_text) >= MIN_DOC_CHARS:
            page_num = page_for_offset(start)
            chunks.append({
                "id": f"pdf_chunk_{chunk_idx}",
                "doc": chunk_text,
                "meta": {
                    "source": "pdf",
                    "title": os.path.basename(pdf_path),
                    "url": f"file://{os.path.abspath(pdf_path)}#page={page_num}",
                    "page": page_num,
                    "chunk_id": chunk_idx,
                },
                "dist": 0.0,
            })
            chunk_idx += 1
        start += chunk_size - overlap

    print(f"📄 Loaded {len(chunks)} chunks from '{os.path.basename(pdf_path)}'")
    return chunks


# ---------------- RERANKER ---------------- #

_RERANKER = None


def get_reranker():
    global _RERANKER
    if _RERANKER:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return _RERANKER
    except Exception:
        traceback.print_exc()
        return None


def try_cross_encoder_rerank(query: str, docs: List[str]):
    reranker = get_reranker()
    if not reranker:
        return []
    try:
        pairs = [(query, d) for d in docs]
        scores = reranker.predict(pairs)
        return [float(s) for s in scores]
    except Exception:
        traceback.print_exc()
        return []


# ---------------- QUERY ---------------- #

def get_space(coll):
    try:
        return (coll.metadata or {}).get("hnsw:space", "cosine")
    except Exception:
        return "cosine"


def format_similarity(space: str, dist: float):
    if space == "cosine":
        return f"{1 - dist:.4f} (cosine-sim approx)"
    return f"{dist:.4f}"


def query_collection(coll, question: str, n: int):
    q_emb = EMBEDDER.encode(question).tolist()

    res = coll.query(
        query_embeddings=[q_emb],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )

    ids = res["ids"][0]
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    out = []
    for id_, doc, meta, dist in zip(ids, docs, metas, dists):
        if not doc or len(doc) < MIN_DOC_CHARS:
            continue
        out.append({
            "id": id_,
            "doc": doc,
            "meta": meta or {},
            "dist": float(dist),
        })
    return out


# ---------------- RAG FLOW ---------------- #

def rag_answer_flow(coll, question: str, pdf_chunks: List[Dict]):

    space = get_space(coll)

    # ---- 1. Gather candidates: ChromaDB + PDF ----
    db_candidates = query_collection(coll, question, N_CANDIDATES)
    all_candidates = db_candidates + pdf_chunks   

    if not all_candidates:
        print("⚠️ No candidates found.")
        return

    # ---- 2. Rerank everything together ----
    docs = [c["doc"] for c in all_candidates]
    ce_scores = try_cross_encoder_rerank(question, docs)

    merged = []
    if ce_scores and len(ce_scores) == len(all_candidates):
        for item, ce in zip(all_candidates, ce_scores):
            merged.append((ce * WEIGHT, ce, item))
        rerank_label = "cross-encoder (weighted)"
    else:
        for item in all_candidates:
            kw = keyword_overlap_score(question, item["doc"])
            merged.append((kw * WEIGHT, kw, item))
        rerank_label = "keyword-overlap fallback (weighted)"

    merged.sort(key=lambda x: x[0], reverse=True)

    # ---- 3. Diverse selection (email ≤2, tutorial ≤2, pdf ≤ MAX_PDF_CHUNKS_IN_CONTEXT) ----
    chosen = []
    email_count = 0
    tutorial_count = 0
    pdf_count = 0

    for weighted, rawscore, item in merged:

        meta = item["meta"]
        url_l = (meta.get("url") or "").lower()

        src = meta.get("source")
        if not src:
            if "archive.ambermd.org" in url_l:
                src = "email"
            elif "ambermd.org/tutorials" in url_l:
                src = "tutorial"
            else:
                src = "unknown"

        if src == "email" and email_count < 2:
            chosen.append((weighted, rawscore, item, src))
            email_count += 1
        elif src == "tutorial" and tutorial_count < 2:
            chosen.append((weighted, rawscore, item, src))
            tutorial_count += 1
        elif src == "pdf" and pdf_count < MAX_PDF_CHUNKS_IN_CONTEXT:
            chosen.append((weighted, rawscore, item, src))
            pdf_count += 1
        elif len(chosen) < TOP_K:
            chosen.append((weighted, rawscore, item, src))

        if len(chosen) >= TOP_K:
            break

    print(f"✅ Rerank method: {rerank_label}")
    print(f"🔎 Candidates: {len(merged)} (DB: {len(db_candidates)}, PDF: {len(pdf_chunks)}) | "
          f"Showing top {len(chosen)} (diverse)")

    # ---- 4. Build context ----
    sources = []
    context_blocks = []

    for i, (weighted, rawscore, item, src) in enumerate(chosen, 1):

        meta = item["meta"]
        title = meta.get("title") or meta.get("subject") or "(no title/subject)"
        url = meta.get("url") or "(no url)"
        chunk_id = meta.get("chunk_id")
        page = meta.get("page")

        snippet = best_window_snippet(question, item["doc"], 750)
        sim_display = format_similarity(space, item["dist"]) if src != "pdf" else "n/a (pdf)"

        print(f"\n{i}. [{src.upper()}] {title}", end="")
        if page:
            print(f"  (p.{page})", end="")
        print()
        print(f"   id: {item['id']}")
        if chunk_id is not None:
            print(f"   chunk: {chunk_id}")
        print(f"   url: {url}")
        print(f"   vector: {sim_display}")
        print(f"   rerank_score: {rawscore:.4f} | weighted: {weighted:.4f}")
        print(f"   best_snippet: {snippet}")

        context_blocks.append(snippet)
        if url:
            sources.append(url)

    context = "\n\n---\n\n".join(context_blocks)

    print("\n================= FINAL ANSWER (LLM) =================\n")

    prompt = f"""
You are a helpful assistant.
Answer the question using ONLY the context below.

Question:
{question}

Context:
{context}

Answer:
"""

    proc = subprocess.run(
        ["ollama", "run", OLLAMA_MODEL],
        input=prompt.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=OLLAMA_TIMEOUT,
    )

    answer = proc.stdout.decode(errors="replace").strip()

    # De-duplicate sources, keep order
    sources = [s for s in sources if s]
    sources = list(dict.fromkeys(sources))

    lower = answer.lower()
    if sources and ("source:" not in lower) and ("sources:" not in lower):
        if len(sources) == 1:
            answer += f"\n\nSource: {sources[0]}"
        else:
            answer += "\n\nSources:\n" + "\n".join(sources)

    print(answer)


# ---------------- MENU ---------------- #

def main():
    col_api = None
    db_path_display = "None"
    pdf_chunks = load_pdf_chunks(PDF_PATH)

    while True:
        print("\n========== AMBER RAG MENU ==========")
        print(f"Current database: {db_path_display}")
        print(f"Collection:        {COLLECTION_NAME}")
        print("1. Open DB")
        print("2. RAG Ask")
        print("3. Exit")
        print("====================================")

        choice = input("Choose an option (1-3): ").strip()

        if choice == "1":
            db_path = input(f"Database folder (default: {DEFAULT_DB_PATH}): ").strip() or DEFAULT_DB_PATH
            col_api = AmberChromaAPI(db_path=db_path, collection_name=COLLECTION_NAME)
            db_path_display = db_path
            print(f"📦 '{COLLECTION_NAME}' count: {col_api.collection.count()}")
            print(f"📄 PDF chunks loaded: {len(pdf_chunks)}")

        elif choice == "2":
            if not col_api:
                print("Open DB first.")
                continue
            while True:
                q = input("\nEnter question (or 'back'): ").strip()
                if q.lower() == "back":
                    break
                rag_answer_flow(col_api.collection, q, pdf_chunks)

        elif choice == "3":
            break

        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()