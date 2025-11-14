import json, os, math
import chromadb

JSONL_PATH = "amber_tutorials.jsonl"
COLLECTION_NAME = "amber_tutorials"
PERSIST_PATH = "chroma_db"
BATCH_SIZE = 256

def load_jsonl(path):
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
    os.makedirs(PERSIST_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=PERSIST_PATH)
    coll = client.get_or_create_collection(name=COLLECTION_NAME)

    records = list(load_jsonl(JSONL_PATH))
    if not records:
        print("No records in JSONL.")
        return

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

    print(f"✅ Ingested into '{COLLECTION_NAME}' (path: {os.path.abspath(PERSIST_PATH)})")

if __name__ == "__main__":
    main()
