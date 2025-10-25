import argparse
import os
import re
import sys

# --- package-first imports, with optional StubRetriever ---
try:
    from RAG.retriever import ChromaRetriever
    try:
        from RAG.retriever import StubRetriever  # optional
    except Exception:
        StubRetriever = None
    from RAG.prompt_builder import build_prompt
    from RAG.llm_interface import call_llm
    from RAG.real_data import load_query_and_messages
except ImportError:
    # Fallback to relative imports when run from inside RAG/
    sys.path.append(os.path.dirname(__file__))
    from retriever import ChromaRetriever
    try:
        from retriever import StubRetriever
    except Exception:
        StubRetriever = None
    from prompt_builder import build_prompt
    from llm_interface import call_llm
    from real_data import load_query_and_messages


def _build_citations(items):
    lines = []
    for idx, d in items:
        md = d.metadata or {}
        title = md.get("title") or d.id
        src   = md.get("source_type") or ""
        date  = md.get("date") or ""
        url   = md.get("url_or_path") or ""
        tail  = f" — {src}, {date}" if (src or date) else ""
        lines.append(f"[[{idx}]] {title}{tail}" + (f" {url}" if url else ""))
    return "\n".join(lines)

# --- guardrails ---
_BAD_PATTERNS = [
    r"^\s*\[\[\s*\d+\s*\]\]\s*$",
    r"^\s*\[\[\s*n\s*\]\]\s*$",
    r"^\s*\[\[",
    r"^\s*(context|instructions)[:\-]\s*$",
]

def _looks_bad(ans: str) -> bool:
    s = (ans or "").strip().lower()
    return any(re.match(p, s) for p in _BAD_PATTERNS) or len(s) < 8

def _regenerate_with_top1(system, user, temperature=0.3):
    user2 = user + "\n\nADJUSTMENT:\nWrite 2–4 short sentences. Do not echo context bullets."
    return call_llm(system, user2, temperature=temperature, max_tokens=180)

def _finalize(ans: str) -> str:
    s = (ans or "").strip()
    # strip any leading [[...]]
    s = re.sub(r'^\s*(\[\[\s*[\dn]+\s*\]\]\s*)+', '', s)
    s = re.sub(r'^\s*\[\[.*?\]\]\s*', '', s)
    if not s.lower().startswith("answer:"):
        s = "ANSWER: " + s
    return s.strip()


def main():
    p = argparse.ArgumentParser(description="Amber RAG demo")
    p.add_argument("-q", "--question",
                   help="User question. Required for --mode chroma. If omitted in stub mode, a synthetic question is loaded.")
    p.add_argument("-k", type=int, default=6, help="Top-k retrieval")
    p.add_argument("--mode", choices=["stub", "chroma"], default="chroma", help="Which retriever to use")
    p.add_argument("--db-path", default="./amber_chroma_db", help="Chroma db_path (folder with collection data)")
    p.add_argument("--collection", default="amber_messages", help="Chroma collection name")
    p.add_argument("--threshold", type=float, default=0.0, help="Server similarity threshold (0.0 = permissive)")
    p.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature (0.0 = deterministic)")
    p.add_argument("--max-new", type=int, default=200, help="Max new tokens for generation")
    p.add_argument("--json", default="thread_level.json", help="(stub mode) path to thread-level JSON")
    p.add_argument("--debug", action="store_true", help="Print prompt preview and token counts")
    args = p.parse_args()

    # --- choose retriever & fetch docs ---
    if args.mode == "chroma":
        if not args.question:
            raise SystemExit("Please provide --question when using --mode chroma")
        retriever = ChromaRetriever(
            db_path=args.db_path,
            collection_name=args.collection,
            default_threshold=args.threshold,
        )
        docs = retriever.query(args.question, n_results=args.k, filters=None, threshold=args.threshold)
        question = args.question
    else:
        if StubRetriever is None:
            raise SystemExit("Stub mode is not available in this build. Use --mode chroma.")
        if args.question:
            _, messages = load_query_and_messages(args.json)
            question = args.question
        else:
            question, messages = load_query_and_messages(args.json)
        retriever = StubRetriever()
        retriever.add(messages)
        docs = retriever.query(question, n_results=args.k)

    # Fallback minimal prompt if no docs
    if not docs:
        system = "You are an expert Amber assistant. If context is missing, say so and request the needed info."
        user = f"QUESTION:\n{question}\n\nCONTEXT:\n- [[1]] No context found.\n\nFORMAT: Start with ANSWER:, 2–4 sentences, use [[n]] if any context is present.\nANSWER:"
        answer = call_llm(system, user, temperature=args.temperature, max_tokens=args.max_new)
        print(_finalize(answer))
        return

    # --- build prompt & (optional) debug preview ---
    system, user, items = build_prompt(question, docs)
    if args.debug:
        from RAG.llm_interface import _get_tokenizer, DEFAULT_MODEL
        tok = _get_tokenizer(DEFAULT_MODEL)
        preview = f"{system}\n\n{user}"
        ids = tok.encode(preview, add_special_tokens=True, truncation=True, max_length=512)
        print(f"\n[DEBUG] tokens={len(ids)} chars={len(preview)}")
        print("[DEBUG] prompt >>>\n" + preview[:800] + ("\n... [truncated]" if len(preview) > 800 else ""))

    # --- generate ---
    answer = call_llm(system, user, temperature=args.temperature, max_tokens=args.max_new)

    # Retry once if the model output looks bad; use only top-1 to reduce confusion
    if _looks_bad(answer):
        top1 = [docs[0]]
        system2, user2, items2 = build_prompt(question, top1)
        answer2 = _regenerate_with_top1(system2, user2, temperature=max(0.3, args.temperature))
        if not _looks_bad(answer2):
            answer, items = answer2, items2

    # --- print result + citations ---
    answer = _finalize(answer)
    print(answer.strip())
    if items:
        print("\n—\nCitations:\n" + _build_citations(items))


if __name__ == "__main__":
    main()