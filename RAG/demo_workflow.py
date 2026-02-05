# RAG/demo_workflow.py
import os, sys, re, argparse

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMADB_TELEMETRY_IMPLEMENTATION", "none")

from RAG.retriever import AmberRetriever
from RAG.prompt_builder import build_prompt
from RAG.llm_interface import LLM

DEFN_RE = re.compile(r"^(what is|summarize|define|briefly)\b", re.I)

def run(query, db_path, collection, top_k, threshold, model):
    use_context = not DEFN_RE.match(query.strip())

    contexts = []
    if use_context:
        retr = AmberRetriever(db_path=db_path, collection=collection, top_k=top_k, threshold=threshold)
        hits = retr.retrieve(query)
        contexts = [h["text"] for h in hits]

    prompt = build_prompt(query, contexts)
    llm = LLM(model_name=model, max_new_tokens=256, temperature=0.0, use_device_map=False)
    print(llm.generate(prompt))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--db-path", default="/opt/chromadb/data/amber_chroma_db")
    p.add_argument("--collection", default="amber_messages")
    p.add_argument("--top-k", type=int, default=6)
    p.add_argument("--threshold", type=float, default=0.15)
    p.add_argument("--model", default="meta-llama/Llama-2-7b-chat-hf")
    args = p.parse_args()
    run(args.query, args.db_path, args.collection, args.top_k, args.threshold, args.model)