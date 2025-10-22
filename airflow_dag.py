from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import logging
import sys
import os

# Make sure Python can find scrape_amber.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scripts.Scaping import scrape_new_data

# ----------------------------
# DAG Configuration
# ----------------------------
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
    description="Incremental scraper for Amber mailing list, runs daily",
    schedule_interval=timedelta(days=1),
    start_date=datetime(2025, 10, 16),  # First day to run
    catchup=False,
    max_active_runs=1
)


def run_scraper():
    logging.info("=== Starting Incremental Amber Scraper ===")
    threads_scraped = scrape_new_data()
    logging.info(f"=== Finished scraping: {threads_scraped} threads scraped ===")


scraper_task = PythonOperator(
    task_id="incremental_scrape_task",
    python_callable=run_scraper,
    dag=dag
)

scraper_task
