from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator  # type: ignore

BASE = "/opt/airflow/dags/scripts"
DATA_DIR = "/opt/airflow/data"

default_args = {
    "owner": "data",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="AMBER_Daily_Scraping",
    description="Run AMBER scrapers sequentially: web -> json -> check replies -> tutorial scrape -> tutorial ingestion",
    start_date=datetime(2025, 10, 15),
    schedule=None,   # set to "@daily" when ready
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["amber"],
) as dag:

    amber_web = BashOperator(
        task_id="web_scrape",
        bash_command=f"cd {BASE} && python AMBER_WEB_Scraping.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_json = BashOperator(
        task_id="web_json_scrape",
        bash_command=f"cd {BASE} && python AMBER_JSON_Scraping.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_check = BashOperator(
        task_id="check_replies",
        bash_command=f"cd {BASE} && python AMBER_Check_Replies.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_tutorial = BashOperator(
        task_id="tutorial_scrape",
        bash_command=f"cd {BASE} && python AMBER_Extract_Tutorial.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_ingest_tutorial = BashOperator(
        task_id="tutorial_ingestion",
        bash_command=f"cd {BASE} && python AMBER_Tutorial_ChromaDB_Ingestion.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_web >> amber_json >> amber_check >> amber_tutorial >> amber_ingest_tutorial
