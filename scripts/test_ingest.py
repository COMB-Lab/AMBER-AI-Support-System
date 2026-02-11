#!/usr/bin/env python3
"""Quick test of Chroma ingestion with local embeddings."""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import chromadb
from pathlib import Path
from sentence_transformers import SentenceTransformer

print("=" * 60)
print("CHROMA INGESTION TEST")
print("=" * 60)

# Initialize Chroma
print("\n1. Initializing Chroma...")
client = chromadb.Client()

# Read tutorial chunks
print("\n2. Loading tutorial chunks...")
chunks_dir = Path("data/tutorials_chunks")
chunk_files = list(chunks_dir.glob("*.jsonl"))
print(f"   Found {len(chunk_files)} chunk files")

# Load all chunks
all_chunks = []
for f in chunk_files:
    with open(f) as file:
        for line in file:
            try:
                all_chunks.append(json.loads(line))
            except:
                pass

print(f"   Loaded {len(all_chunks)} chunks total")

if not all_chunks:
    print("ERROR: No chunks loaded!")
    sys.exit(1)

# Initialize embeddings
print("\n3. Loading embedding model...")
try:
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("   Loaded sentence-transformers model")
except Exception as e:
    print(f"   ERROR loading model: {e}")
    sys.exit(1)

# Create collection
print("\n4. Creating Chroma collection...")
collection = client.get_or_create_collection(
    name="amber_tutorials",
    metadata={"hnsw:space": "cosine"}
)
print(f"   Created collection: 'amber_tutorials'")

# Generate embeddings and ingest
print("\n5. Generating embeddings and ingesting...")
batch_size = 32
texts = [c['text'] for c in all_chunks]
ids = [c['id'] for c in all_chunks]
metadatas = [c['metadata'] for c in all_chunks]

try:
    embeddings = model.encode(texts, show_progress_bar=True, batch_size=batch_size)
    print(f"   Generated {len(embeddings)} embeddings")
    print(f"   Embedding dimension: {len(embeddings[0])}")
    
    # Upsert in batches
    total_ingested = 0
    for i in range(0, len(all_chunks), batch_size):
        batch_end = min(i + batch_size, len(all_chunks))
        batch_ids = ids[i:batch_end]
        batch_texts = texts[i:batch_end]
        batch_embeddings = embeddings[i:batch_end]
        batch_metadatas = metadatas[i:batch_end]
        
        collection.upsert(
            ids=batch_ids,
            embeddings=batch_embeddings,
            documents=batch_texts,
            metadatas=batch_metadatas
        )
        total_ingested += len(batch_ids)
        print(f"   Ingested batch {i//batch_size + 1}: {len(batch_ids)} documents")
    
    print(f"\n   SUCCESS: {total_ingested} documents ingested")
    
except Exception as e:
    print(f"   ERROR during ingestion: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test a query
print("\n6. Testing query...")
try:
    query_text = "molecular dynamics simulation"
    query_embedding = model.encode([query_text])[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=3
    )
    print(f"   Query: '{query_text}'")
    print(f"   Found {len(results['documents'][0])} results:")
    for i, (doc, dist, meta) in enumerate(zip(results['documents'][0], results['distances'][0], results['metadatas'][0])):
        print(f"     [{i+1}] Distance: {dist:.3f}")
        print(f"         URL: {meta.get('url', 'N/A')}")
        print(f"         Preview: {doc[:80]}...")
except Exception as e:
    print(f"   ERROR during query: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)
