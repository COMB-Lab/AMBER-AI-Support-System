import argparse
from retriever import StubRetriever  # swap to ChromaRetriever when ready
from prompt_builder import build_prompt
from llm_interface import call_llm
from real_data import load_query_and_messages

def _build_citations(items):
    lines = []
    for idx, d in items:
        title = d.metadata.get("title") or d.id
        src   = d.metadata.get("source_type") or ""
        date  = d.metadata.get("date") or ""
        url   = d.metadata.get("url_or_path") or ""
        tail  = f" — {src}, {date}" if (src or date) else ""
        lines.append(f"[[{idx}]] {title}{tail}" + (f" {url}" if url else ""))
    return "\n".join(lines)

def main():
    p = argparse.ArgumentParser(description="Amber RAG demo")
    p.add_argument("-q", "--question", help="User question; if omitted, load synthetic from thread_level.json")
    p.add_argument("-k", type=int, default=6, help="Top-k retrieval")
    p.add_argument("--json", default="thread_level.json", help="Path to thread-level JSON for stub retriever")
    args = p.parse_args()

    if args.question:
        # Use the provided question and still load messages for the stub retriever
        _, messages = load_query_and_messages(args.json)
        question = args.question
    else:
        # Fall back to synthetic question from the JSON
        question, messages = load_query_and_messages(args.json)

    retriever = StubRetriever()
    retriever.add(messages)
    docs = retriever.query(question, n_results=args.k)

    system, user, items = build_prompt(question, docs)
    answer = call_llm(system, user)

    print(answer.strip())
    if items:
        print("\n—\nCitations:\n" + _build_citations(items))

if __name__ == "__main__":
    main()