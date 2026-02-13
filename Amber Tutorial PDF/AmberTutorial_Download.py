"""
Attribution:
Embedding + search logic is based on a reference script provided by the project TA
(

What this script does:
1) Downloads Amber25.pdf (stores it locally)
2) Extracts text, chunks it, embeds it, and runs semantic search
"""

import requests
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer, util
import torch

# ----------------------------
# Download settings
# ----------------------------
PDF_URL = "https://ambermd.org/doc12/Amber25.pdf"
PDF_FILENAME = "Amber25.pdf"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/117.0.0.0 Safari/537.36"
}

# ----------------------------
# Embedder (TA)
# ----------------------------
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")


def download_pdf(url: str, filename: str) -> None:
    """Download and store the PDF locally."""
    print(f" Downloading: {url}")
    r = requests.get(url, headers=HEADERS, stream=True, timeout=60)
    if r.status_code != 200:
        print(" Download failed with status code:", r.status_code)
        raise SystemExit(1)

    with open(filename, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    print(f" Saved: {filename}")


# ----------------------------
# TA function to search PDF directly 
# ----------------------------
def search_pdf_directly(
    pdf_path: str,
    query: str,
    top_k: int = 5,
    chunk_size: int = 700,
    overlap: int = 100
):
    """
    Extracts text from a PDF and searches for passages semantically similar to a query,
    without adding anything to ChromaDB.
    """
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    print(f" Loading PDF: {pdf_path}")
    reader = PdfReader(pdf_path)

    text = ""
    for i, page in enumerate(reader.pages):
        try:
            # IMPORTANT FIX: extract_text() can return None
            text += (page.extract_text() or "") + "\n"
        except Exception:
            print(f" Skipped unreadable page {i}")

    print(f" Extracted {len(text)} characters from {len(reader.pages)} pages")

    # --- Chunking ---
    def chunk_text(text, size, overlap):
        chunks = []
        step = size - overlap
        for i in range(0, len(text), step):
            chunk = text[i:i + size]
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    chunks = chunk_text(text, chunk_size, overlap)
    print(f" Created {len(chunks)} chunks from PDF")

    # --- Encode query + chunks ---
    query_emb = EMBEDDER.encode(query, convert_to_tensor=True)
    chunk_embs = EMBEDDER.encode(chunks, convert_to_tensor=True)

    # --- Compute cosine similarities ---
    scores = util.cos_sim(query_emb, chunk_embs)[0]
    top_indices = torch.topk(scores, k=min(top_k, len(chunks))).indices

    # --- Display results ---
    print(f"\n Top {min(top_k, len(chunks))} matching passages:\n")
    for rank, idx in enumerate(top_indices, 1):
        print(f"\n=== PDF Result {rank} ===")
        print(f"Similarity: {scores[idx].item():.3f}")
        print(chunks[idx][:700].strip())
        print("=" * 80)

    # Return useful data if needed programmatically
    return [{"text": chunks[idx], "similarity": scores[idx].item()} for idx in top_indices]


# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    # 1) Store the PDF locally
    download_pdf(PDF_URL, PDF_FILENAME)

    # 2) Run embedding + semantic search (change the query to whatever you want)
    search_pdf_directly(
        pdf_path=PDF_FILENAME,
        query="Amber25 tutorial?",
        top_k=5
    )
