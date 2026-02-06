from dataclasses import dataclass
from typing import List
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import chromadb
import json
import sys

# Data Schema
@dataclass
class Message:
    message_id: str
    author: str
    date_raw: str
    body: str
    url: str

@dataclass
class Thread:
    thread_id: str
    subject: str
    messages: List[Message]

# Retriever
class ChromaRetriever:
    def __init__(self, db_path="/opt/chromadb/data", collection_name="amber_messages"):
        self.db_path = db_path
        try:
            self.client = chromadb.PersistentClient(path=db_path)
            self.collection = self.client.get_collection(collection_name)
        except Exception as e:
            print(f"Error connecting to ChromaDB: {e}")
            sys.exit(1)

    def retrieve(self, query: str, top_k: int = 5) -> List[str]:
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k
            )
            if results and results['documents']:
                return results['documents'][0]
        except Exception as e:
            print("Error retrieving from ChromaDB:", e)
            return []
        
        return []

# Query Understanding
class QueryUnderstanding:
    def __init__(self, model_name: str = "facebook/bart-large-mnli"):
        self.classifier = pipeline("zero-shot-classification", model=model_name)

    def normalize(self, query: str) -> str:
        return query.strip().replace("\n", " ").lower()

    def classify(self, query: str) -> dict:
        candidate_labels = [
            "Technical Question",
            "Concept Explanation",
            "Error Troubleshooting",
            "Software Usage",
            "General Discussion",
        ]
        result = self.classifier(query, candidate_labels)
        return {
            "query": query,
            "top_label": result["labels"][0],
            "scores": dict(zip(result["labels"], result["scores"])),
        }

    def process(self, query: str) -> dict:
        normalized = self.normalize(query)
        classification = self.classify(normalized)
        return classification

# Prompt Builder
def build_prompt(query: str, retrieved_docs: List[str], max_chars: int = 1500) -> str:
    context = "\n".join(retrieved_docs)
    if len(context) > max_chars:
        context = context[:max_chars] + "..."
    return (
        f"Question: {query}\n\n"
        f"Read the context and find the specific answer to the question. "
        f"Write a full sentence explaining the answer based on the text.\n\n"
        f"Context: {context}\n\n"
        f"Answer:"
    )

# LLM Integration
class HuggingFaceLLM:
    def __init__(self, model_name="google/flan-t5-large"):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    def generate(self, prompt: str) -> str:
        inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
        outputs = self.model.generate(**inputs, max_new_tokens=200)
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)

# Demo Workflow
if __name__ == "__main__":
    
    retriever = ChromaRetriever(db_path="/opt/chromadb/data", collection_name="amber_messages")
    
    query = "Is there a way to define a repulsive potential between the two proteins without specifying a specific pulling direction?"
    
    query_understanding = QueryUnderstanding()
    query_info = query_understanding.process(query)

    print("\nQuery Understanding:")
    print(f"Normalized Query: {query_info['query']}")
    print(f"Detected Intent: {query_info['top_label']}")
    print("Scores: ", json.dumps(query_info["scores"], indent=2))
    
    retrieved_docs = retriever.retrieve(query, top_k=3)
    
    if not retrieved_docs:
        print("No documents found.")
        exit()
    
    print("\nRetrieved docs:")
    for doc in retrieved_docs:
        print("-", doc[:500].replace("\n", " "), "\n")

    prompt = build_prompt(query, retrieved_docs)
    print("\nPrompt sent to LLM:\n", prompt)

    llm = HuggingFaceLLM()
    answer = llm.generate(prompt)

    print("\nAnswer:\n", answer)