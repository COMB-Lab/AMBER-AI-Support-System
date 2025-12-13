# File: dags/amber_pipeline.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import requests
from bs4 import BeautifulSoup
import json
import chromadb
from sentence_transformers import SentenceTransformer


BASE_URL = "https://ambermd.org/tutorials/"
RAW_DIR = "/opt/airflow/dags/tutorial_data/raw_html"
CLEAN_DIR = "/opt/airflow/dags/tutorial_data/cleaned"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "amber_tutorials"


os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(CLEAN_DIR, exist_ok=True)
os.makedirs("/opt/airflow/dags/tutorial_data/embeddings", exist_ok=True)


def scrape_tutorials():
    response = requests.get(BASE_URL)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    links = []
    for li in soup.find_all("li"):
        a_tag = li.find("a")
        if a_tag and a_tag.get("href") and "tutorial" in a_tag["href"].lower():
            full_url = a_tag["href"] if a_tag["href"].startswith("http") else BASE_URL + a_tag["href"]
            links.append(full_url)

    with open(os.path.join(RAW_DIR, "tutorial_links.json"), "w") as f:
        json.dump(links, f)
    print(f"Found {len(links)} tutorial links.")

    for i, url in enumerate(links, 1):
        try:
            r = requests.get(url)
            r.raise_for_status()
            file_name = f"tutorial_{i}.html"
            with open(os.path.join(RAW_DIR, file_name), "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"Saved {url} as {file_name}")
        except Exception as e:
            print(f"Error scraping {url}: {e}")

def clean_tutorials():
    tutorials = []
    for file_name in os.listdir(RAW_DIR):
        if file_name.endswith(".html"):
            file_path = os.path.join(RAW_DIR, file_name)
            with open(file_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
            content_div = soup.find("div", {"id": "main-content"}) or soup
            text = content_div.get_text(separator="\n").strip()
            tutorials.append({"file": file_name, "content": text, "source": file_name})

    with open(os.path.join(CLEAN_DIR, "tutorials_cleaned.json"), "w", encoding="utf-8") as f:
        json.dump(tutorials, f, indent=2)
    print(f"Cleaned {len(tutorials)} tutorials.")

def embed_tutorials():
    # Load cleaned tutorials
    with open(os.path.join(CLEAN_DIR, "tutorials_cleaned.json"), "r", encoding="utf-8") as f:
        tutorials = json.load(f)

    # Load embedding model
    model = SentenceTransformer(EMBEDDING_MODEL)


    client = chromadb.Client()

    # Create or get collection
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        collection = client.get_collection(COLLECTION_NAME)
    else:
        collection = client.create_collection(name=COLLECTION_NAME)

    for tut in tutorials:
        content = tut["content"]
        tut_id = tut["file"]
        vector = model.encode(content).tolist()
        collection.add(
            ids=[tut_id],
            documents=[content],
            metadatas=[{"source": tut_id}],
            embeddings=[vector]
        )

    print(f"Stored {len(tutorials)} tutorials with embeddings in ChromaDB.")

# --- DAG ---
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2025, 12, 12),
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "amber_pipeline",
    default_args=default_args,
    schedule_interval=None,  # or set a cron schedule
    catchup=False,
) as dag:

    t1 = PythonOperator(
        task_id="scrape_tutorials",
        python_callable=scrape_tutorials
    )

    t2 = PythonOperator(
        task_id="clean_tutorials",
        python_callable=clean_tutorials
    )

    t3 = PythonOperator(
        task_id="embed_tutorials",
        python_callable=embed_tutorials
    )

    # Set execution order
    t1 >> t2 >> t3
