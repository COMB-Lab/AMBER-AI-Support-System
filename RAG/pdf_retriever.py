import os
import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")


def chunk_text_with_pages(page_texts, size=700, overlap=100):
    chunks = []
    step = size - overlap

    for page_num, text in page_texts:
        for i in range(0, len(text), step):
            chunk = text[i:i + size]
            if chunk.strip():
                chunks.append({
                    "text": chunk,
                    "page": page_num,
                })

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
    page_texts = []

    for i, page in enumerate(reader.pages, start=1):
        try:
            t = page.extract_text()
            if t:
                page_texts.append((i, t))
        except Exception:
            pass

    chunks = chunk_text_with_pages(page_texts)

    texts = [c["text"] for c in chunks]
    embeddings = EMBEDDER.encode(texts, convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, index_path)
    np.save(chunks_path, np.array(chunks, dtype=object))

    return index, np.array(chunks, dtype=object)


def search_pdf(pdf_path, query, top_k=5, pdf_title="Amber25 Reference Manual", pdf_url=""):
    index, chunks = build_or_load_index(pdf_path)

    query_emb = EMBEDDER.encode([query], convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(query_emb)

    scores, indices = index.search(query_emb, top_k)

    results = []
    for idx, score in zip(indices[0], scores[0]):
        chunk = chunks[idx].item() if hasattr(chunks[idx], "item") else chunks[idx]
        results.append({
            "text": chunk["text"],
            "metadata": {
                "doc_type": "tutorial_pdf",
                "title": pdf_title,
                "url": pdf_url,
                "page": chunk["page"],
            },
            "similarity": float(score),
        })

    return results