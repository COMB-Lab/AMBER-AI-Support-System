from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import logging
import sys, os

DAGS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(DAGS_DIR, "..", ".."))  # adjust if needed
PLUGINS_DIR = os.path.join(PROJECT_DIR, "plugins")

if PLUGINS_DIR not in sys.path:
    sys.path.insert(0, PLUGINS_DIR)

from run_month import run as run_month_pipeline
from chroma_ingest import ingest_month_threads

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

dag = DAG(
    dag_id="amber_monthly_pipeline_with_ingest",
    default_args=default_args,
    description="Monthly scrape/parse/merge then ingest into Chroma (previous month)",
    schedule="0 0 1 * *",   # midnight on the 1st
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
)

def compute_prev_month(**context) -> str:
    logical_date = context["logical_date"]
    prev = logical_date.subtract(months=1)
    return prev.format("YYYYMM")

def run_pipeline(**context):
    month_str = compute_prev_month(**context)
    logging.info(f"=== Running month pipeline for {month_str} ===")

    # ensure consistent paths for all modules
    os.environ["AMBER_DATA_ROOT"] = "/opt/chromadb/data/data"

    run_month_pipeline(month_str)

def run_ingest(**context):
    month_str = compute_prev_month(**context)
    logging.info(f"=== Ingesting month {month_str} into Chroma ===")

    os.environ["AMBER_DATA_ROOT"] = "/opt/chromadb/data/data"

    ingest_month_threads(
        month=month_str,
        db_path="/opt/chromadb/data/airflow_db",
        collection_name="amber_messages",
        threads_dir="/opt/chromadb/data/data/threads",
    )

pipeline_task = PythonOperator(
    task_id="scrape_parse_merge_previous_month",
    python_callable=run_pipeline,
    dag=dag,
)

ingest_task = PythonOperator(
    task_id="ingest_previous_month_into_chroma",
    python_callable=run_ingest,
    dag=dag,
)

pipeline_task >> ingest_task

