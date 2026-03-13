from RAG.retriever import AmberRetriever
from RAG.prompt_builder import build_prompt, build_context
from RAG.llm_interface import OllamaLLM
from RAG.pdf_retriever import search_pdf


def run(
    query: str,
    db_path: str = "/opt/chromadb/data/prompt_db",
    top_k: int = 8,
    pdf_path: str = "tutorials/Amber25.pdf",
):
    retr = AmberRetriever(db_path=db_path, top_k=top_k)
    chunks = []
    pdf_hits = search_pdf(pdf_path, query)
    chunks.extend([h["text"] for h in pdf_hits])

    db_hits = retr.retrieve(query)
    chunks.extend([h["text"] for h in db_hits])

    if not chunks:
        print(
            "No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket."
        )
        return

    context = build_context(chunks)
    messages = build_prompt(query, context)
    llm = OllamaLLM()
    print(llm.generate(messages))


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--db-path", default="/opt/chromadb/data/prompt_db")
    p.add_argument("--top-k", type=int, default=8)
    p.add_argument("--pdf-path", default="tutorials/Amber25.pdf")
    args = p.parse_args()

    run(
        args.query,
        db_path=args.db_path,
        top_k=args.top_k,
        pdf_path=args.pdf_path,
    )