# plugins/chroma_ingest.py
import json
from pathlib import Path
import logging

from database_menu import AmberChromaAPI  # expects database_menu.py in plugins/

def ingest_month_threads(
    month: str,
    db_path: str = "/opt/chromadb/data/airflow_db",
    collection_name: str = "amber_messages",
    threads_dir: str = "/opt/chromadb/data/data/threads",
):
    """
    Load data/threads/threads_YYYYMM.json and upsert (delete+add) those thread IDs into Chroma.
    """
    threads_path = Path(threads_dir) / f"threads_{month}.json"
    if not threads_path.exists():
        raise FileNotFoundError(f"threads file not found: {threads_path}")

    logging.info(f"Opening Chroma DB: {db_path} | collection={collection_name}")
    api = AmberChromaAPI(db_path=db_path, collection_name=collection_name)

    data = json.loads(threads_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("threads JSON must be a list of thread dicts")

    # Build IDs used by your add_thread(): ids=[f"thread-{thread_id}"]
    ids = []
    for thread in data:
        tid = thread.get("thread_id")
        if tid is None:
            continue
        ids.append(f"thread-{tid}")

    # Delete existing IDs so reruns work (collection.add fails on duplicate IDs)
    if ids:
        logging.info(f"Deleting {len(ids)} existing IDs for month {month} (if present)")
        api.collection.delete(ids=ids)

    logging.info(f"Adding {len(data)} threads for month {month}")
    api.add_json(data, level="thread")

    logging.info(f"Ingest complete for {month} | added={len(data)}")
    return len(data)
