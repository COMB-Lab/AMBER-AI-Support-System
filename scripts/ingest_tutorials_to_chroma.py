#!/usr/bin/env python3
"""Production-grade ingestion script for storing Amber tutorials in Chroma.

This script:
1. Reads chunked JSONL files from the tutorials scraper
2. Generates embeddings (local or OpenAI)
3. Stores chunks in ChromaDB (local or remote Mirzakhani instance)
4. Tracks provenance and metadata
5. Supports idempotent re-ingestion (upsert mode)

Usage:
    # Ingest to local Chroma with local embeddings:
    python scripts/ingest_tutorials_to_chroma.py --chunks-dir data/tutorials_chunks/
    
    # Ingest to remote Mirzakhani with OpenAI embeddings:
    $env:OPENAI_API_KEY = "sk-..."
    python scripts/ingest_tutorials_to_chroma.py \
        --chunks-dir data/tutorials_chunks/ \
        --collection amber_tutorials \
        --chroma-host http://mirzakhani:8000 \
        --use-openai \
        --batch-size 32

Environment:
    OPENAI_API_KEY: For OpenAI embeddings (optional)
    CHROMA_SERVER_HOST: Chroma server host (optional)
    CHROMA_SERVER_HTTP_PORT: Chroma server port (optional)
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('amber_tutorials_ingest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_openai_embeddings(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    """Generate embeddings using OpenAI API."""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package required: pip install openai")
    
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY environment variable not set')
    
    client = OpenAI(api_key=api_key)
    logger.info(f"Generating OpenAI embeddings for {len(texts)} chunks with model {model}")
    
    # OpenAI allows batch requests
    response = client.embeddings.create(input=texts, model=model)
    embeddings = [item.embedding for item in response.data]
    
    logger.info(f"Generated {len(embeddings)} embeddings")
    return embeddings


def get_local_embeddings(texts: List[str], model: str = "all-MiniLM-L6-v2") -> List[List[float]]:
    """Generate embeddings using local sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise RuntimeError("sentence-transformers package required: pip install sentence-transformers")
    
    logger.info(f"Loading local embedding model: {model}")
    st_model = SentenceTransformer(model)
    
    logger.info(f"Generating embeddings for {len(texts)} chunks")
    embeddings = st_model.encode(texts, show_progress_bar=True)
    
    return embeddings.tolist()


def create_chroma_client(host: Optional[str] = None, port: Optional[int] = None):
    """Create Chroma client (local or remote)."""
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        raise RuntimeError("chromadb package required: pip install chromadb")
    
    # Check environment variables if not provided
    host = host or os.environ.get('CHROMA_SERVER_HOST')
    port = port or (int(os.environ.get('CHROMA_SERVER_HTTP_PORT', '8000')) if os.environ.get('CHROMA_SERVER_HTTP_PORT') else 8000)
    
    if host:
        logger.info(f"Connecting to remote Chroma server at {host}:{port}")
        settings = Settings(
            chroma_api_impl="rest",
            chroma_server_host=host,
            chroma_server_http_port=port,
            allow_reset=False
        )
        try:
            client = chromadb.Client(settings)
            # Test connection
            client.heartbeat()
            logger.info("✓ Connected to Chroma server")
        except Exception as e:
            logger.error(f"Failed to connect to Chroma server at {host}:{port}")
            raise
    else:
        logger.info("Using local Chroma client")
        client = chromadb.Client()
    
    return client


def load_chunks_from_jsonl(jsonl_path: Path) -> List[Dict]:
    """Load chunks from JSONL file."""
    chunks = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
                chunks.append(doc)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON at line {line_num} in {jsonl_path}: {e}")
                continue
    
    return chunks


def ingest_chunks_to_chroma(
    chunks_files: List[Path],
    collection_name: str,
    client,
    use_openai: bool = False,
    batch_size: int = 64,
    upsert: bool = True
):
    """Ingest tutorial chunks into Chroma collection."""
    
    # Get or create collection
    try:
        collection = client.get_collection(collection_name)
        logger.info(f"Using existing collection: {collection_name}")
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"Created new collection: {collection_name}")
    
    total_ingested = 0
    
    for jsonl_file in chunks_files:
        logger.info(f"\nProcessing: {jsonl_file}")
        chunks = load_chunks_from_jsonl(jsonl_file)
        
        if not chunks:
            logger.warning(f"No chunks found in {jsonl_file}")
            continue
        
        logger.info(f"Loaded {len(chunks)} chunks")
        
        # Process in batches
        for batch_start in range(0, len(chunks), batch_size):
            batch_end = min(batch_start + batch_size, len(chunks))
            batch = chunks[batch_start:batch_end]
            
            ids = [c['id'] for c in batch]
            texts = [c['text'] for c in batch]
            metadatas = [c.get('metadata', {}) for c in batch]
            
            # Generate embeddings
            if use_openai:
                embeddings = get_openai_embeddings(texts)
            else:
                embeddings = get_local_embeddings(texts)
            
            # Upsert to collection
            try:
                if upsert:
                    collection.upsert(
                        ids=ids,
                        documents=texts,
                        metadatas=metadatas,
                        embeddings=embeddings
                    )
                    logger.info(f"  Upserted batch {batch_start//batch_size + 1}: {len(ids)} chunks")
                else:
                    collection.add(
                        ids=ids,
                        documents=texts,
                        metadatas=metadatas,
                        embeddings=embeddings
                    )
                    logger.info(f"  Added batch {batch_start//batch_size + 1}: {len(ids)} chunks")
                
                total_ingested += len(ids)
            except Exception as e:
                logger.error(f"Failed to ingest batch {batch_start//batch_size + 1}: {e}")
                continue
    
    return total_ingested


def load_and_ingest_manifest(
    manifest_path: Path,
    client,
    use_openai: bool = False,
    batch_size: int = 64
):
    """Load manifest and create metadata tracking collection."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning(f"Failed to load manifest: {e}")
        return
    
    # Create metadata collection for tracking tutorials
    try:
        meta_col = client.get_collection("amber_tutorials_metadata")
    except Exception:
        meta_col = client.create_collection("amber_tutorials_metadata")
    
    # Add tutorial metadata records
    for tutorial in manifest.get('scraped_tutorials', []):
        tutorial_id = f"meta_{tutorial['slug']}"
        tutorial_text = f"{tutorial['title']}\n{json.dumps(tutorial['metadata'])}"
        
        try:
            meta_col.upsert(
                ids=[tutorial_id],
                documents=[tutorial_text],
                metadatas=[{
                    'title': tutorial['title'],
                    'url': tutorial['url'],
                    'slug': tutorial['slug'],
                    'chunks_count': tutorial['chunks_count'],
                    **tutorial['metadata']
                }]
            )
        except Exception as e:
            logger.error(f"Failed to add metadata for {tutorial['slug']}: {e}")
    
    logger.info(f"✓ Stored metadata for {len(manifest.get('scraped_tutorials', []))} tutorials")


def main():
    parser = argparse.ArgumentParser(
        description='Ingest Amber tutorials into Chroma'
    )
    parser.add_argument(
        '--chunks-dir',
        type=str,
        default='data/tutorials_chunks',
        help='Directory containing JSONL chunk files'
    )
    parser.add_argument(
        '--collection',
        type=str,
        default='amber_tutorials',
        help='Chroma collection name (default: amber_tutorials)'
    )
    parser.add_argument(
        '--chroma-host',
        type=str,
        default=None,
        help='Chroma server host (e.g., http://mirzakhani or localhost)'
    )
    parser.add_argument(
        '--chroma-port',
        type=int,
        default=8000,
        help='Chroma server port (default: 8000)'
    )
    parser.add_argument(
        '--use-openai',
        action='store_true',
        help='Use OpenAI embeddings (requires OPENAI_API_KEY env var)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=64,
        help='Batch size for embeddings and ingestion (default: 64)'
    )
    parser.add_argument(
        '--add-only',
        action='store_true',
        help='Use add() instead of upsert() (fails if IDs exist)'
    )
    parser.add_argument(
        '--manifest',
        type=str,
        default='data/tutorials_manifest.json',
        help='Path to tutorials manifest for metadata tracking'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("Starting Amber Tutorials Chroma Ingestion")
    logger.info(f"Chunks directory: {args.chunks_dir}")
    logger.info(f"Collection: {args.collection}")
    logger.info(f"Chroma host: {args.chroma_host or 'local'}")
    logger.info(f"Embeddings: {'OpenAI' if args.use_openai else 'local'}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info("=" * 80)
    
    chunks_dir = Path(args.chunks_dir)
    if not chunks_dir.exists():
        logger.error(f"Chunks directory not found: {chunks_dir}")
        return
    
    # Find all JSONL files
    jsonl_files = sorted(chunks_dir.glob('*_chunks.jsonl'))
    if not jsonl_files:
        logger.error(f"No JSONL chunk files found in {chunks_dir}")
        return
    
    logger.info(f"Found {len(jsonl_files)} chunk files")
    
    # Create Chroma client
    try:
        # Parse host if it includes protocol
        host = args.chroma_host
        port = args.chroma_port
        
        if host and "://" in host:
            from urllib.parse import urlparse
            parsed = urlparse(host)
            host = parsed.hostname or "localhost"
            port = parsed.port or port
        
        client = create_chroma_client(host=host, port=port)
    except Exception as e:
        logger.error(f"Failed to create Chroma client: {e}")
        return
    
    # Ingest chunks
    try:
        logger.info(f"\nIngesting {len(jsonl_files)} chunk files...")
        total = ingest_chunks_to_chroma(
            jsonl_files,
            args.collection,
            client,
            use_openai=args.use_openai,
            batch_size=args.batch_size,
            upsert=not args.add_only
        )
        logger.info(f"✓ Successfully ingested {total} chunks")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return
    
    # Load and ingest metadata
    manifest_path = Path(args.manifest)
    if manifest_path.exists():
        logger.info(f"\nLoading manifest: {manifest_path}")
        try:
            load_and_ingest_manifest(
                manifest_path,
                client,
                use_openai=args.use_openai,
                batch_size=args.batch_size
            )
        except Exception as e:
            logger.error(f"Failed to ingest metadata: {e}")
    
    # Verify ingestion
    try:
        collection = client.get_collection(args.collection)
        count = collection.count()
        logger.info(f"✓ Collection '{args.collection}' now contains {count} documents")
    except Exception as e:
        logger.warning(f"Could not verify collection count: {e}")
    
    logger.info("=" * 80)
    logger.info("INGESTION COMPLETE")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
