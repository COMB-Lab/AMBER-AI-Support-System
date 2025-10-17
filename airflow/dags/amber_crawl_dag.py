from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def on_failure_callback(context):
    """Notify on failure using the notify helper if available."""
    try:
        notify_path = os.path.join(PROJECT_DIR, 'scripts', 'notify_on_failure.py')
        # import as module and call notify(context)
        from importlib.machinery import SourceFileLoader

        mod = SourceFileLoader('notify_on_failure', notify_path).load_module()
        mod.notify_on_failure(context)
    except Exception as e:
        # best-effort: write to a local failures log
        with open(os.path.join(PROJECT_DIR, 'airflow_failure.log'), 'a', encoding='utf-8') as f:
            f.write(f"{datetime.utcnow().isoformat()} - Failed to notify: {e}\n")


default_args = {
    'owner': 'amber_team',
    'depends_on_past': False,
    'email_on_failure': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


with DAG(
    dag_id='amber_archive_daily_crawl',
    default_args=default_args,
    description='Daily crawl of Amber archive and load into DB',
    schedule_interval='@daily',
    start_date=datetime(2025, 10, 1),
    catchup=False,
    max_active_runs=1,
) as dag:

    # Crawl command: run crawler for the month of execution_date
    crawl_cmd = (
        f"python {os.path.join(PROJECT_DIR, 'scripts', 'crawl_archive.py')}"
        " --start-year {{execution_date.year}} --end-year {{execution_date.year}} --months {{execution_date.month}} --delay 0.5"
    )

    task_crawl = BashOperator(
        task_id='crawl_month',
        bash_command=crawl_cmd,
        on_failure_callback=on_failure_callback,
    )

    task_reparse = BashOperator(
        task_id='reparse_all',
        bash_command=f"python {os.path.join(PROJECT_DIR, 'scripts', 'reparse_all.py')}",
        on_failure_callback=on_failure_callback,
    )

    task_load_db = PythonOperator(
        task_id='load_to_sqlite',
        python_callable=lambda: __import__('importlib').machinery.SourceFileLoader('load_to_sqlite', os.path.join(PROJECT_DIR, 'scripts', 'load_to_sqlite.py')).load_module().main(),
        on_failure_callback=on_failure_callback,
    )

    task_crawl >> task_reparse >> task_load_db
