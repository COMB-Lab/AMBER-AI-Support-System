#!/usr/bin/env python3
"""Download Amber tutorials PDF and store with embeddings for RAG.

This script:
1. Downloads the PDF from the specified URL
2. Extracts text per page using pdfplumber
3. Chunks the text for embedding
4. Generates embeddings (OpenAI or local)
5. Stores chunks in Chroma vector database

Usage:
    python scripts/download_amber_pdf_with_embeddings.py \
        --url https://ambermd.org/doc12/Amber25.pdf \
        --collection amber_tutorials

Environment variables:
    OPENAI_API_KEY: for OpenAI embeddings (optional)
    CHROMA_SERVER_HOST: Chroma server host (optional, defaults to local)
    CHROMA_SERVER_HTTP_PORT: Chroma server port (optional, defaults to 8000)

Outputs:
    data/pdfs/<slug>/Amber25.pdf - raw PDF
    data/pdfs/<slug>/metadata.json - PDF metadata with page count
    Chroma collection with embedded chunks
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import List, Dict, Tuple
from urllib.parse import urlparse

import requests


def slug_from_url(url: str) -> str:
    """Generate a slug from URL path."""
    p = urlparse(url)
    name = Path(p.path).stem.lower()
    return name or "pdf_doc"


def ensure_dirs(path: Path):
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_pdf(url: str, out_path: Path) -> Path:
    """Download PDF from URL and save to out_path."""
    print(f"Downloading PDF from {url}...")
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    ensure_dirs(out_path.parent)
    
    total_size = int(r.headers.get('content-length', 0))
    downloaded = 0
    
    with out_path.open("wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    pct = (downloaded / total_size) * 100
                    print(f"  {pct:.1f}%", end="\r")
    
    print(f"Downloaded {downloaded} bytes")
    return out_path


def extract_text_from_pdf(pdf_path: Path) -> Tuple[List[Dict], int]:
    """Extract text from PDF using pdfplumber or fallback to pypdf.
    
    Returns:
        Tuple of (list of {page_num, text}, total_pages)
    """
    try:
        import pdfplumber
        pages_data = []
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"Extracting text from {total_pages} pages...")
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                pages_data.append({
                    "page_num": page_num,
                    "text": text
                })
                print(f"  Page {page_num + 1}/{total_pages}")
        return pages_data, total_pages
    except ImportError:
        print("pdfplumber not found, trying pypdf...")
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf_path)
            total_pages = len(reader.pages)
            pages_data = []
            print(f"Extracting text from {total_pages} pages...")
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                pages_data.append({
                    "page_num": page_num,
                    "text": text
                })
                print(f"  Page {page_num + 1}/{total_pages}")
            return pages_data, total_pages
        except ImportError:
            raise RuntimeError("pdfplumber or pypdf required for text extraction")


def chunk_text(text: str, max_chunk_size: int = 2000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks.
    
    Args:
        text: Text to chunk
        max_chunk_size: Maximum characters per chunk
        overlap: Overlap between chunks in characters
    
    Returns:
        List of text chunks
    """
    chunks = []
    if len(text) <= max_chunk_size:
        return [text]
    
    start = 0
    while start < len(text):
        end = min(start + max_chunk_size, len(text))
        # Try to break at a sentence boundary
        if end < len(text):
            last_period = text.rfind(".", start + max_chunk_size - 500, end)
            if last_period > start:
                end = last_period + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap
    
    return chunks


def get_openai_embeddings(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    """Generate embeddings using OpenAI API."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package required for embeddings")
    
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY not set')
    
    client = OpenAI(api_key=api_key)
    print(f"Generating embeddings for {len(texts)} chunks using {model}...")
    
    resp = client.embeddings.create(input=texts, model=model)
    embeddings = [r.embedding for r in resp.data]
    print(f"Generated {len(embeddings)} embeddings")
    return embeddings


def get_local_embeddings(texts: List[str], model: str = "all-MiniLM-L6-v2") -> List[List[float]]:
    """Generate embeddings using local sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError("sentence-transformers package required for local embeddings")
    
    print(f"Loading local embedding model: {model}...")
    st_model = SentenceTransformer(model)
    print(f"Generating embeddings for {len(texts)} chunks...")
    embeddings = st_model.encode(texts, show_progress_bar=True)
    return embeddings.tolist()


def create_chroma_client():
    """Create Chroma client (local or remote)."""
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        raise RuntimeError("chromadb package required")
    
    host = os.environ.get('CHROMA_SERVER_HOST')
    port = os.environ.get('CHROMA_SERVER_HTTP_PORT')
    
    if host:
        port = int(port) if port else 8000
        print(f"Connecting to remote Chroma at {host}:{port}...")
        settings = Settings(
            chroma_api_impl="rest",
            chroma_server_host=host,
            chroma_server_http_port=port
        )
        client = chromadb.Client(settings)
    else:
        print("Using local Chroma client...")
        client = chromadb.Client()
    
    return client


def store_chunks_in_chroma(
    chunks_with_metadata: List[Dict],
    collection_name: str,
    use_openai: bool = False
):
    """Store chunks with embeddings in Chroma.
    
    Args:
        chunks_with_metadata: List of {id, text, metadata}
        collection_name: Name of Chroma collection
        use_openai: Use OpenAI embeddings (default: local)
    """
    if not chunks_with_metadata:
        print("No chunks to store")
        return
    
    client = create_chroma_client()
    
    # Get or create collection
    try:
        collection = client.get_collection(collection_name)
        print(f"Using existing collection: {collection_name}")
    except Exception:
        collection = client.create_collection(collection_name)
        print(f"Created new collection: {collection_name}")
    
    # Extract data
    ids = [c['id'] for c in chunks_with_metadata]
    texts = [c['text'] for c in chunks_with_metadata]
    metadatas = [c['metadata'] for c in chunks_with_metadata]
    
    # Generate embeddings
    if use_openai:
        embeddings = get_openai_embeddings(texts)
    else:
        embeddings = get_local_embeddings(texts)
    
    # Upsert into Chroma
    print(f"Storing {len(ids)} chunks in Chroma collection '{collection_name}'...")
    collection.upsert(
        ids=ids,
        documents=texts,
        metadatas=metadatas,
        embeddings=embeddings
    )
    print(f"Successfully stored {len(ids)} chunks")


def main():
    parser = argparse.ArgumentParser(
        description="Download Amber PDF and store with embeddings for RAG"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="PDF URL to download"
    )
    parser.add_argument(
        "--collection",
        default="amber_tutorials",
        help="Chroma collection name"
    )
    parser.add_argument(
        "--out-root",
        default="data",
        help="Output root directory"
    )
    parser.add_argument(
        "--use-openai",
        action="store_true",
        help="Use OpenAI embeddings instead of local model"
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=2000,
        help="Maximum characters per chunk"
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Overlap between chunks in characters"
    )
    parser.add_argument(
        "--skip-chroma",
        action="store_true",
        help="Skip storing in Chroma (only download and chunk)"
    )
    
    args = parser.parse_args()
    
    # Setup paths
    url = args.url
    slug = slug_from_url(url)
    out_root = Path(args.out_root)
    pdf_dir = out_root / "pdfs" / slug
    ensure_dirs(pdf_dir)
    
    pdf_name = Path(urlparse(url).path).name or f"{slug}.pdf"
    pdf_path = pdf_dir / pdf_name
    
    # Download PDF
    if not pdf_path.exists():
        download_pdf(url, pdf_path)
    else:
        print(f"PDF already exists at {pdf_path}, skipping download")
    
    # Verify integrity
    sha = sha256_file(pdf_path)
    print(f"PDF SHA256: {sha}")
    
    # Extract text
    pages_data, total_pages = extract_text_from_pdf(pdf_path)
    
    # Create chunks with metadata
    chunks_with_metadata = []
    chunk_id_counter = 0
    
    for page_data in pages_data:
        page_num = page_data['page_num']
        text = page_data['text']
        
        # Skip mostly-empty pages
        if not text.strip():
            continue
        
        page_chunks = chunk_text(
            text,
            max_chunk_size=args.chunk_size,
            overlap=args.chunk_overlap
        )
        
        for chunk_idx, chunk_text_content in enumerate(page_chunks):
            chunk_id = f"{slug}_p{page_num:04d}_c{chunk_idx:03d}"
            chunks_with_metadata.append({
                'id': chunk_id,
                'text': chunk_text_content,
                'metadata': {
                    'source_url': url,
                    'page': page_num + 1,
                    'chunk_index': chunk_idx,
                    'pdf_filename': pdf_name,
                }
            })
            chunk_id_counter += 1
    
    print(f"Created {chunk_id_counter} chunks from {total_pages} pages")
    
    # Save metadata
    metadata = {
        "url": url,
        "filename": str(pdf_path.name),
        "sha256": sha,
        "page_count": total_pages,
        "chunk_count": chunk_id_counter,
    }
    
    metadata_path = pdf_dir / "metadata.json"
    with metadata_path.open("w", encoding="utf8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"Saved metadata to {metadata_path}")
    
    # Store in Chroma
    if not args.skip_chroma:
        # Check if embeddings are available
        if args.use_openai:
            if not os.environ.get('OPENAI_API_KEY'):
                print("Warning: OPENAI_API_KEY not set, using local embeddings instead")
                args.use_openai = False
        else:
            try:
                import sentence_transformers
            except ImportError:
                print("Installing sentence-transformers for local embeddings...")
                import subprocess
                subprocess.check_call([
                    "pip", "install", "sentence-transformers"
                ])
        
        store_chunks_in_chroma(
            chunks_with_metadata,
            args.collection,
            use_openai=args.use_openai
        )
    
    print("\nDone! Summary:")
    print(f"  PDF: {pdf_path}")
    print(f"  Pages: {total_pages}")
    print(f"  Chunks: {chunk_id_counter}")
    print(f"  Collection: {args.collection}")
    print(f"  Metadata: {metadata_path}")


if __name__ == "__main__":
    main()
