#!/usr/bin/env python3
"""Ingest chunked JSONL tutorial documents into a Chroma collection.

This script expects chunk JSONL files with lines like:
  {"id": "slug-0", "text": "...", "metadata": {"url": "...", "title": "..."}}

Environment variables:
- OPENAI_API_KEY: if set, used to generate embeddings via OpenAI Embeddings API.
- CHROMA_SERVER_HOST / CHROMA_SERVER_HTTP_PORT: optional, to connect to a remote Chroma server (REST API).

Usage:
  python scripts/chroma_ingest.py --chunks-dir data/tutorials_chunks --collection amber_tutorials

Note: install chromadb and openai (requirements.txt updated).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List


def get_openai_embeddings(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    try:
        import openai
    except Exception as e:
        raise RuntimeError("openai package not installed or available") from e
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY not set; cannot generate embeddings')
    openai.api_key = api_key
    # OpenAI allows batching; we will send as one request if small
    resp = openai.Embedding.create(input=texts, model=model)
    embeddings = [r['embedding'] for r in resp['data']]
    return embeddings


def create_chroma_client():
    try:
        import chromadb
        from chromadb.config import Settings
    except Exception as e:
        raise RuntimeError('chromadb package not installed') from e

    # If CHROMA_SERVER_HOST is set, configure REST client
    host = os.environ.get('CHROMA_SERVER_HOST') or os.environ.get('CHROMA_SERVER_URL')
    port = os.environ.get('CHROMA_SERVER_HTTP_PORT')
    if host:
        # If host is a URL, parse
        if host.startswith('http') and '://' in host:
            # try to extract host and port
            from urllib.parse import urlparse

            p = urlparse(host)
            host_only = p.hostname
            port_only = p.port or (port and int(port)) or 8000
            settings = Settings(chroma_api_impl="rest", chroma_server_host=host_only, chroma_server_http_port=port_only)
        else:
            settings = Settings(chroma_api_impl="rest", chroma_server_host=host, chroma_server_http_port=int(port) if port else 8000)
        client = chromadb.Client(settings)
    else:
        client = chromadb.Client()
    return client


def ingest_chunks(chunks_dir: Path, collection_name: str, batch_size: int = 64):
    files = sorted(chunks_dir.glob('*_chunks.jsonl'))
    if not files:
        print(f'No chunk files found in {chunks_dir}')
        return
    client = create_chroma_client()
    # get or create collection
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        collection = client.create_collection(collection_name)

    for f in files:
        docs = [json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]
        ids = [d['id'] for d in docs]
        texts = [d['text'] for d in docs]
        metadatas = [d.get('metadata', {}) for d in docs]

        print(f'Processing {f.name}: {len(docs)} docs')

        # obtain embeddings via OpenAI if API key present
        embeddings = None
        if os.environ.get('OPENAI_API_KEY'):
            # chunk embeddings in batches
            embs = []
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i+batch_size]
                batch_emb = get_openai_embeddings(batch)
                embs.extend(batch_emb)
            embeddings = embs

        # add to collection; chroma accepts embeddings if provided
        try:
            if embeddings is not None:
                collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
            else:
                collection.add(ids=ids, documents=texts, metadatas=metadatas)
            print(f'Upserted {len(ids)} docs into collection {collection_name}')
        except Exception as e:
            print(f'Failed to add {f.name} to Chroma: {e}')


def main():
    parser = argparse.ArgumentParser(description='Ingest tutorial chunk JSONL into Chroma')
    parser.add_argument('--chunks-dir', type=str, default='data/tutorials_chunks')
    parser.add_argument('--collection', type=str, default='amber_tutorials')
    parser.add_argument('--batch-size', type=int, default=64)
    args = parser.parse_args()

    ingest_chunks(Path(args.chunks_dir), args.collection, args.batch_size)


if __name__ == '__main__':
    main()
