from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator # type: ignore

BASE = "/opt/airflow/dags/scripts"
CHROMA_DIR = "/opt/airflow/data/chroma_db"
DATA_DIR = "/opt/airflow/data"

default_args = {
    "owner": "data",
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
}

with DAG(
    dag_id="AMBER_Daily_Scraping",
    description="Run AMBER scrapers sequentially: web → json → check replies",
    start_date=datetime(2025, 10, 15),
    # schedule="@daily",
    schedule=None,   # DEBUG ONLY
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["amber"],
) as dag:

    amber_web = BashOperator(
        task_id="amber_web_scrape",
        bash_command=f"cd {BASE} && python AMBER_WEB_Scraping.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_json = BashOperator(
        task_id="amber_json_scrape",
        bash_command=f"cd {BASE} && python AMBER_JSON_Scraping.py",
        env={"DATA_DIR": DATA_DIR},
    )

    amber_check = BashOperator(
        task_id="amber_check_replies",
        bash_command=f"cd {BASE} && python AMBER_Check_Replies.py",
        env={"DATA_DIR": DATA_DIR},
    )

    # NEW: RAG query task (can run after the scrapes, or independently)
    amber_query = BashOperator(
    task_id="amber_rag_query",
    bash_command=(
        f'cd {BASE} && '
        'python AMBER_RAG_Query.py '
        '--question "{{ dag_run.conf.get(\'question\', \'What changed?\') }}" '
        f'--k 4 --chroma_dir "{CHROMA_DIR}"'
    ),
    env={
        "CHROMA_DIR": CHROMA_DIR,
        "DATA_DIR": DATA_DIR,
        },
    )

    # Typical flow: run query last
    amber_web >> amber_json >> amber_check >> amber_query
