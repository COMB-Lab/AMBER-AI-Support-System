from RAG.retriever import AmberRetriever
from RAG.prompt_builder import build_prompt, build_context
from RAG.llm_interface import OllamaLLM
from RAG.pdf_retriever import search_pdf


def extract_sources(chunks, max_sources: int = 3):
    sources = []
    seen = set()

    for ch in chunks:
        meta = ch.get("metadata", {}) or {}

        if meta.get("doc_type") == "tutorial_pdf":
            page = meta.get("page")
            label = meta.get("title") or "Amber25 Reference Manual"
            if page:
                label = f"{label}, page {page}"
        else:
            label = (
                meta.get("page_title")
                or meta.get("title")
                or meta.get("subject")
                or "Source"
            )

        url = meta.get("page_url") or meta.get("url") or ""

        if not url:
            continue

        key = (label, url)
        if key in seen:
            continue

        seen.add(key)
        sources.append((label, url))

        if len(sources) >= max_sources:
            break

    return sources

def run(
    query: str,
    db_path: str = "/opt/chromadb/data/prompt_db",
    top_k: int = 8,
    pdf_path: str = "tutorials/Amber25.pdf",
    pdf_url: str = "",
):
    retr = AmberRetriever(db_path=db_path, top_k=top_k)

    chunks = []

    # PDF first
    pdf_hits = search_pdf(
        pdf_path,
        query,
        top_k=5,
        pdf_title="Amber25 Reference Manual",
        pdf_url=pdf_url,
    )
    chunks.extend(pdf_hits)

    # Then DB hits
    db_hits = retr.retrieve(query)
    chunks.extend(db_hits)

    if not chunks:
        print(
            "No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket."
        )
        return

    context = build_context(chunks)
    messages = build_prompt(query, context)
    llm = OllamaLLM()
    answer = llm.generate(messages)

    print(answer)

    sources = extract_sources(chunks)
    if sources:
        print("\nSources:")
        for label, url in sources:
            print(f"- [{label}]({url})")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--db-path", default="/opt/chromadb/data/prompt_db")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--pdf-path", default="tutorials/Amber25.pdf")
    p.add_argument("--pdf-url", default="")
    args = p.parse_args()

    run(
        args.query,
        db_path=args.db_path,
        top_k=args.top_k,
        pdf_path=args.pdf_path,
        pdf_url=args.pdf_url,
    )