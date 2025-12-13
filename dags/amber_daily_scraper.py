from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
     "owner": "amber scraper",
     "retries":1,
     "retry_delay": timedelta(minutes = 5),
}

with DAG(
    dag_id="amber_daily_scraper",
    default_args=default_args,
    schedule_interval=timedelta(days=1),
    start_date=datetime(2025, 1, 1),
    catchup=False,
    max_active_runs=1,
) as dag:

    run_scraper = BashOperator(
        task_id="run_scraper",
        bash_command="cd /media/sf_Amber && python3 amber_scraper_mar2024.py"
    )
