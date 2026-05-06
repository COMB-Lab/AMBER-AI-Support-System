import os
import re
import textwrap
import csv
from datetime import datetime
import subprocess
import traceback
from typing import List, Dict, Any, Tuple

from database_menu import AmberChromaAPI, EMBEDDER


# ---------------- CONFIG ---------------- #

DEFAULT_DB_PATH = os.getenv("CHROMA_DIR", "/opt/chromadb/data/prompt_db")
COLLECTION_NAME = "amber_messages"

N_CANDIDATES = 100
TOP_K = 5
MIN_DOC_CHARS = 60
WEIGHT = 1.0

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


# ---------------- SOURCE DETECTION ---------------- #

def detect_source_type(meta: Dict[str, Any]) -> str:
    src = (meta.get("source") or "").lower()
    url = (meta.get("url") or "").lower()
    title = (meta.get("title") or meta.get("subject") or "").lower()

    if src in {"email", "tutorial", "pdf"}:
        return src

    if "archive.ambermd.org" in url:
        return "email"

    if "ambermd.org/tutorials" in url or "tutorial" in title:
        return "tutorial"

    if url.startswith("file://") or meta.get("page") is not None:
        return "pdf"

    return "unknown"


# ---------------- PDF LOADER ---------------- #

def load_pdf_chunks(
    pdf_path: str,
    chunk_size: int = PDF_CHUNK_SIZE,
    overlap: int = PDF_CHUNK_OVERLAP,
) -> List[Dict]:
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

    pages_text = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append((i, text))

    full_text = ""
    page_boundaries = []
    for page_num, text in pages_text:
        page_boundaries.append((len(full_text), page_num))
        full_text += text + "\n"

    def page_for_offset(offset: int) -> int:
        result = 1
        for boundary_offset, pnum in page_boundaries:
            if offset >= boundary_offset:
                result = pnum
            else:
                break
        return result

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


# ---------------- CSV MAKER ---------------- #

RESULTS_CSV = "ranking_results_test.csv"
SUMMARY_CSV = "ranking_summary_test.csv"

def append_result_row(
    csv_path: str,
    question: str,
    pipeline: str,
    run_number: int,
    answer: str,
    ce_score: float,
    kw_score: float,
    answer_length: int,
    email_count: int = 0,
    tutorial_count: int = 0,
    pdf_count: int = 0,
):
    file_exists = os.path.isfile(csv_path)

    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "pipeline": pipeline,
        "run_number": run_number,
        "ce_score": ce_score,
        "kw_score": kw_score,
        "answer_length": answer_length,
        "answer": answer,
        "email_count": email_count,
        "tutorial_count": tutorial_count,
        "pdf_count": pdf_count,
    }

    fieldnames = [
        "timestamp",
        "question",
        "pipeline",
        "run_number",
        "ce_score",
        "kw_score",
        "answer_length",
        "answer",
        "email_count",
        "tutorial_count",
        "pdf_count",
    ]

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def append_summary_row(
    csv_path: str,
    question: str,
    pipeline: str,
    avg_scores: dict,
    avg_counts: dict,
):
    file_exists = os.path.isfile(csv_path)

    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "pipeline": pipeline,
        "avg_ce_score": avg_scores["ce_score"],
        "avg_kw_score": avg_scores["kw_score"],
        "avg_answer_length": avg_scores["length"],
        "avg_email_count": avg_counts["email_count"],
        "avg_tutorial_count": avg_counts["tutorial_count"],
        "avg_pdf_count": avg_counts["pdf_count"],
    }

    fieldnames = [
        "timestamp",
        "question",
        "pipeline",
        "avg_ce_score",
        "avg_kw_score",
        "avg_answer_length",
        "avg_email_count",
        "avg_tutorial_count",
        "avg_pdf_count",
    ]

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ---------------- SCORING HELPERS ---------------- #

def score_answer(question: str, answer: str) -> dict:
    ce_scores = try_cross_encoder_rerank(question, [answer])
    ce = ce_scores[0] if ce_scores else 0.0
    kw = keyword_overlap_score(question, answer)
    return {
        "ce_score": round(ce, 4),
        "kw_score": float(kw),
        "length": len(answer),
    }


def average_scores(scores_list: List[dict]) -> dict:
    if not scores_list:
        return {}
    keys = scores_list[0].keys()
    return {k: round(sum(s[k] for s in scores_list) / len(scores_list), 4) for k in keys}


# ---------------- PIPELINE RUNNERS ---------------- #

def _select_top_candidates(coll, question: str, pdf_chunks: List[Dict]) -> List[tuple]:
    db_candidates = query_collection(coll, question, N_CANDIDATES)
    all_candidates = db_candidates + pdf_chunks

    if not all_candidates:
        return []

    docs = [c["doc"] for c in all_candidates]
    ce_scores = try_cross_encoder_rerank(question, docs)

    merged = []
    if ce_scores and len(ce_scores) == len(all_candidates):
        for item, ce in zip(all_candidates, ce_scores):
            merged.append((ce * WEIGHT, ce, item))
    else:
        for item in all_candidates:
            kw = keyword_overlap_score(question, item["doc"])
            merged.append((kw * WEIGHT, kw, item))
    merged.sort(key=lambda x: x[0], reverse=True)

    chosen = []
    email_count = 0
    tutorial_count = 0
    pdf_count = 0

    print("\n[TOP CANDIDATE RAW METADATA]")
    for weighted, rawscore, item in merged[:10]:
        meta = item["meta"] or {}
        print({
            "score": round(rawscore, 4),
            "title": meta.get("title"),
            "subject": meta.get("subject"),
            "url": meta.get("url"),
        })

    for weighted, rawscore, item in merged:
        meta = item["meta"]
        src = detect_source_type(meta)

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

    return chosen


def run_llm_with_rag(
    coll,
    question: str,
    pdf_chunks: List[Dict],
) -> Tuple[str, int, int, int]:
    """RAG pipeline — returns (answer, email_count, tutorial_count, pdf_count)."""
    chosen = _select_top_candidates(coll, question, pdf_chunks)
    if not chosen:
        return "[No candidates found]", 0, 0, 0

    src_counts = {"email": 0, "tutorial": 0, "pdf": 0}
    for _, _, item, src in chosen:
        if src in src_counts:
            src_counts[src] += 1

    context_blocks = [
        best_window_snippet(question, item["doc"], 750)
        for _, _, item, _ in chosen
    ]
    context = "\n\n---\n\n".join(context_blocks)

    prompt = f"""You are a helpful assistant.
Answer the question using ONLY the context below.

Question:
{question}

Context:
{context}

Answer:"""

    try:
        proc = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=OLLAMA_TIMEOUT,
        )
        answer = proc.stdout.decode(errors="replace").strip()
        return answer, src_counts["email"], src_counts["tutorial"], src_counts["pdf"]
    except Exception as e:
        return f"[ERROR: {e}]", 0, 0, 0


def run_llm_without_rag(question: str) -> Tuple[str, int, int, int]:
    """Baseline — same LLM, no retrieval context."""
    prompt = f"""You are a helpful assistant.
Answer the following question as best as you can.

Question:
{question}

Answer:"""

    try:
        proc = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL],
            input=prompt.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=OLLAMA_TIMEOUT,
        )
        answer = proc.stdout.decode(errors="replace").strip()
        return answer, 0, 0, 0
    except Exception as e:
        return f"[ERROR: {e}]", 0, 0, 0


def run_chatgpt_manual_answer(manual_answers: List[str], i: int) -> Tuple[str, int, int, int]:
    if i < len(manual_answers):
        return manual_answers[i], 0, 0, 0
    return "[Missing manual answer]", 0, 0, 0


def run_ChatGPT_manual_answers(question: str, expected_runs: int) -> List[str]:
    
    separator = "===RUN==="

    print("=" * 70)
    print("  CHATGPT MANUAL WEB ANSWER")
    print("=" * 70)
    print("Ask the question on the website multiple times, then paste ALL answers")
    print("below in one go.")
    print()
    print(f"Use this separator before each answer: {separator}")
    print("Type END on its own line when finished.")
    print()
    print("Example format:")
    print(separator)
    print("answer 1...")
    print(separator)
    print("answer 2...")
    print(separator)
    print("answer 3...")
    print("END")
    print()

    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)

    pasted = "\n".join(lines).strip()
    if not pasted:
        return []

    parts = [p.strip() for p in pasted.split(separator) if p.strip()]

    if len(parts) != expected_runs:
        print(f"\n⚠️ Expected {expected_runs} answers, but found {len(parts)}.")
        print("The program will still continue with what it found.\n")

    return parts


# ---------------- RANK QUESTIONS ---------------- #

def rank_questions(coll, question: str, pdf_chunks: List[Dict], runs: int = 1):
    """
    Run the question through all 3 pipelines, score each answer,
    print per-run scores, then a final ranked comparison table.
    Returns the full results dict.
    """
    print(f"\n{'='*70}")
    print(f"  Question: {question}")

    manual_answers = run_ChatGPT_manual_answers(question, runs)

    pipelines = {
        "LLM + RAG": lambda i: run_llm_with_rag(coll, question, pdf_chunks),
        "LLM only": lambda i: run_llm_without_rag(question),
        "ChatGPT Web manual": lambda i: run_chatgpt_manual_answer(manual_answers, i),
    }

    results = {}

    for name, runner in pipelines.items():
        print(f"\n▶  [{name}]  ({runs} run{'s' if runs > 1 else ''})")
        all_scores = []
        all_counts = []
        last_answer = ""

        for i in range(runs):
            answer, email_c, tutorial_c, pdf_c = runner(i)
            last_answer = answer

            if answer.startswith("[") and "error" in answer.lower():
                print(f"   run {i+1:>2}: ERROR -> {answer}")
                continue

            if answer == "[Missing manual answer]":
                print(f"   run {i+1:>2}: ERROR -> {answer}")
                continue

            s = score_answer(question, answer)
            all_scores.append(s)
            all_counts.append({
                "email_count": email_c,
                "tutorial_count": tutorial_c,
                "pdf_count": pdf_c,
            })

            print(
                f"   run {i+1:>2}: ce={s['ce_score']:+.4f}  "
                f"kw={int(s['kw_score']):>3}  len={s['length']:>5}  "
                f"| email={email_c} tutorial={tutorial_c} pdf={pdf_c}"
            )

            append_result_row(
                csv_path=RESULTS_CSV,
                question=question,
                pipeline=name,
                run_number=i + 1,
                answer=answer,
                ce_score=s["ce_score"],
                kw_score=s["kw_score"],
                answer_length=s["length"],
                email_count=email_c,
                tutorial_count=tutorial_c,
                pdf_count=pdf_c,
            )

        avg = average_scores(all_scores) if all_scores else {
            "ce_score": float("-inf"),
            "kw_score": 0.0,
            "length": 0,
        }

        avg_counts = average_scores(all_counts) if all_counts else {
            "email_count": 0.0,
            "tutorial_count": 0.0,
            "pdf_count": 0.0,
        }

        append_summary_row(
            csv_path=SUMMARY_CSV,
            question=question,
            pipeline=name,
            avg_scores=avg,
            avg_counts=avg_counts,
        )

        results[name] = {
            "answer": last_answer,
            "scores": avg,
            "counts": avg_counts,
            "all_scores": all_scores,
        }

    ranked = sorted(results.items(), key=lambda x: x[1]["scores"]["ce_score"], reverse=True)

    print(f"\n{'='*62}")
    print("  SCORE COMPARISON  (sorted by cross-encoder score)")
    print(f"{'='*62}")
    print(f"  {'Pipeline':<16}  {'CE Score':>10}  {'KW Overlap':>10}  {'Ans Length':>10}")
    print(f"  {'-'*16}  {'-'*10}  {'-'*10}  {'-'*10}")

    medals = ["🥇", "🥈", "🥉"]
    for rank, (name, data) in enumerate(ranked):
        s = data["scores"]
        medal = medals[rank] if rank < 3 else "  "
        print(f"{medal} {name:<16}  {s['ce_score']:>+10.4f}  {s['kw_score']:>10.1f}  {s['length']:>10}")

    winner = ranked[0][0]
    runner_up = ranked[1][0] if len(ranked) > 1 else None

    print(f"\n  ✅ Best answer  : {winner}")
    if runner_up:
        gap = ranked[0][1]["scores"]["ce_score"] - ranked[1][1]["scores"]["ce_score"]
        print(f"  📊 CE gap (1st vs 2nd): {gap:+.4f}")

    print(f"\n💾 Results appended to: {RESULTS_CSV}")
    print(f"💾 Summary appended to: {SUMMARY_CSV}")

    show = input("\nPrint all answers? (y/n): ").strip().lower()
    if show == "y":
        for name, data in results.items():
            print(f"\n{'─'*62}")
            print(f"  [{name}]")
            print(f"{'─'*62}")
            print(data["answer"])

    return results

# ---------------- ORIGINAL RAG FLOW ---------------- #

def rag_answer_flow(coll, question: str, pdf_chunks: List[Dict]):
    space = get_space(coll)
    db_candidates = query_collection(coll, question, N_CANDIDATES)
    all_candidates = db_candidates + pdf_chunks

    if not all_candidates:
        print("⚠️ No candidates found.")
        return

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

    chosen = []
    email_count = 0
    tutorial_count = 0
    pdf_count = 0

    for weighted, rawscore, item in merged:
        meta = item["meta"]
        src = detect_source_type(meta)

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
    print(
        f"🔎 Candidates: {len(merged)} (DB: {len(db_candidates)}, PDF: {len(pdf_chunks)}) | "
        f"Showing top {len(chosen)} (diverse)"
    )
    print(f"📊 Source counts in final context: email={email_count}, tutorial={tutorial_count}, pdf={pdf_count}")

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

    prompt = f"""You are a helpful assistant.
Answer the question using ONLY the context below.

Question:
{question}

Context:
{context}

Answer:"""

    proc = subprocess.run(
        ["ollama", "run", OLLAMA_MODEL],
        input=prompt.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=OLLAMA_TIMEOUT,
    )

    answer = proc.stdout.decode(errors="replace").strip()

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
    pdf_chunks = []
    db_path_display = "None"

    while True:
        print("\n========== AMBER RAG MENU ==========")
        print(f"Current database: {db_path_display}")
        print(f"Collection:        {COLLECTION_NAME}")
        print("1. Open DB")
        print("2. RAG Ask")
        print("3. RankEach (RAG vs LLM vs ChatGPT manual web)")
        print("4. Exit")
        print("====================================")

        choice = input("Choose an option (1-4): ").strip()

        if choice == "1":
            db_path = input(f"Database folder (default: {DEFAULT_DB_PATH}): ").strip() or DEFAULT_DB_PATH
            col_api = AmberChromaAPI(db_path=db_path, collection_name=COLLECTION_NAME)
            db_path_display = db_path
            pdf_chunks = load_pdf_chunks(PDF_PATH)
            print(
                f"\n📦 '{COLLECTION_NAME}' count: {col_api.collection.count()} "
                f"\n📄 PDF chunks loaded: {len(pdf_chunks)}"
            )

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
            if not col_api:
                print("Open DB first.")
                continue
            while True:
                q = input("\nEnter question (or 'back'): ").strip()
                if q.lower() == "back":
                    break
                runs_str = input("Number of runs to average (default 1): ").strip()
                runs = int(runs_str) if runs_str.isdigit() and int(runs_str) > 0 else 1
                rank_questions(col_api.collection, q, pdf_chunks, runs=runs)

        elif choice == "4":
            break

        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()