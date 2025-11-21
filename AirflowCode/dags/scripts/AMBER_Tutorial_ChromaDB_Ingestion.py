import json, os, math
import chromadb
from pathlib import Path

# ---------- Paths ----------
DATA_DIR = Path(os.getenv("DATA_DIR", "/opt/airflow/data")).resolve()
JSONL_PATH = DATA_DIR / "amber_tutorials.jsonl"
PERSIST_PATH = DATA_DIR / "chroma_db"
COLLECTION_NAME = "amber_tutorials"
BATCH_SIZE = 256

def load_jsonl(path):
    if not path.exists():
        raise FileNotFoundError(f"❌ JSONL file not found at: {path}")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def normalize_record(rec):
    # Supports both {"id","text","metadata":{...}} and doc-shaped {"id","content_text",...}
    if "text" in rec and "metadata" in rec:
        rid = rec["id"]
        doc = rec["text"]
        meta = rec["metadata"] or {}
        return rid, doc, meta
    rid = rec["id"]
    doc = rec.get("content_text") or rec.get("content_md") or ""
    meta_keys = ["title","url","tutorial_id","section_path","tags",
                 "has_code","equations","captured_at","content_md"]
    meta = {k: rec.get(k) for k in meta_keys if k in rec}
    return rid, doc, meta

def _to_meta_value(v):
    # Chroma only allows primitives. Convert lists/dicts/etc. to JSON strings.
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return json.dumps(v, ensure_ascii=False)

def sanitize_meta(meta: dict) -> dict:
    return {k: _to_meta_value(v) for k, v in (meta or {}).items()}

def main():
    print(f"Looking for amber_tutorials.jsonl in: {JSONL_PATH}")
    os.makedirs(PERSIST_PATH, exist_ok=True)

    # Initialize ChromaDB client
    client = chromadb.PersistentClient(path=str(PERSIST_PATH))
    coll = client.get_or_create_collection(name=COLLECTION_NAME)

    # Load JSONL
    records = list(load_jsonl(JSONL_PATH))
    if not records:
        print("⚠️  No records found in JSONL file.")
        return

    # Batch upload to Chroma
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i+BATCH_SIZE]
        ids, docs, metas = [], [], []
        for rec in batch:
            rid, doc, meta = normalize_record(rec)
            if not rid or not doc:
                continue
            ids.append(str(rid))
            docs.append(str(doc))
            metas.append(sanitize_meta(meta))
        if ids:
            coll.upsert(ids=ids, documents=docs, metadatas=metas)
            print(f"[{min(i+len(ids), len(records))}/{len(records)}] upserted {len(ids)}")

    print(f"✅ Ingested into '{COLLECTION_NAME}'")
    print(f"📂 ChromaDB path: {PERSIST_PATH.resolve()}")
    print(f"📘 Source file: {JSONL_PATH.resolve()}")

if __name__ == "__main__":
    main()
