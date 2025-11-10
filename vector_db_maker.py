import os
import json
import chromadb
import chromadb.config
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from sentence_transformers import SentenceTransformer


EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
# Define required metadata fields set in mailing list data
REQUIRED_FIELDS = [
    "thread_id", "subject", "author", "email",
    "date_iso", "url", "doc_type", "schema_version"
]


def _ensure_date_epoch(meta: dict):
    "Ensure valid ISO and epoch date fields exist."
    # First try to parse from ISO format
    if "date_iso" in meta and meta["date_iso"]:
        try:
            iso_norm = meta["date_iso"].replace("Z", "+00:00") if meta["date_iso"].endswith("Z") else meta["date_iso"]
            dt = datetime.fromisoformat(iso_norm)
            # Ensure timezone-aware datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            meta["date_epoch"] = int(dt.timestamp())
            return
        except Exception:
            pass

    # Next try to parse from raw date string
    if "date_raw" in meta and meta["date_raw"]:
        try:
            dt = parsedate_to_datetime(meta["date_raw"])
            # Ensure timezone-aware datetime
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            meta["date_iso"] = dt.astimezone(timezone.utc).isoformat()
            meta["date_epoch"] = int(dt.timestamp())
            return
        except Exception:
            pass

    # If both fail, set defaults
    meta["date_iso"] = meta.get("date_iso", "")
    meta["date_epoch"] = meta.get("date_epoch", 0)


def _validate_metadata(meta: dict):
    "Ensure all required metadata fields exist."
    if "schema_version" not in meta:
        meta["schema_version"] = 1
    if "doc_type" not in meta:
        meta["doc_type"] = "thread"

    # Ensure date fields exist or have default values
    _ensure_date_epoch(meta)

    for key in REQUIRED_FIELDS:
        if key not in meta:
            raise KeyError(f"Missing required metadata key: {key}")
    return meta


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
        # Concatenate all messages in the thread
        body = "\n\n---\n\n".join(
            f"{msg.get('author', 'Unknown')} ({msg.get('date_raw', '')}):\n{msg.get('body', '')}"
            for msg in thread.get("messages", [])
        )
        # Use first message for metadata fields
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

        # Validates which also sets defaults and ensures date fields
        metadata = _validate_metadata(metadata)
        # Creates embedding
        embedding = EMBEDDER.encode(body).tolist()
        # Then add to collection
        self.collection.add(
            ids=[f"thread-{thread_id}"],
            documents=[body],
            metadatas=[metadata],
            embeddings=[embedding],
        )

    def add_json(self, json_input, level="thread"):
        "Load and add threads from a JSON file or a dict."
        # If file string given, load JSON from file
        if isinstance(json_input, str):
            with open(json_input, "r", encoding="utf-8") as f:
                data = json.load(f)
        # Otherwise assume dict/list given
        else:
            data = json_input
        # Iterate through each thread in the data
        for thread in data:
            if level == "thread":
                self.add_thread(thread)

    def query(self, text, n=5, where=None, threshold=0.75):
        "Run a semantic search and apply a similarity threshold."
        # Creates embedding for the query text based on the user input
        embedding = EMBEDDER.encode(text).tolist()
        print(f"\nQuerying for: '{text}'")

        # Returns the top n results and includes document texts, metadata, and distances
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=n,
            where=where if where is not None else None,
            include=["documents", "metadatas", "distances"]
        )

        total_found = len(results.get("documents", [[]])[0])
        print(f"Found {total_found} total results before filtering")

        # Iterates through the returned first result, and keeps items with similarity >= threshold
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

    # Could also be changes to adjust peek size by passing n parameter as user input
    def peek(self, n=5):

        # peek_size = input("Enter a desired peek size: ").strip().toint()
        # return self.collection.peek(peek_size)

        "Return a small preview of the collection."
        return self.collection.peek(n)


def main():
    api = None
    db_path_display = "None"

    while True:

        # Testing: check if file exists before proceeding
        # file_path = "thread_level.json"
        # if not os.path.exists(file_path):
        #     print(f"File not found: {file_path}")
        #     print("Current Working Directory:", os.getcwd())
        # else:
        #     print("File exists!")

        # Add everything in one shot (thread-level)
        # api.add_json("thread_level.json", level="thread")

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
