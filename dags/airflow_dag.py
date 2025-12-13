from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import logging
import sys, os

# GLOBAL PATHS
SCRAPED_DIR = "/opt/chromadb/data/scraped"
os.makedirs(SCRAPED_DIR, exist_ok=True)

DAGS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(DAGS_DIR, ".."))
PLUGINS_DIR = os.path.join(PROJECT_DIR, "plugins")

if PLUGINS_DIR not in sys.path:
    sys.path.insert(0, PLUGINS_DIR)

from scaping import scrape_new_data

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    "amber_scraper_incremental_dag",
    default_args=default_args,
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    catchup=False,
)

def run_scraper():
    logging.info("=== SCRAPER START ===")
    count = scrape_new_data(output_dir=SCRAPED_DIR)
    logging.info(f"=== SCRAPER DONE: {count} threads ===")

scraper_task = PythonOperator(
    task_id="incremental_scrape",
    python_callable=run_scraper,
    dag=dag,
)

