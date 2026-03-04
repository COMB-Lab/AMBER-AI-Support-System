#!/usr/bin/env python3
import argparse
from RAG.retriever import retrieve_with_pdf
from RAG.prompt_builder import build_context, build_prompt
from RAG.llm_interface import OllamaLLM


def run(
    query: str,
    db_path: str,
    collection: str,
    top_k_chroma: int,
    top_k_pdf: int,
    threshold_chroma: float,
    threshold_pdf: float,
    pdf_path: str | None,
    ollama_model: str,
    ollama_url: str,
    temperature: float,
):
    chunks = retrieve_with_pdf(
        question=query,
        db_path=db_path,
        collection_name=collection,
        k_chroma=top_k_chroma,
        k_pdf=top_k_pdf,
        threshold_chroma=threshold_chroma,
        threshold_pdf=threshold_pdf,
        pdf_path=pdf_path,
    )

    if not chunks:
        print(
            "No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket."
        )
        return

    context = build_context(chunks)
    messages = build_prompt(query, context)

    llm = OllamaLLM(model_name=ollama_model, base_url=ollama_url, temperature=temperature)
    answer = llm.generate(messages)

    print("\n--- LLM Response ---\n")
    print(answer)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)

    p.add_argument("--db-path", default="/opt/chromadb/data/amber_chroma_db")
    p.add_argument("--collection", default="amber_messages")

    p.add_argument("--top-k-chroma", type=int, default=50)
    p.add_argument("--top-k-pdf", type=int, default=5)

    p.add_argument("--threshold-chroma", type=float, default=0.35)
    p.add_argument("--threshold-pdf", type=float, default=0.45)

    p.add_argument("--pdf-path", default=None)

    p.add_argument("--ollama-model", default="llama3.1:8b")
    p.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    p.add_argument("--temperature", type=float, default=0.2)

    args = p.parse_args()

    run(
        query=args.query,
        db_path=args.db_path,
        collection=args.collection,
        top_k_chroma=args.top_k_chroma,
        top_k_pdf=args.top_k_pdf,
        threshold_chroma=args.threshold_chroma,
        threshold_pdf=args.threshold_pdf,
        pdf_path=args.pdf_path,
        ollama_model=args.ollama_model,
        ollama_url=args.ollama_url,
        temperature=args.temperature,
    )