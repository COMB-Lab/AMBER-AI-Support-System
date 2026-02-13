import json
import os
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Tuple, Union

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# ----------------------------
# Paths / Settings
# ----------------------------

DATA_DIR = Path(os.getenv("DATA_DIR", "data")).resolve()

TUTORIALS_JSONL = DATA_DIR / "amber_tutorials.jsonl"
EMAILS_DIR = DATA_DIR / "CleanData"

EMAILS_RECURSIVE = True
EMAILS_GLOB = "*.json"

PERSIST_PATH = DATA_DIR / "chroma_db"
TUTORIALS_COLLECTION = "amber_tutorials"
EMAILS_COLLECTION = "amber_messages"

BATCH_SIZE = 128

EF = DefaultEmbeddingFunction()

# ----------------------------
# Utilities
# ----------------------------

def load_jsonl(path: Path) -> Iterator[dict]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)

def load_json_file(path: Path) -> Union[dict, list]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def iter_email_files(emails_dir: Path) -> Iterator[Path]:
    if EMAILS_RECURSIVE:
        yield from emails_dir.rglob(EMAILS_GLOB)
    else:
        yield from emails_dir.glob(EMAILS_GLOB)

# ----------------------------
# Email Flattening
# ----------------------------

def iter_email_records_from_dir(emails_dir: Path) -> Iterator[dict]:
    """
    Flattens thread JSON into individual message records.
    Each file is expected to look like:
      {thread_id, subject, messages:[...]}
    """
    for fp in iter_email_files(emails_dir):
        try:
            obj = load_json_file(fp)
        except Exception:
            continue

        rel = str(fp.relative_to(DATA_DIR))

        if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
            thread_id = obj.get("thread_id")
            thread_subject = obj.get("subject")

            for i, msg in enumerate(obj["messages"]):
                if not isinstance(msg, dict):
                    continue
                rec = dict(msg)
                rec["_source_file"] = rel
                rec["_thread_msg_index"] = i
                rec["thread_id"] = thread_id
                if "subject" not in rec:
                    rec["subject"] = thread_subject
                yield rec

# ----------------------------
# Metadata Sanitizer
# ----------------------------

def _to_meta_value(v):
    # Chroma metadata CANNOT contain None
    if v is None:
        return None

    if isinstance(v, (str, int, float, bool)):
        return v

    # Convert lists/dicts/objects to JSON string
    return json.dumps(v, ensure_ascii=False)

def sanitize_meta(meta: Dict) -> Dict:
    meta = meta or {}
    out = {}
    for k, v in meta.items():
        v2 = _to_meta_value(v)
        if v2 is None:
            continue 
        out[str(k)] = v2
    return out

# ----------------------------
# Tutorial Normalization
# ----------------------------

def normalize_tutorial_record(rec: dict) -> Tuple[str, str, Dict]:
    rid = str(rec.get("id", "")).strip()

    # Prefer content_text, fallback to content_md or text
    doc = str(
        rec.get("content_text")
        or rec.get("content_md")
        or rec.get("text")
        or ""
    ).strip()

    # Build metadata from known top-level fields
    meta = rec.get("metadata", {}) or {}
    meta["source_type"] = "tutorial"

    if rec.get("title"):
        meta["title"] = rec["title"]
    if rec.get("url"):
        meta["url"] = rec["url"]
    if rec.get("tutorial_id"):
        meta["tutorial_id"] = rec["tutorial_id"]
    if rec.get("captured_at"):
        meta["captured_at"] = rec["captured_at"]
    if rec.get("tags"):
        meta["tags"] = rec["tags"]

    return rid, doc, meta


# ----------------------------
# Email Normalization
# ----------------------------

def normalize_email_record(rec: dict) -> Tuple[str, str, Dict]:
    source_file = rec.get("_source_file", "")
    msg_index = rec.get("_thread_msg_index", 0)

    thread_id = rec.get("thread_id", "")
    message_id = rec.get("message_id", "")
    subject = rec.get("subject", "")
    author = rec.get("author", "")
    date = rec.get("date_raw", "")
    url = rec.get("url", "")
    in_reply_to = rec.get("in_reply_to", "")

    body = (rec.get("body") or "").strip()

    header = []
    if subject: header.append(f"Subject: {subject}")
    if author: header.append(f"Author: {author}")
    if date: header.append(f"Date: {date}")
    if thread_id: header.append(f"Thread-ID: {thread_id}")

    doc = "\n".join(header) + ("\n\n" + body if body else "")

    rid = f"{source_file}#t{thread_id}#m{message_id}#i{msg_index}"

    meta = {
        "source_type": "email",
        "thread_id": thread_id,
        "message_id": message_id,
        "subject": subject, 
        "author": author,
        "date": date,
        "url": url,
        "in_reply_to": in_reply_to,
        "_source_file": source_file,
        "_thread_msg_index": msg_index,
    }

    return rid, doc.strip(), meta

# ----------------------------
# Batch Helper
# ----------------------------

def batched(iterable: Iterable, size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch

def add_records(coll, records: List[Tuple[str, str, Dict]], prefix: str):
    ids, docs, metas = [], [], []
    for rid, doc, meta in records:
        if not rid or not doc:
            continue
        ids.append(prefix + rid)
        docs.append(doc)
        metas.append(sanitize_meta(meta))
    if ids:
        coll.add(ids=ids, documents=docs, metadatas=metas)

# ----------------------------
# Main
# ----------------------------

def main():
    print(f"📂 DATA_DIR: {DATA_DIR}")
    os.makedirs(PERSIST_PATH, exist_ok=True)

    client = chromadb.PersistentClient(path=str(PERSIST_PATH))
    tutorials_coll = client.get_or_create_collection(
        name=TUTORIALS_COLLECTION,
        embedding_function=EF
    )
    emails_coll = client.get_or_create_collection(
        name=EMAILS_COLLECTION,
        embedding_function=EF
    )

    # ---- Tutorials ----
    if TUTORIALS_JSONL.exists():
        print("\n=== Ingest Tutorials ===")
        total = 0
        for chunk in batched(load_jsonl(TUTORIALS_JSONL), BATCH_SIZE):
            normed = [normalize_tutorial_record(rec) for rec in chunk]
            add_records(tutorials_coll, normed, "tutorial:")
            total += len(normed)
            print(f"✅ Tutorials inserted: {total}")

    # ---- Emails ----
    if EMAILS_DIR.exists():
        print("\n=== Ingest Emails ===")
        total = 0
        stream = (normalize_email_record(rec) for rec in iter_email_records_from_dir(EMAILS_DIR))
        for chunk in batched(stream, BATCH_SIZE):
            add_records(emails_coll, chunk, "email:")
            total += len(chunk)
            if total % 1000 == 0:
                print(f"  inserted emails: {total}")
        print(f"✅ Emails inserted: {total}")

    print("\n=== Done ===")
    print("Collections:", [c.name for c in client.list_collections()])

if __name__ == "__main__":
    main()
