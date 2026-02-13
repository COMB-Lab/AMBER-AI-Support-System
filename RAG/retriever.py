import os
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer


def _import_AmberChromaAPI():
    """
    Try imports in a few common places:
    - notebook style: from database import AmberChromaAPI
    - your server style: /opt/chromadb/data/vector_db_maker.py
    """
    try:
        from database import AmberChromaAPI  # type: ignore
        return AmberChromaAPI
    except Exception:
        pass

    try:
        import sys
        sys.path.append("/opt/chromadb/data")
        from vector_db_maker import AmberChromaAPI  # type: ignore
        return AmberChromaAPI
    except Exception:
        pass

    raise ImportError(
        "Could not import AmberChromaAPI. Expected `database.py` on PYTHONPATH or "
        "`/opt/chromadb/data/vector_db_maker.py`."
    )


def chunk_text(text: str, size: int = 700, overlap: int = 100) -> List[str]:
    chunks: List[str] = []
    step = size - overlap
    for i in range(0, len(text), step):
        ch = text[i : i + size]
        if ch.strip():
            chunks.append(ch)
    return chunks


def build_or_load_index(
    pdf_path: str,
    embedder: SentenceTransformer,
    chunk_size: int = 700,
    overlap: int = 100,
) -> Tuple[faiss.Index, List[str]]:
    base_name, _ = os.path.splitext(pdf_path)
    index_path = base_name + ".faiss"
    chunks_path = base_name + ".chunks.npy"

    if os.path.exists(index_path) and os.path.exists(chunks_path):
        index = faiss.read_index(index_path)
        chunks = np.load(chunks_path, allow_pickle=True).tolist()
        return index, chunks

    reader = PdfReader(pdf_path)
    full_text = ""
    for i, page in enumerate(reader.pages):
        try:
            extracted = page.extract_text()
            if extracted:
                full_text += extracted + "\n"
        except Exception:
            print(f"Skipped unreadable page {i}")

    chunks = chunk_text(full_text, size=chunk_size, overlap=overlap)

    embeddings = embedder.encode(
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

    return index, chunks


def search_pdf(
    pdf_path: str,
    query: str,
    embedder: SentenceTransformer,
    top_k: int = 5,
    threshold: float = 0.45,
) -> List[Dict[str, Any]]:
    index, chunks = build_or_load_index(pdf_path, embedder)

    q_emb = embedder.encode([query], convert_to_numpy=True)
    q_emb = np.asarray(q_emb, dtype=np.float32)
    q_emb = np.ascontiguousarray(q_emb)
    faiss.normalize_L2(q_emb)

    scores, indices = index.search(q_emb, min(top_k, len(chunks)))

    out: List[Dict[str, Any]] = []
    for rank, idx in enumerate(indices[0], 1):
        sim = float(scores[0][rank - 1])
        if sim < threshold:
            continue
        out.append(
            {
                "text": chunks[idx],
                "author": "Amber Manual",
                "subject": os.path.basename(pdf_path),
                "date_iso": "",
                "similarity": sim,
                "source": "pdf",
            }
        )
    return out


def retrieve_chroma(
    db_path: str,
    question: str,
    k: int = 50,
    threshold: float = 0.2,
    where: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    AmberChromaAPI = _import_AmberChromaAPI()
    api = AmberChromaAPI(db_path=db_path)

    # The notebook's expected return:
    # results["documents"], results["metadatas"], results["scores"]
    results = api.query(text=question, n=k, where=where, threshold=threshold)

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
                "url": meta.get("url", ""),
            }
        )
    return out


def retrieve_with_pdf(
    question: str,
    db_path: str,
    pdf_path: str,
    embedder_name: str = "all-MiniLM-L6-v2",
    k_chroma: int = 50,
    k_pdf: int = 5,
    threshold_chroma: float = 0.35,
    threshold_pdf: float = 0.45,
) -> List[Dict[str, Any]]:
    embedder = SentenceTransformer(embedder_name)

    chroma_hits = retrieve_chroma(
        db_path=db_path,
        question=question,
        k=k_chroma,
        threshold=threshold_chroma,
    )

    pdf_hits: List[Dict[str, Any]] = []
    if pdf_path and os.path.exists(pdf_path):
        pdf_hits = search_pdf(
            pdf_path=pdf_path,
            query=question,
            embedder=embedder,
            top_k=k_pdf,
            threshold=threshold_pdf,
        )

    # Merge + sort by similarity desc (like notebook does)
    merged = chroma_hits + pdf_hits
    merged.sort(key=lambda x: float(x.get("similarity", 0.0)), reverse=True)
    return merged