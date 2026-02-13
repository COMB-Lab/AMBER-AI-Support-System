import os
import requests
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer, util
import torch

EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")


def download_pdf(url: str) -> str:
    response = requests.get(url, stream=True)
    pdf_file_name = os.path.basename(url)

    if response.status_code == 200:
        filepath = os.path.join(os.getcwd(), pdf_file_name)
        with open(filepath, 'wb') as pdf_object:
            pdf_object.write(response.content)
            print(f'{pdf_file_name} was successfully saved!')
            return filepath
    else:
        print(f'Could not download {pdf_file_name},')
        print(f'HTTP response status code: {response.status_code}')
        return None


def search_pdf_directly(pdf_path: str, query: str, top_k: int = 5, chunk_size: int = 700, overlap: int = 100):
    print(f"Loading PDF: {pdf_path}")
    reader = PdfReader(pdf_path)
    text = ""
    for i, page in enumerate(reader.pages):
        try:
            text += page.extract_text() + "\n"
        except Exception:
            print(f"Skipped unreadable page {i}")

    print(f"Extracted {len(text)} characters from {len(reader.pages)} pages")

    def chunk_text(text, size, overlap):
        chunks = []
        for i in range(0, len(text), size - overlap):
            chunk = text[i:i + size]
            if chunk.strip():
                chunks.append(chunk)
        return chunks

    chunks = chunk_text(text, chunk_size, overlap)
    print(f"Created {len(chunks)} chunks from PDF")

    query_emb = EMBEDDER.encode(query, convert_to_tensor=True)
    chunk_embs = EMBEDDER.encode(chunks, convert_to_tensor=True)

    scores = util.cos_sim(query_emb, chunk_embs)[0]
    top_indices = torch.topk(scores, k=min(top_k, len(chunks))).indices

    print(f"\nTop {top_k} matching passages:\n")
    for i, idx in enumerate(top_indices, 1):
        print(f"\n=== PDF Result {i} ===")
        print(f"Similarity: {scores[idx].item():.3f}")
        print(chunks[idx][:700].strip())
        print("=" * 80)

    return [
        {"text": chunks[idx], "similarity": scores[idx].item()}
        for idx in top_indices
    ]


if __name__ == '__main__':
    URL = 'https://ambermd.org/doc12/Amber25.pdf'
    QUERY = "What are the installation requirements?"

    saved_path = download_pdf(URL)

    if saved_path:
        search_pdf_directly(saved_path, QUERY)