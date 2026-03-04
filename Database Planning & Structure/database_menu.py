import os
import sys
import json
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Create Chroma client (new API)
import chromadb
from sentence_transformers import SentenceTransformer

# ----------------- GLOBAL SETTINGS -----------------
os.environ["CUDA_VISIBLE_DEVICES"] = ""   # disables GPU visibility
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

EMAIL_REQUIRED_FIELDS = [
    "thread_id", "subject", "author", "email",
    "date_iso", "url", "doc_type", "schema_version"
]

TUTORIAL_REQUIRED_FIELDS = [
    "label_id", "title", "url",
    "page_url", "page_title",
    "doc_type", "schema_version"
]

# ----------------- HELPERS -----------------
def _clean_text(s: str) -> str:
    return (s or "").strip()

def _ensure_date_epoch(meta: dict):
    """Ensure valid ISO and epoch date fields exist."""
    if "date_iso" in meta and meta["date_iso"]:
        try:
            iso_norm = meta["date_iso"].replace("Z", "+00:00") if meta["date_iso"].endswith("Z") else meta["date_iso"]
            dt = datetime.fromisoformat(iso_norm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            meta["date_epoch"] = int(dt.timestamp())
            return
        except Exception:
            pass

    if "date_raw" in meta and meta["date_raw"]:
        try:
            dt = parsedate_to_datetime(meta["date_raw"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            meta["date_iso"] = dt.astimezone(timezone.utc).isoformat()
            meta["date_epoch"] = int(dt.timestamp())
            return
        except Exception:
            pass

    meta["date_iso"] = meta.get("date_iso", "")
    meta["date_epoch"] = meta.get("date_epoch", 0)

def _validate_email_metadata(meta: dict):
    """Ensure all required email metadata fields exist."""
    if "schema_version" not in meta:
        meta["schema_version"] = 1
    if "doc_type" not in meta:
        meta["doc_type"] = "thread"

    _ensure_date_epoch(meta)

    for key in EMAIL_REQUIRED_FIELDS:
        if key not in meta:
            raise KeyError(f"Missing required email metadata key: {key}")
    return meta

def _validate_tutorial_metadata(meta: dict):
    """Ensure all required tutorial metadata fields exist."""
    if "schema_version" not in meta:
        meta["schema_version"] = 1
    if "doc_type" not in meta:
        meta["doc_type"] = "tutorial_page"

    # Tutorials may not have dates; keep consistent optional fields
    meta.setdefault("date_iso", "")
    meta.setdefault("date_epoch", 0)

    for key in TUTORIAL_REQUIRED_FIELDS:
        if key not in meta:
            raise KeyError(f"Missing required tutorial metadata key: {key}")
    return meta

def _safe_delete_by_id(collection, doc_id: str):
    """
    Best-effort delete. If the ID doesn't exist (or Chroma errors),
    we don't want to crash the ingest.
    """
    try:
        collection.delete(ids=[doc_id])
    except Exception:
        pass

# ----------------- MAIN CLASS -----------------
class AmberChromaAPI:
    def __init__(self, db_path="./amber_chroma_db", collection_name="amber_messages"):
        """Initialize a persistent ChromaDB client in a local folder."""
        os.makedirs(db_path, exist_ok=True)
        print(f"Using local ChromaDB path: {os.path.abspath(db_path)}")
        self.db_path = db_path

        self.client = chromadb.PersistentClient(path=db_path)

        # Use cosine similarity for text embeddings
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def clear_collection(self):
        """Delete all documents in the collection."""
        all_docs = self.collection.get()
        if all_docs["ids"]:
            self.collection.delete(ids=all_docs["ids"])
            print("Collection cleared.")
        else:
            print("Collection already empty.")

    # ----------------- EMAIL THREAD INGEST -----------------
    def add_thread(self, thread: dict, upsert: bool = True):
        """
        Add a single email thread as a document.

        If upsert=True, we delete any existing doc with the same ID (thread-{thread_id})
        and then re-add the updated thread. This is ideal when re-scraping the same
        month every day and threads can gain new messages over time.
        """
        thread_id = str(thread["thread_id"])
        doc_id = f"thread-{thread_id}"

        subject = thread.get("subject", "No Subject")

        body = "\n\n---\n\n".join(
            f"{msg.get('author', 'Unknown')} ({msg.get('date_raw', '')}):\n{msg.get('body', '')}"
            for msg in thread.get("messages", [])
        )

        first_msg = thread["messages"][0] if thread.get("messages") else {}

        metadata = {
            "thread_id": int(thread_id),
            "subject": subject,
            "author": first_msg.get("author", ""),
            "email": first_msg.get("email", ""),
            "date_iso": first_msg.get("date_iso", ""),
            "date_raw": first_msg.get("date_raw", ""),
            "url": first_msg.get("url", ""),
            "message_count": len(thread.get("messages", [])),
            "doc_type": "thread",
            "schema_version": 1,
            # Helpful for debugging / recency; optional
            "updated_epoch": int(datetime.now(timezone.utc).timestamp()),
        }

        metadata = _validate_email_metadata(metadata)
        embedding = EMBEDDER.encode(body).tolist()

        if upsert:
            _safe_delete_by_id(self.collection, doc_id)

        self.collection.add(
            ids=[doc_id],
            documents=[body],
            metadatas=[metadata],
            embeddings=[embedding],
        )

    # ----------------- TUTORIAL INGEST -----------------
    def add_tutorial_label(self, label: dict):
        """
        Ingest one tutorial label entry and store 1 Chroma doc per page.

        Expected schema:
          - label_id, title, url
          - pages[]: {url, page_title, full_text, sections[]}
        """
        label_id = str(label.get("label_id", "")).strip()
        title = str(label.get("title", "")).strip()
        label_url = str(label.get("url", "")).strip()

        pages = label.get("pages", []) or []

        # Fallback: if pages is missing but top-level has full_text/sections
        if not pages:
            pages = [{
                "url": label_url,
                "page_title": title,
                "full_text": label.get("full_text", ""),
                "sections": label.get("sections", []),
            }]

        for p_idx, page in enumerate(pages):
            page_url = str(page.get("url") or label_url).strip()
            page_title = str(page.get("page_title") or title).strip()

            full_text = _clean_text(page.get("full_text", ""))
            if not full_text:
                # Build from sections if full_text missing
                sec_parts = []
                for sec in (page.get("sections", []) or []):
                    h = _clean_text(sec.get("heading", ""))
                    t = _clean_text(sec.get("text", ""))
                    if h and t:
                        sec_parts.append(f"{h}\n{t}")
                    elif t:
                        sec_parts.append(t)
                full_text = "\n\n".join(sec_parts).strip()

            if not full_text:
                # nothing to embed
                continue

            metadata = {
                "label_id": label_id,
                "title": title,
                "url": label_url,
                "page_url": page_url,
                "page_title": page_title,
                "doc_type": "tutorial_page",
                "schema_version": 1,
            }
            metadata = _validate_tutorial_metadata(metadata)

            doc_id = f"tutorial-{label_id}-page-{p_idx}"
            embedding = EMBEDDER.encode(full_text).tolist()

            # NOTE: If you also need upsert for tutorial pages, you can
            # _safe_delete_by_id(self.collection, doc_id) here too.
            self.collection.add(
                ids=[doc_id],
                documents=[full_text],
                metadatas=[metadata],
                embeddings=[embedding],
            )

    # ----------------- JSON LOADER (AUTO DETECT) -----------------
    def add_json(self, json_input, level="auto", upsert_threads: bool = True):
        """
        Load and add from JSON file path or python list/dict. Auto-detect schema.

        For thread ingest, upsert_threads=True will delete+readd each thread doc_id,
        preventing duplicates when re-scraping the same month daily.
        """
        if isinstance(json_input, str):
            with open(json_input, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json_input

        if not isinstance(data, list) or not data:
            raise ValueError("JSON must be a non-empty list of objects")

        first = data[0]

        if level == "auto":
            if isinstance(first, dict) and "thread_id" in first:
                level = "thread"
            elif isinstance(first, dict) and "label_id" in first and ("pages" in first or "sections" in first):
                level = "tutorial"
            else:
                raise ValueError("Unknown JSON schema. Expected thread_id or label_id/pages/sections.")

        if level == "thread":
            for thread in data:
                self.add_thread(thread, upsert=upsert_threads)
        elif level == "tutorial":
            for label in data:
                self.add_tutorial_label(label)
        else:
            raise ValueError("level must be 'auto', 'thread', or 'tutorial'")

    # ----------------- QUERY -----------------
    def query_embeddings(self, text, n=5, where=None, threshold=0.75):
        """Return matched embeddings and similarity scores (filtered by threshold)."""
        embedding = EMBEDDER.encode(text).tolist()
        print(f"\nQuerying for embeddings similar to: '{text}'")

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n,
            where=where if where is not None else None,
            include=["embeddings", "distances", "metadatas"]
        )

        embeddings = results.get("embeddings", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0] if "metadatas" in results else [None] * len(embeddings)

        total_found = len(embeddings)
        print(f"Found {total_found} total embedding results before filtering")

        filtered_pairs = []
        for emb, dist, meta in zip(embeddings, distances, metadatas):
            similarity = 1 - dist
            if similarity >= threshold:
                filtered_pairs.append({
                    "embedding": emb,
                    "similarity": similarity,
                    "metadata": meta,
                })

        print(f"{len(filtered_pairs)} embeddings kept (similarity ≥ {threshold})")
        return filtered_pairs

    def query(self, text, n=5, where=None, threshold=0.75):
        """Run a semantic search and apply a similarity threshold."""
        embedding = EMBEDDER.encode(text).tolist()
        print(f"\nQuerying for: '{text}'")

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n,
            where=where if where is not None else None,
            include=["documents", "metadatas", "distances"]
        )

        total_found = len(results.get("documents", [[]])[0])
        print(f"Found {total_found} total results before filtering")

        filtered_docs, filtered_metas, filtered_scores = [], [], []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            similarity = 1 - dist
            if similarity >= threshold:
                filtered_docs.append(doc)
                filtered_metas.append(meta)
                filtered_scores.append(similarity)

        print(f"{len(filtered_docs)} results kept (similarity ≥ {threshold})")
        return {
            "documents": filtered_docs,
            "metadatas": filtered_metas,
            "scores": filtered_scores,
        }

    def peek(self, n=5):
        """Return a small preview of the collection."""
        return self.collection.peek(n)

# ----------------- MAIN MENU LOOP -----------------
def main():
    api = None
    db_path_display = "None"

    while True:
        print("\n========== AMBER CHROMA DB ==========")
        print(f"Current database: {db_path_display}")
        print("1. Setup (Add JSON / Open Database / Peek / Clean)")
        print("2. Query")
        print("3. Exit")
        print("=====================================")

        choice = input("Choose an option (1-3): ").strip()

        # ------------------ SETUP ------------------
        if choice == "1":
            setup_choice = input("Setup mode: (A)dd JSON, (O)pen DB, (P)eek, (C)lean: ").strip().lower()

            if setup_choice == "a":
                path = input("Enter JSON filename: ").strip()
                db_name = input("Database folder (default: ./amber_chroma_db): ").strip() or "./amber_chroma_db"
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)

                # Auto-detect thread vs tutorial schema
                api.add_json(path, level="auto", upsert_threads=True)
                print(f"Added docs from {path} into {db_name}")

            elif setup_choice == "o":
                db_name = input("Database folder (default: ./amber_chroma_db): ").strip() or "./amber_chroma_db"
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)
                print(f"Opened database: {db_path_display}")

            elif setup_choice == "c":
                db_name = input("Database folder (default: ./amber_chroma_db): ").strip() or "./amber_chroma_db"
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)
                api.clear_collection()

            elif setup_choice == "p":
                db_name = input("Database folder (default: ./amber_chroma_db): ").strip() or "./amber_chroma_db"
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)

                peeked = api.peek()
                if not peeked.get("documents"):
                    print("No entries found in this collection.")
                else:
                    print(f"\nPreviewing first {len(peeked['documents'])} entries:\n")
                    for meta, doc in zip(peeked["metadatas"], peeked["documents"]):
                        label = meta.get("doc_type", "doc")
                        title = meta.get("subject") or meta.get("page_title") or meta.get("title") or "Untitled"
                        author = meta.get("author", "")
                        prefix = f"[{label}]"
                        if author:
                            prefix += f" [{author}]"
                        print(f"{prefix} {title}")
                        print(doc[:250] + "...\n" + "-" * 60)

            else:
                print("Invalid choice.")

        # ------------------ QUERY ------------------
        elif choice == "2":
            if api is None:
                print("No database is currently open. Use option 1 first.")
                continue

            while True:
                query_text = input("\nEnter search query (or 'back' to return): ").strip()
                if query_text.lower() == "back":
                    break

                threshold = input("Enter relevance threshold (0.0–1.0, default 0.75): ").strip()
                threshold = float(threshold) if threshold else 0.75

                # Optional: filter tutorials only:
                # where = {"doc_type": "tutorial_page"}
                where = None

                res = api.query(query_text, threshold=threshold, where=where)
                for meta, doc, score in zip(res["metadatas"], res["documents"], res["scores"]):
                    label = meta.get("doc_type", "doc")
                    title = meta.get("subject") or meta.get("page_title") or meta.get("title") or "Untitled"
                    author = meta.get("author", "")
                    extra = f" [{author}]" if author else ""
                    print(f"\n[{label}]{extra} {title}  |  similarity={score:.3f}")

                    # Show URL if present
                    url = meta.get("url") or meta.get("page_url") or ""
                    if url:
                        print(f"URL: {url}")

                    print(doc[:250] + "...\n" + "-" * 60)

        # ------------------ EXIT ------------------
        elif choice == "3":
            print("Exiting Amber ChromaDB Interface.")
            break

        else:
            print("Invalid choice.")

if __name__ == "__main__":
    main()