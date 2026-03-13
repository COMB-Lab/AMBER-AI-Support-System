import os
import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")

def chunk_text(text, size=700, overlap=100):
    chunks = []
    step = size - overlap

    for i in range(0, len(text), step):
        chunk = text[i:i + size]
        if chunk.strip():
            chunks.append(chunk)

    return chunks


def build_or_load_index(pdf_path):
    base = os.path.splitext(pdf_path)[0]
    index_path = base + ".faiss"
    chunks_path = base + ".chunks.npy"

    if os.path.exists(index_path) and os.path.exists(chunks_path):
        index = faiss.read_index(index_path)
        chunks = np.load(chunks_path, allow_pickle=True)
        return index, chunks

    reader = PdfReader(pdf_path)
    text = ""

    for page in reader.pages:
        try:
            t = page.extract_text()
            if t:
                text += t + "\n"
        except:
            pass

    chunks = chunk_text(text)

    embeddings = EMBEDDER.encode(chunks, convert_to_numpy=True).astype("float32")

    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, index_path)
    np.save(chunks_path, chunks)

    return index, chunks


def search_pdf(pdf_path, query, top_k=5):
    index, chunks = build_or_load_index(pdf_path)

    query_emb = EMBEDDER.encode([query], convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(query_emb)

    scores, indices = index.search(query_emb, top_k)

    results = []

    for idx in indices[0]:
        results.append({
            "text": chunks[idx],
            "metadata": {"doc_type": "tutorial_pdf"}
        })

    return results