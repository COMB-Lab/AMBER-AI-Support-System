import os
import json
# Create Chroma client (new API)
import chromadb
import chromadb.config
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from sentence_transformers import SentenceTransformer


# ----------------- GLOBAL SETTINGS -----------------
EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")

REQUIRED_FIELDS = [
    "thread_id", "subject", "author", "email",
    "date_iso", "url", "doc_type", "schema_version"
]


# ----------------- HELPERS -----------------
def _ensure_date_epoch(meta: dict):
    "Ensure valid ISO and epoch date fields exist."
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


def _validate_metadata(meta: dict):
    "Ensure all required metadata fields exist."
    if "schema_version" not in meta:
        meta["schema_version"] = 1
    if "doc_type" not in meta:
        meta["doc_type"] = "thread"

    _ensure_date_epoch(meta)

    for key in REQUIRED_FIELDS:
        if key not in meta:
            raise KeyError(f"Missing required metadata key: {key}")
    return meta


# ----------------- MAIN CLASS -----------------
class AmberChromaAPI:
    def __init__(self, db_path="./amber_chroma_db", collection_name="amber_messages"):
        "Initialize a persistent ChromaDB client in a local folder."
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
        "Delete all documents in the collection."
        all_docs = self.collection.get()
        if all_docs["ids"]:
            self.collection.delete(ids=all_docs["ids"])
            print("Collection cleared.")

    def add_thread(self, thread: dict):
        "Add a single thread as a document."
        thread_id = str(thread["thread_id"])
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
        }

        metadata = _validate_metadata(metadata)
        embedding = EMBEDDER.encode(body).tolist()

        self.collection.add(
            ids=[f"thread-{thread_id}"],
            documents=[body],
            metadatas=[metadata],
            embeddings=[embedding],
        )

    def add_json(self, json_input, level="thread"):
        "Load and add threads from a JSON file or a dict."
        if isinstance(json_input, str):
            with open(json_input, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = json_input

        for thread in data:
            if level == "thread":
                self.add_thread(thread)

    def query_embeddings(self, text, n=5, where=None):
        "Return matched embeddings and similarity scores."
        embedding = EMBEDDER.encode(text).tolist()
        print(f"\nQuerying for embeddings similar to: '{text}'")

        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n,
            where=where if where is not None else None,
            include=["embeddings", "distances"]
        )

        embeddings = results.get("embeddings", [[]])[0]
        distances = results.get("distances", [[]])[0]

        pairs = [{"embedding": e, "similarity": 1 - d} for e, d in zip(embeddings, distances)]
        print(f"Returned {len(pairs)} embedding vectors.")
        return pairs


    def query(self, text, n=5, where=None, threshold=0.75):
        "Run a semantic search and apply a similarity threshold."
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
        "Return a small preview of the collection."
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
                api.add_json(path)
                print(f"Added threads from {path} into {db_name}")
            elif setup_choice == "o":
                db_name = input("Database folder (default: ./amber_chroma_db): ").strip() or "./amber_chroma_db"
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)
                print(f"Opened database: {db_path_display}")
            elif setup_choice =="c":
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)
                api.clear_collection()
            elif setup_choice == "p":
                db_name = input("Database folder (default: ./amber_chroma_db): ").strip() or "./amber_chroma_db"
                api = AmberChromaAPI(db_path=db_name)
                db_path_display = os.path.abspath(db_name)
                peeked = api.peek()
                if not peeked["documents"]:
                    print("No entries found in this collection.")
                else:
                    print(f"\nPreviewing first {len(peeked['documents'])} entries:\n")
                    for meta, doc in zip(peeked["metadatas"], peeked["documents"]):
                        print(f"[{meta['author']}] {meta['subject']}")
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

                res = api.query(query_text, threshold=threshold)
                for meta, doc, score in zip(res["metadatas"], res["documents"], res["scores"]):
                    print(f"\n[{meta['author']}] {meta['subject']}  |  similarity={score:.3f}")
                    print(doc[:250] + "...\n" + "-" * 60)

        # ------------------ EXIT ------------------
        elif choice == "3":
            print("Exiting Amber ChromaDB Interface.")
            break

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
