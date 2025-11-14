# RAG/demo_workflow.py
import os
import sys
import re
import argparse

# Ensure parent directory is on path (so RAG.* imports work)
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

# Silence Chroma telemetry noise
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMADB_TELEMETRY_IMPLEMENTATION", "none")

from RAG.retriever import AmberRetriever
from RAG.prompt_builder import build_prompt
from RAG.llm_interface import LLM

DEFN_OR_CLUSTER_RE = re.compile(r"^(what is|summarize|define|briefly)\b|\bcluster|clustering\b", re.I)

def run(query: str,
        db_path: str,
        collection: str,
        top_k: int,
        threshold: float,
        model: str):
    use_context = not DEFN_OR_CLUSTER_RE.search(query.strip())
    contexts = []
    if use_context:
        retr = AmberRetriever(db_path=db_path, collection=collection, top_k=top_k, threshold=threshold)
        hits = retr.retrieve(query)
        contexts = [h["text"] for h in hits]

    prompt = build_prompt(query, contexts)
    llm = LLM(model_name=model, max_new_tokens=128, temperature=0.0, use_device_map=False)
    answer = llm.generate(prompt)
    print(answer)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--db-path", default="/opt/chromadb/data/amber_chroma_db")
    parser.add_argument("--collection", default="amber_messages")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--model", default="google/flan-t5-base")
    args = parser.parse_args()
    run(args.query, args.db_path, args.collection, args.top_k, args.threshold, args.model)