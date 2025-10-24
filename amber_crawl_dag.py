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


def _run_load_to_sqlite():
    """Picklable wrapper to load and run scripts/load_to_sqlite.py.

    This avoids using a lambda as python_callable which is not picklable and will
    fail under executors that require picklable callables (Celery, Kubernetes).
    """
    loader_path = os.path.join(PROJECT_DIR, 'scripts', 'load_to_sqlite.py')
    # Use modern importlib utilities to load the module from file
    import importlib.util

    spec = importlib.util.spec_from_file_location('load_to_sqlite', loader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Cannot load module from {loader_path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Call the script's main() if present, otherwise try run top-level main
    if hasattr(mod, 'main'):
        return mod.main()
    # fallback: nothing to do
    return None


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
        python_callable=_run_load_to_sqlite,
        on_failure_callback=on_failure_callback,
    )

    task_crawl >> task_reparse >> task_load_db
