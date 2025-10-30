from datetime import datetime, timedelta
from airflow import DAG # type: ignore
from airflow.operators.python import PythonOperator # type: ignore
from Scaping import scrape_new_data  # Make sure Scaping.py is in the same dags folder

# ===============================
# Default DAG arguments
# ===============================
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

# ===============================
# Define the DAG
# ===============================
with DAG(
    dag_id="amber_scraper_dag",
    default_args=default_args,
    description="Daily scraper for Amber mailing list archive (2020–2025 incremental updates)",
    schedule_interval=timedelta(days=1),  # Run every 24 hours
    start_date=datetime(2025, 1, 1),
    catchup=False,  # Don't rerun old days
    tags=["amber", "scraper", "automation"],
) as dag:

    # Task: Run scraper
    run_scraper = PythonOperator(
        task_id="run_scraping_script",
        python_callable=scrape_new_data,
    )

    run_scraper
