import os
import re
import shutil
import textwrap
import traceback
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any
from database_menu import AmberChromaAPI, EMBEDDER

# ----------------------------
# Config (env override-friendly)
# ----------------------------

DEFAULT_DB_PATH = os.getenv("CHROMA_DIR", "/opt/chromadb/data/database")

TUTORIALS_COLLECTION = os.getenv("TUTORIALS_COLLECTION", "amber_tutorials")
EMAILS_COLLECTION = os.getenv("EMAILS_COLLECTION", "amber_messages")

N_CANDIDATES = int(os.getenv("N_CANDIDATES", "30"))
TOP_K = int(os.getenv("TOP_K", "5"))
MIN_DOC_CHARS = int(os.getenv("MIN_DOC_CHARS", "200"))

# How to mix results from both collections
TUTORIAL_WEIGHT = float(os.getenv("TUTORIAL_WEIGHT", "1.0"))
EMAIL_WEIGHT = float(os.getenv("EMAIL_WEIGHT", "1.0"))

# LLM / Ollama
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))

# ----------------------------
# Tokenization Helpers
# ----------------------------

_word_re = re.compile(r"[a-zA-Z0-9_]+")

def tokenize(s: str) -> List[str]:
    return [t.lower() for t in _word_re.findall(s or "")]

def keyword_overlap_score(query: str, doc: str) -> float:
    q = tokenize(query)
    d = tokenize(doc)
    if not q or not d:
        return 0.0
    overlap = set(q).intersection(set(d))
    score = 0.0
    for tok in overlap:
        score += 1.0 + min(len(tok), 12) / 12.0
    return score / (len(set(q)) ** 0.5)

def best_window_snippet(query: str, text: str, window_chars: int = 700) -> str:
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
    if len(snippet) > window_chars:
        snippet = snippet[:window_chars] + "…"
    return snippet

def format_similarity(space: str, dist: float) -> str:
    # database_menu uses cosine space by default
    if space == "cosine":
        return f"{1 - dist:.4f} (cosine-sim approx)"
    return f"{dist:.4f} (distance; lower is better)"

# ----------------------------
# Cross-Encoder reranker
# ----------------------------

_RERANKER = None

def get_reranker():
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder
        model_name = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        print(f"Loading reranker model: {model_name}")
        _RERANKER = CrossEncoder(model_name)
        return _RERANKER
    except Exception:
        print("⚠️ Failed to load cross-encoder (fallback to keyword overlap).")
        traceback.print_exc()
        _RERANKER = None
        return None

def try_cross_encoder_rerank(query: str, docs: List[str]) -> List[float]:
    reranker = get_reranker()
    if reranker is None:
        return []
    try:
        pairs = [(query, d) for d in docs]
        scores = reranker.predict(pairs)
        return [float(s) for s in scores]
    except Exception:
        traceback.print_exc()
        return []

# ----------------------------
# Ollama helpers
# ----------------------------

def find_ollama_executable() -> str | None:
    p = shutil.which("ollama")
    if p:
        return p
    env = os.getenv("OLLAMA_PATH")
    if env and Path(env).exists():
        return env
    if os.name == "nt":
        candidates = [
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
            Path("C:/Program Files (x86)/Ollama/ollama.exe"),
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    return None

def generate_with_ollama(question: str, context: str, source_url: str | None = None) -> str:
    ollama_exec = find_ollama_executable()
    if not ollama_exec:
        print("⚠️ Ollama executable not found.")
        return "(Ollama not found — returning retrieved context)\n\n" + context

    print(f"🦙 Using Ollama executable: {ollama_exec}\n")

    source_block = ""
    if source_url:
        source_block = f"\nMost relevant source:\n{source_url}\n"

    prompt = textwrap.dedent(f"""\
        You are a helpful assistant.
        Answer the question using ONLY the context provided.
        If a source link is provided and relevant, cite it at the end as:
        Source: <url>

        Question:
        {question}

        Context:
        {context}
        {source_block}

        Answer:
    """)

    proc = subprocess.run(
        [ollama_exec, "run", OLLAMA_MODEL],
        input=prompt.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=OLLAMA_TIMEOUT,
    )

    out = proc.stdout.decode(errors="replace").strip()
    err = proc.stderr.decode(errors="replace").strip()

    if proc.returncode != 0:
        return f"Ollama failed.\nStderr:\n{err}\nStdout:\n{out}"

    if source_url and "source:" not in out.lower():
        out += f"\nSource: {source_url}"

    return out

# ----------------------------
# Chroma query across BOTH collections
# ----------------------------

def get_space(coll) -> str:
    try:
        meta = coll.metadata or {}
        return meta.get("hnsw:space", "unknown")
    except Exception:
        return "unknown"

def query_collection(coll, question: str, n: int, collection_label: str, weight: float) -> List[Tuple[float, Dict[str, Any]]]:
    """
    Returns list of (weight, item_dict).
    item_dict contains doc/meta/dist/id/collection for downstream rerank + printing.
    """
    q_emb = EMBEDDER.encode(question).tolist()

    res = coll.query(
        query_embeddings=[q_emb],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )

    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    out = []
    for id_, doc, meta, dist in zip(ids, docs, metas, dists):
        if not doc:
            continue
        doc = str(doc)
        if len(doc) < MIN_DOC_CHARS:
            continue
        item = {
            "collection": collection_label,
            "id": id_,
            "doc": doc,
            "meta": meta or {},
            "dist": float(dist),
        }
        out.append((weight, item))
    return out


# ----------------------------
# Interactive menu
# ----------------------------

def open_two_collections(db_path: str, tutorials_name: str, emails_name: str):
    # Use AmberChromaAPI to ensure db folder exists and to reuse its client wiring
    tut_api = AmberChromaAPI(db_path=db_path, collection_name=tutorials_name)
    eml_api = AmberChromaAPI(db_path=db_path, collection_name=emails_name)
    return tut_api, eml_api

def rag_answer_flow(tutorials_coll, emails_coll, question: str):
    space_tut = get_space(tutorials_coll)
    space_eml = get_space(emails_coll)

    # Pull candidates from BOTH
    candidates: List[Tuple[float, Dict[str, Any]]] = []
    candidates += query_collection(tutorials_coll, question, N_CANDIDATES, "tutorials", TUTORIAL_WEIGHT)
    candidates += query_collection(emails_coll, question, N_CANDIDATES, "emails", EMAIL_WEIGHT)

    if not candidates:
        print("⚠️ No candidates found (docs too short or empty).")
        return

    # Rerank all together
    docs_for_rerank = [it["doc"] for _, it in candidates]
    ce_scores = try_cross_encoder_rerank(question, docs_for_rerank)

    if ce_scores and len(ce_scores) == len(candidates):
        merged = []
        for (w, item), ce in zip(candidates, ce_scores):
            merged.append((float(ce) * float(w), float(ce), item))
        merged.sort(key=lambda x: x[0], reverse=True)
        rerank_label = "cross-encoder (weighted by collection)"
    else:
        merged = []
        for (w, item) in candidates:
            kw = keyword_overlap_score(question, item["doc"])
            merged.append((kw * float(w), kw, item))
        merged.sort(key=lambda x: x[0], reverse=True)
        rerank_label = "keyword-overlap fallback (weighted by collection)"

    print(f"✅ Rerank method: {rerank_label}")
    print(f"🔎 Candidates: {len(merged)} | Showing top {TOP_K}")

    # Print top-k
    for i, (weighted, rawscore, item) in enumerate(merged[:TOP_K], 1):
        meta = item["meta"] or {}
        title = meta.get("title") or meta.get("subject") or "(no title/subject)"
        url = meta.get("url") or "(no url)"
        snippet = best_window_snippet(question, item["doc"], 750)

        sim_display = format_similarity(
            space_tut if item["collection"] == "tutorials" else space_eml,
            item["dist"],
        )

        print(f"\n{i}. [{item['collection']}] {title}")
        print(f"   id: {item['id']}")
        print(f"   url: {url}")
        print(f"   vector: {sim_display}")
        print(f"   rerank_score: {rawscore:.4f} | weighted: {weighted:.4f}")
        print(f"   best_snippet: {snippet}")

    # Build context from top-k
    context = "\n\n---\n\n".join(
        best_window_snippet(question, item["doc"], 700)
        for _, _, item in merged[:TOP_K]
    )

    best_meta = merged[0][2].get("meta", {}) if merged else {}
    most_relevant_url = best_meta.get("url")

    print("\n================= FINAL ANSWER (LLM) =================\n")
    answer = generate_with_ollama(question, context, most_relevant_url)
    print(answer)


def main():
    tut_api = None
    eml_api = None
    db_path_display = "None"

    while True:
        print("\n========== AMBER RAG MENU ==========")
        print(f"Current database: {db_path_display}")
        print(f"Tutorials collection: {TUTORIALS_COLLECTION}")
        print(f"Emails collection:    {EMAILS_COLLECTION}")
        print(f"Ollama model:         {OLLAMA_MODEL}")
        print("1. Open DB (and open both collections)")
        print("2. Add JSON to a collection")
        print("3. Peek a collection")
        print("4. RAG Ask (top-k + Llama answer)")
        print("5. Exit")
        print("====================================")

        choice = input("Choose an option (1-5): ").strip()

        if choice == "1":
            db_path = input(f"Database folder (default: {DEFAULT_DB_PATH}): ").strip() or DEFAULT_DB_PATH
            tut_api, eml_api = open_two_collections(db_path, TUTORIALS_COLLECTION, EMAILS_COLLECTION)
            db_path_display = os.path.abspath(db_path)

            try:
                print(f"📦 '{TUTORIALS_COLLECTION}' count: {tut_api.collection.count()}")
            except Exception:
                pass
            try:
                print(f"📦 '{EMAILS_COLLECTION}' count: {eml_api.collection.count()}")
            except Exception:
                pass

        elif choice == "2":
            if tut_api is None or eml_api is None:
                print("No database is currently open. Use option 1 first.")
                continue

            path = input("Enter JSON filename: ").strip()
            target = input("Which collection? (T)utorials or (E)mails: ").strip().lower()

            if target == "t":
                tut_api.add_json(path)
                print(f"Added threads from {path} into {TUTORIALS_COLLECTION}")
            elif target == "e":
                eml_api.add_json(path)
                print(f"Added threads from {path} into {EMAILS_COLLECTION}")
            else:
                print("Invalid choice.")

        elif choice == "3":
            if tut_api is None or eml_api is None:
                print("No database is currently open. Use option 1 first.")
                continue

            target = input("Peek which collection? (T)utorials or (E)mails: ").strip().lower()
            api = tut_api if target == "t" else eml_api if target == "e" else None
            if api is None:
                print("Invalid choice.")
                continue

            peeked = api.peek()
            docs = peeked.get("documents", [])
            metas = peeked.get("metadatas", [])
            if not docs:
                print("No entries found in this collection.")
            else:
                print(f"\nPreviewing first {min(len(docs), 5)} entries:\n")
                for meta, doc in zip(metas[:5], docs[:5]):
                    author = (meta or {}).get("author", "Unknown")
                    subject = (meta or {}).get("subject", "(no subject)")
                    print(f"[{author}] {subject}")
                    print(str(doc)[:250] + "...\n" + "-" * 60)

        elif choice == "4":
            if tut_api is None or eml_api is None:
                print("No database is currently open. Use option 1 first.")
                continue

            while True:
                q = input("\nEnter question (or 'back'): ").strip()
                if q.lower() == "back":
                    break
                rag_answer_flow(tut_api.collection, eml_api.collection, q)

        elif choice == "5":
            print("Exiting.")
            break

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
