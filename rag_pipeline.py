import os
from typing import List, Dict
import numpy as np
import faiss
from pypdf import PdfReader
import chromadb
from sentence_transformers import SentenceTransformer
import ollama

os.environ["CUDA_VISIBLE_DEVICES"] = "" 
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

PDF_ADDRESS = "Amber25.pdf"
threshold_PDF = 0.45

class AmberChromaAPI:
    def __init__(self, db_path="/opt/chromadb/data/prompt_db", collection_name="amber_messages"):
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
    
# Chunking
def chunk_text(text, size=700, overlap=100):
    """
    Splits long text into overlapping chunks.

    Parameters:
        text (str): Full document text.
        size (int): Maximum characters per chunk.
        overlap (int): Number of overlapping characters between chunks.

    Returns:
        list[str]: List of text chunks.
    """
    # Store generated chunks
    chunks = []

    # Step size to maintain overlap
    step = size - overlap

    # Iterate over text using sliding window
    for i in range(0, len(text), step):
        # Extract chunk of fixed size
        chunk = text[i:i + size]
        # Skip empty/whitespace chunks
        if chunk.strip():
            chunks.append(chunk)

    # Return all chunks
    return chunks

# Build or Load FAISS Index
def build_or_load_index(pdf_path, chunk_size=700, overlap=100):
    """
    Builds a FAISS vector index from a PDF file or loads an existing one.

    Steps:
    1. Check if FAISS index already exists.
    2. If yes → load index and chunks.
    3. If no → extract text from PDF.
    4. Chunk text into overlapping pieces.
    5. Generate embeddings.
    6. Normalize embeddings for cosine similarity.
    7. Build FAISS index and save to disk.

    Returns:
        index (faiss.Index): FAISS search index.
        chunks (list[str]): Corresponding text chunks.
    """

    # Remove .pdf extension
    base_name = os.path.splitext(pdf_path)[0]
    # Path to saved FAISS index
    index_path = base_name + ".faiss"
    # Path to saved chunks
    chunks_path = base_name + ".chunks.npy"

    # Load if already exists
    if os.path.exists(index_path) and os.path.exists(chunks_path):
        # Load FAISS index
        index = faiss.read_index(index_path)
        # Load chunks
        chunks = np.load(chunks_path, allow_pickle=True)
        # Return loaded objects
        return index, chunks

    # If no saved index → build new one
    reader = PdfReader(pdf_path)
    # Store extracted text
    text = ""

    # Loop through all pages
    for i, page in enumerate(reader.pages):
        try:
            # Extract page text
            extracted = page.extract_text()
            # Append to full text
            if extracted:
                text += extracted + "\n"
        except Exception:
            print(f"Skipped unreadable page {i}")

    # Split text into overlapping chunks
    chunks = chunk_text(text, chunk_size, overlap)

    # Generate embeddings for all chunks
    embeddings = EMBEDDER.encode(
        chunks,
        batch_size=32,
        convert_to_numpy=True,
        show_progress_bar=True
    )

    embeddings = np.asarray(embeddings, dtype=np.float32)
    embeddings = np.ascontiguousarray(embeddings)

    # Normalize embeddings for cosine similarity search
    faiss.normalize_L2(embeddings)

    # Get embedding dimension
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    # Save index and chunks to disk
    faiss.write_index(index, index_path)
    np.save(chunks_path, chunks)

    return index, chunks

# Search Function
def search_pdf(pdf_path, query, top_k=5, threshold=threshold_PDF):
    """
    Searches a PDF using FAISS similarity search.

    Steps:
    1. Load or build FAISS index.
    2. Embed the query.
    3. Normalize query embedding.
    4. Perform similarity search.
    5. Return top-k most similar chunks.

    Returns:
        list[dict]: List of matching chunks with similarity scores.
    """

    index, chunks = build_or_load_index(pdf_path)

    # Encode query into embedding
    query_embedding = EMBEDDER.encode(
        [query],
        convert_to_numpy=True
    )

    # Normalize for cosine similarity
    query_embedding = np.asarray(query_embedding, dtype=np.float32)
    query_embedding = np.ascontiguousarray(query_embedding)

    faiss.normalize_L2(query_embedding)

    scores, indices = index.search(query_embedding, min(top_k, len(chunks)))

    results = []

    for rank, idx in enumerate(indices[0], 1):
        similarity = float(scores[0][rank - 1])
        chunk_text = chunks[idx]

        if similarity < threshold:
            continue

        results.append({
            "text": chunk_text,
            "author": "Amber 25 Manual",
            "subject": f"PDF Section {idx}",
            "url": "Amber25.pdf",
            "similarity": similarity
        })

    return results

# Prompt Builder
SYSTEM_PROMPT = """
You are AmberRAG, an expert AI assistant specializing in the AMBER molecular dynamics suite
and AmberTools workflows.

You answer questions strictly using the provided Context (archive discussions and manuals).


CORE RULES-
1) Use ONLY the provided Context to generate your answer.
2) Do NOT use outside knowledge or prior training information.
3) You may logically reason based on information in the Context,
   but do NOT introduce new facts that are not supported by it.
4) If the Context contains relevant information, use it to answer as completely as possible.
5) Do NOT mention an Persona, Identity, or Role in your answer. 
6) Do NOT fabricate AMBER commands, flags, filenames, or parameter values.
7) Do NOT include citation markers, chunk labels, similarity scores,
   reference numbers, or metadata in your output.
8) Do NOT repeat metadata from the Context.

STYLE-
- Start with a clear, direct answer.
- Then provide a concise technical explanation.
- Include practical AMBER-specific guidance only if supported by the Context.
- Address multiple sub-questions in the same order asked.
- Be precise, professional, and focused.
- Avoid unnecessary verbosity.

Output only the final answer.
"""

def build_context(chunks, max_chars: int = 9000):
    """
    Builds a single context string from retrieved chunks for LLM input.

    Steps:
    1. Iterate through retrieved chunks (already ranked).
    2. Add citation-style headers for traceability.
    3. Concatenate chunk text with metadata.
    4. Stop when max character limit is reached.
    5. Return a formatted context block.

    Parameters:
        chunks (list[dict]): Retrieved documents with metadata.
        max_chars (int): Maximum total characters allowed.

    Returns:
        str: Combined context string ready for LLM.
    """
    parts, used = [], 0

    # Loop through ranked chunks
    for i, ch in enumerate(chunks, 1):
        # Create citation-style header with metadata
        header = (
            f"[CITE {i}] {ch['subject']} | {ch['author']} "
            f"| Link: {ch.get('url') or 'None'} "
        )
        body = (ch["text"] or "").strip()
        block = header + "\n" + body + "\n"
        # Stop if adding this block exceeds max character limit
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    
    # Join all blocks with separator for readability
    return "\n\n-----\n\n".join(parts)

def build_prompt(question: str, context: str) -> list:
    """
    Builds a structured chat prompt for a chat-based LLM.

    Steps:
    1. Add system-level instructions (SYSTEM_PROMPT).
    2. Provide retrieved context to ground the answer.
    3. Append the user’s question.
    4. Instruct the model to answer with citations.

    Parameters:
        question (str): User's question.
        context (str): Retrieved contextual information.

    Returns:
        list[dict]: Chat-formatted messages for LLM API.
    """

    return [
        # System message defines assistant behavior
        {"role": "system", "content": SYSTEM_PROMPT},

        # User message contains context + question
        {
            "role": "user",
            "content": (
                f"Context:\n{context}\n\n"
                f"Question: {question}\n\n"
                "Answer"
            )
        }
    ]

# LLM Integration
class OllamaLLM:
    def __init__(self, model_name="llama3.1:8b"):
        self.model_name = model_name
        print(f"Connected to Ollama. Using model: {model_name}")

    def generate(self, messages: list) -> str:
        try:
            response = ollama.chat(model=self.model_name, messages=messages)
            return response['message']['content']
        except Exception as e:
            return f"Error communicating with Ollama: {e}"

# Demo Workflow
if __name__ == "__main__":
    
    api = AmberChromaAPI(db_path="/opt/chromadb/data/prompt_db", collection_name="amber_messages")
    
    query = """
    I am learning how to use cpptraj of Amber 16 to wrap the protein and water into the box. I am using the cellulose system from the Amber benchmark. The topology, restart and input files were downloaded from the Amber benchmark website. After cpptraj, water molecules were wrapped back into the box but the protein was not in the center. And it seems that the bottom of the box was moved to the top.


    My cpptraj input(rst.cpptraj file):

    trajin inpcrd

    autoimage


    cpptraj command:

    $AMBERHOME/bin/cpptraj -p prmtop -i rst.cpptraj &>rstcpp.log -x out.crd
    """
    
    print(f"Searching for: '{query}'...")
    
    results = api.query(query, n=5, threshold=0.2)

    chunks = []

    for doc, meta, score in zip(results["documents"], results["metadatas"], results["scores"]):
        subject = meta.get("subject") or "No Subject"
        author = meta.get("author") or "Amber Community"
        url = meta.get("url") or "None"

        chunks.append({
            "text": doc,
            "author": author,
            "subject": subject,
            "url": url,
            "similarity": score
        })
    
    print(f"-> ChromaDB returned {len(chunks)} useful chunks.")
    
    print(f"\nQuerying FAISS (PDF Manual) for: '{query[:50]}...'")
    pdf_chunks = search_pdf(PDF_ADDRESS, query, top_k=5, threshold=threshold_PDF)
    print(f"-> FAISS returned {len(pdf_chunks)} useful chunks.")

    all_chunks = chunks + pdf_chunks
    all_chunks = sorted(all_chunks, key=lambda x: x["similarity"], reverse=True)
    all_chunks = all_chunks[:5]

    if not all_chunks:
        print("No relevant documents found in ChromaDB or the PDF.")
        exit()

    print(f"\nBuilding context from {len(all_chunks)} combined documents...")

    context_string = build_context(all_chunks)
    
    messages = build_prompt(query, context_string)

    llm = OllamaLLM(model_name="llama3.1:8b")
    answer = llm.generate(messages)

    unique_sources = []
    for c in all_chunks:
        src_string = f"Subject: {c['subject']} | Author: {c['author']} | Link: {c['url']}"
        if src_string not in unique_sources:
            unique_sources.append(src_string)

    print("\n" + "="*40)
    print(f"ANSWER: {answer}")
    print("Sources:")
    for i, src in enumerate(unique_sources[:5], 1):
        print(f"[{i}] {src}")
    print("="*40)
