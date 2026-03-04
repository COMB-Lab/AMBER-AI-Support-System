from RAG.retriever import AmberRetriever
from RAG.prompt_builder import build_prompt, build_context
from RAG.llm_interface import OllamaLLM

def run(query: str, db_path: str = "/opt/chromadb/data/prompt_db", top_k: int = 8):
    retr = AmberRetriever(db_path=db_path, top_k=top_k)
    hits = retr.retrieve(query)
    if not hits:
        print("No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket.")
        return
    chunks = [h["text"] for h in hits]
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
    args = p.parse_args()
    run(args.query, db_path=args.db_path, top_k=args.top_k)