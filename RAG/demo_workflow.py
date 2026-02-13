# RAG/demo_workflow.py

import argparse
from RAG.retriever import ChromaRetriever
from RAG.prompt_builder import build_context, build_prompt
from RAG.llm_interface import OllamaLLM


def run(query: str, top_k: int):
    retriever = ChromaRetriever(top_k=top_k)
    chunks = retriever.retrieve(query)

    if not chunks:
        print(
            "No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket."
        )
        return

    context = build_context(chunks)
    messages = build_prompt(query, context)

    llm = OllamaLLM()
    answer = llm.generate(messages)

    print("\n--- LLM Response ---\n")
    print(answer)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    run(args.query, args.top_k)