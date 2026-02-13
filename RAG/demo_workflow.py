import argparse
from RAG.retriever import retrieve_with_pdf
from RAG.prompt_builder import build_context, build_prompt
from RAG.llm_interface import generate_ollama


def main():
    p = argparse.ArgumentParser(description="Amber RAG demo (Chroma + PDF + Ollama)")
    p.add_argument("--query", required=True)

    p.add_argument("--db-path", default="/opt/chromadb/data/prompt_db")
    p.add_argument("--pdf-path", default="Amber25.pdf")

    p.add_argument("--k-chroma", type=int, default=50)
    p.add_argument("--k-pdf", type=int, default=5)

    p.add_argument("--threshold-chroma", type=float, default=0.35)
    p.add_argument("--threshold-pdf", type=float, default=0.45)

    p.add_argument("--embedder", default="all-MiniLM-L6-v2")

    p.add_argument("--ollama-model", default="llama3.1:8b")
    p.add_argument("--temperature", type=float, default=0.2)

    args = p.parse_args()

    chunks = retrieve_with_pdf(
        question=args.query,
        db_path=args.db_path,
        pdf_path=args.pdf_path,
        embedder_name=args.embedder,
        k_chroma=args.k_chroma,
        k_pdf=args.k_pdf,
        threshold_chroma=args.threshold_chroma,
        threshold_pdf=args.threshold_pdf,
    )

    context = build_context(chunks)
    messages = build_prompt(args.query, context)
    answer = generate_ollama(messages, model=args.ollama_model, temperature=args.temperature)
    print(answer)


if __name__ == "__main__":
    main()