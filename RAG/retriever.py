import os
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


def _get_amber_api_class():
    import sys
    sys.path.append("/opt/chromadb/data")
    from vector_db_maker import AmberChromaAPI
    return AmberChromaAPI


EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")


def retrieve_chroma(
    question: str,
    db_path: str,
    collection_name: str,
    k: int = 50,
    threshold: float = 0.35,
    where=None,
) -> List[Dict[str, Any]]:
    AmberChromaAPI = _get_amber_api_class()
    api = AmberChromaAPI(db_path=db_path, collection_name=collection_name)

    results = api.query(
        text=question,
        n=k,
        where=where,
        threshold=threshold,
    )

    documents = results.get("documents", [])
    metadatas = results.get("metadatas", [])
    scores = results.get("scores", [])

    out: List[Dict[str, Any]] = []
    for doc, meta, score in zip(documents, metadatas, scores):
        meta = meta or {}
        out.append(
            {
                "text": doc,
                "author": meta.get("author", "Unknown"),
                "subject": meta.get("subject", "(no subject)"),
                "date_iso": meta.get("date_iso", ""),
                "similarity": float(score),
                "source": "chroma",
            }
        )
    return out


def chunk_text(text: str, size: int = 700, overlap: int = 100) -> List[str]:
    chunks: List[str] = []
    step = size - overlap
    for i in range(0, len(text), step):
        chunk = text[i : i + size]
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def build_or_load_index(pdf_path: str, chunk_size: int = 700, overlap: int = 100) -> Tuple[faiss.Index, np.ndarray]:
    base_name = os.path.splitext(pdf_path)[0]
    index_path = base_name + ".faiss"
    chunks_path = base_name + ".chunks.npy"

    if os.path.exists(index_path) and os.path.exists(chunks_path):
        index = faiss.read_index(index_path)
        chunks = np.load(chunks_path, allow_pickle=True)
        return index, chunks

    reader = PdfReader(pdf_path)
    text = ""
    for i, page in enumerate(reader.pages):
        try:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        except Exception:
            print(f"Skipped unreadable page {i}")

    chunks = chunk_text(text, chunk_size, overlap)

    embeddings = EMBEDDER.encode(
        chunks,
        batch_size=32,
        convert_to_numpy=True,
        show_progress_bar=True,
    )

    embeddings = np.asarray(embeddings, dtype=np.float32)
    embeddings = np.ascontiguousarray(embeddings)
    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, index_path)
    np.save(chunks_path, np.array(chunks, dtype=object))

    return index, np.array(chunks, dtype=object)


def search_pdf(pdf_path: str, query: str, top_k: int = 5, threshold: float = 0.45) -> List[Dict[str, Any]]:
    index, chunks = build_or_load_index(pdf_path)

    query_embedding = EMBEDDER.encode([query], convert_to_numpy=True)
    query_embedding = np.asarray(query_embedding, dtype=np.float32)
    query_embedding = np.ascontiguousarray(query_embedding)
    faiss.normalize_L2(query_embedding)

    scores, indices = index.search(query_embedding, min(top_k, len(chunks)))

    results: List[Dict[str, Any]] = []
    for rank, idx in enumerate(indices[0], 1):
        similarity = float(scores[0][rank - 1])
        chunk_text_val = str(chunks[idx])

        if similarity < threshold:
            continue

        results.append(
            {
                "text": chunk_text_val,
                "author": "Amber Manual",
                "subject": f"PDF: {os.path.basename(pdf_path)}",
                "date_iso": "",
                "similarity": similarity,
                "source": "pdf",
            }
        )

    return results


def retrieve_with_pdf(
    question: str,
    db_path: str,
    collection_name: str,
    k_chroma: int = 50,
    k_pdf: int = 5,
    threshold_chroma: float = 0.35,
    threshold_pdf: float = 0.45,
    pdf_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []

    chroma_hits = retrieve_chroma(
        question=question,
        db_path=db_path,
        collection_name=collection_name,
        k=k_chroma,
        threshold=threshold_chroma,
    )
    chunks.extend(chroma_hits)

    if pdf_path and os.path.exists(pdf_path):
        pdf_hits = search_pdf(
            pdf_path=pdf_path,
            query=question,
            top_k=k_pdf,
            threshold=threshold_pdf,
        )
        chunks.extend(pdf_hits)

    chunks = sorted(chunks, key=lambda x: float(x.get("similarity", 0.0)), reverse=True)
    return chunks