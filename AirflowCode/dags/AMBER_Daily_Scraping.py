from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

# Where your scripts live in the container
BASE = "/opt/airflow/dags/scripts"

default_args = {
    "owner": "data",
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
}

with DAG(
    dag_id="AMBER_Daily_Scraping",
    description="Run AMBER scrapers sequentially: web → json → check replies",
    start_date=datetime(2025, 10, 15),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["amber"],
) as dag:

    amber_web = BashOperator(
        task_id="amber_web_scrape",
        bash_command=f"cd {BASE} && python AMBER_WEB_Scraping.py",
    )

    amber_json = BashOperator(
        task_id="amber_json_scrape",
        bash_command=f"cd {BASE} && python AMBER_JSON_Scraping.py",
    )

    amber_check = BashOperator(
        task_id="amber_check_replies",
        bash_command=f"cd {BASE} && python AMBER_Check_Replies.py",
    )

    # Task flow: web → json → check
    amber_web >> amber_json >> amber_check
