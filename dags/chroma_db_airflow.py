from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import logging
import json
import uuid
import chromadb

# ------------------------------------------------------------
# GLOBAL DATA PATHS
# ------------------------------------------------------------
SCRAPED_DIR = "/opt/chromadb/data/scraped"
CHROMA_DIR = "/opt/chromadb/data/amber_chroma_db"

os.makedirs(SCRAPED_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)


# ------------------------------------------------------------
# INGESTION FUNCTION
# ------------------------------------------------------------
def ingest_to_chroma():

    logging.info("=== Starting ChromaDB Ingestion ===")
    logging.info(f"Reading scraped threads from: {SCRAPED_DIR}")
    logging.info(f"Writing vector DB to:        {CHROMA_DIR}")

    # Initialize Chroma client
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    col = client.get_or_create_collection("amber_threads")

    # Collect JSON files
    files = []
    for root, _, fns in os.walk(SCRAPED_DIR):
        for f in fns:
            if f.endswith(".json"):
                files.append(os.path.join(root, f))

    logging.info(f"Found {len(files)} JSON files to ingest.")

    if not files:
        logging.info("No JSON files found. Nothing to ingest.")
        return

    # ------------------------------------------------------------
    # MAIN LOOP — PROCESS EACH JSON FILE
    # ------------------------------------------------------------
    inserted_count = 0

    for fp in files:
        logging.info(f"Processing file: {fp}")

        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.error(f"Failed to load {fp}: {e}")
            continue

        # --------------------------------------------------------
        # CASE A: File contains a LIST of thread dicts
        # --------------------------------------------------------
        if isinstance(data, list):
            for thread in data:
                if not isinstance(thread, dict) or "messages" not in thread:
                    logging.error(f"Malformed thread in {fp}. Skipping thread.")
                    continue

                tid = thread.get("thread_id", str(uuid.uuid4()))
                msgs = thread.get("messages", [])
                body = "\n".join(m.get("body", "") for m in msgs)

                col.upsert(
                    ids=[str(uuid.uuid4())],
                    documents=[body],
                    metadatas=[{"thread_id": tid, "file": fp}]
                )

                inserted_count += 1

            continue  # done with this file

        # --------------------------------------------------------
        # CASE B: File contains a SINGLE thread dict
        # --------------------------------------------------------
        if isinstance(data, dict) and "messages" in data:
            tid = data.get("thread_id", str(uuid.uuid4()))
            msgs = data.get("messages", [])
            body = "\n".join(m.get("body", "") for m in msgs)

            col.upsert(
                ids=[str(uuid.uuid4())],
                documents=[body],
                metadatas=[{"thread_id": tid, "file": fp}]
            )

            inserted_count += 1
            continue

        # --------------------------------------------------------
        # CASE C: Unrecognized structure
        # --------------------------------------------------------
        logging.error(f"Unrecognized JSON structure in {fp}. Skipping.")

    logging.info(f"=== Completed ingestion. Added {inserted_count} threads ===")


# ------------------------------------------------------------
# AIRFLOW DAG CONFIGURATION
# ------------------------------------------------------------
default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="amber_chromadb_ingest_dag",
    description="Ingest scraped Amber threads into ChromaDB",
    default_args=default_args,
    schedule="@daily",            # AIRFLOW 3 syntax
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
)

task = PythonOperator(
    task_id="sync_json_to_chromadb",
    python_callable=ingest_to_chroma,
    dag=dag,
)

