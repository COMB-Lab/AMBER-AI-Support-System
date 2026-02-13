import os
import sys
import json
import torch
from dataclasses import dataclass
from typing import List, Dict
import chromadb
from sentence_transformers import SentenceTransformer
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM, AutoModelForCausalLM

os.environ["CUDA_VISIBLE_DEVICES"] = "" 
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

class AmberChromaAPI:
    def __init__(self, db_path="./amber_chroma_db", collection_name="amber_messages"):
        """Initialize a persistent ChromaDB client in a local folder."""
        os.makedirs(db_path, exist_ok=True)
        print(f"Using local ChromaDB path: {os.path.abspath(db_path)}")
        self.db_path = db_path

        self.client = chromadb.PersistentClient(path=db_path)

        # Use cosine similarity for text embeddings
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        
    def query(self, text, n=5, where=None, threshold=0.75):
        """Run a semantic search and apply a similarity threshold."""
        embedding = EMBEDDER.encode(text).tolist()
        print(f"\nQuerying for: '{text}'")

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n,
            where=where if where is not None else None,
            include=["documents", "metadatas", "distances"]
        )

        total_found = len(results.get("documents", [[]])[0])
        print(f"Found {total_found} total results before filtering")

        filtered_docs, filtered_metas, filtered_scores = [], [], []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            similarity = 1 - dist
            if similarity >= threshold:
                filtered_docs.append(doc)
                filtered_metas.append(meta)
                filtered_scores.append(similarity)

        print(f"{len(filtered_docs)} results kept (similarity ≥ {threshold})")
        return {
            "documents": filtered_docs,
            "metadatas": filtered_metas,
            "scores": filtered_scores,
        }

# Prompt Builder
def build_prompt(query: str, docs: List[str], metas: List[Dict]) -> str:
    context_text = ""
    for doc, meta in zip(docs, metas):
        url = meta.get("url") or meta.get("page_url") or "No Link"
        author = meta.get("author") or "Unknown"
        context_text += f"[Author: {author} | Link: {url}]\n{doc}\n\n"

    return (
        f"Question: {query}\n\n"
        f"Use the provided context to answer the question.\n\n"
        f"Provide a direct solution or explanation. Where applicable, structure the answer as a clear, step-by-step solution.\n\n"
        f"Always cite the author or source link in your answer.\n\n"
        f"Context:\n{context_text}\n\n"
        f"Answer:"
    )

# LLM Integration
class HuggingFaceLLM:
    def __init__(self, model_path="meta-llama/llama-2-7b-chat-hf"):
        print(f"Loading LLaMA from {model_path}...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                device_map="auto",
                torch_dtype=torch.float16,
                local_files_only=True
            )
        except Exception as e:
            print(f"CRITICAL ERROR: Could not load LLaMA. {e}")
            print("Make sure the path is correct and you have 'accelerate' installed.")
            sys.exit(1)

    def generate(self, prompt: str) -> str:
        formatted_prompt = f"[INST] {prompt} [/INST]"
        
        inputs = self.tokenizer(formatted_prompt, return_tensors="pt").to("cuda")
        
        outputs = self.model.generate(
            **inputs, 
            max_new_tokens=512,
            temperature=0.1,
            do_sample=True
        )
        
        full_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        if "[/INST]" in full_text:
            return full_text.split("[/INST]")[-1].strip()
        return full_text

# Demo Workflow
if __name__ == "__main__":
    
    api = AmberChromaAPI(db_path="/opt/chromadb/data", collection_name="amber_messages")
    
    query = "Is there a way to define a repulsive potential between the two proteins?"
    
    print(f"Searching for: '{query}'...")
    
    results = api.query(query, n=3, threshold=0.2)
    
    docs = results["documents"]
    metas = results["metadatas"]
    scores = results["scores"]
    
    if not docs:
        print("No documents found.")
        exit()
    
    print(f"Found {len(docs)} relevant documents.")
    
    prompt = build_prompt(query, docs, metas)
    
    llm = HuggingFaceLLM()
    answer = llm.generate(prompt)

    print("\n" + "="*40)
    print(f"ANSWER: {answer}")
    print("="*40)
    
    print("\nSources Used:")
    for i, meta in enumerate(metas):
        url = meta.get("url") or meta.get("page_url") or "No Link"
        print(f"- {url} (Relevance: {scores[i]:.2f})")
