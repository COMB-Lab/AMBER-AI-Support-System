from dataclasses import dataclass
from typing import List
from transformers import pipeline
from sentence_transformers import SentenceTransformer, util
import chromadb
import json

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
    def __init__(self, db_path="/opt/chromadb/data", collection_name="amber_chroma_db"):
        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_collection(collection_name)
        self.docs = []

    def load_documents(self, limit: int = 400) -> List[str]:
        try:
            results = self.collection.get(limit=limit)
        except Exception as e:
            print("Error retrieving from ChromaDB:", e)
            return []
        
        documents = results.get("documents", [])
        self.docs = documents
        print(f"Loaded {len(documents)} documents from '{self.collection.name}' collection.")
        return documents

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

# Semantic Filter
class SemanticFilter:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def filter(self, query: str, documents: List[str], top_k: int = 5) -> List[str]:
        if not documents:
            print("No documents to search.")
            return []
        
        doc_embeddings = self.model.encode(documents, convert_to_tensor=True)
        query_embedding = self.model.encode(query, convert_to_tensor=True)
        hits = util.semantic_search(query_embedding, doc_embeddings, top_k=top_k)[0]
        return [documents[h['corpus_id']] for h in hits]

# Prompt Builder
def build_prompt(query: str, retrieved_docs: List[str], max_chars: int = 2000) -> str:
    context = "\n".join(retrieved_docs)
    if len(context) > max_chars:
        context = context[:max_chars] + "..."
    return f"Context:\n{context}\n\nQuestion: {query}"

# LLM Integration
class HuggingFaceLLM:
    def __init__(self, model_name="google/flan-t5-large"):
        self.generator = pipeline("text2text-generation", model=model_name)

    def generate(self, prompt: str) -> str:
        result = self.generator(prompt, max_new_tokens=100)
        return result[0]["generated_text"]

# Demo Workflow
if __name__ == "__main__":
    
    retriever = ChromaRetriever(db_path="/opt/chromadb/data", collection_name="amber_chroma_db")
    documents = retriever.load_documents(limit=30)

    if not documents:
        print("No documents found.")
        exit()

    query = "Is there a way to define a repulsive potential between the two proteins without specifying a specific pulling direction?"
    query_understanding = QueryUnderstanding()
    query_info = query_understanding.process(query)

    print("\nQuery Understanding:")
    print(f"Normalized Query: {query_info['query']}")
    print(f"Detected Intent: {query_info['top_label']}")
    print("Scores: ", json.dumps(query_info["scores"], indent=2))
    
    semantic_filter = SemanticFilter()

    retrieved_docs = semantic_filter.filter(query, documents, top_k=3)
    
    print("\nRetrieved docs:")
    for doc in retrieved_docs:
        print("-", doc[:500].replace("\n", " "), "\n")

    prompt = build_prompt(query, retrieved_docs)
    print("\nPrompt sent to LLM:\n", prompt)

    llm = HuggingFaceLLM()
    answer = llm.generate(prompt)

    print("\nAnswer:\n", answer)