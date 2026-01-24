from __future__ import annotations
import os, json, sqlite3, glob, pathlib
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

# === CONFIG (edit paths if needed) ===
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../Data Scraping & Cleaning
PROJECT_SCRIPTS = REPO_ROOT / "scripts"
PROJECT_DATA = REPO_ROOT / "data"            # final output directory (already used by your team)
AIRFLOW_ROOT = REPO_ROOT / "airflow"
RUNS_DIR = AIRFLOW_ROOT / "runs"             # per-run scratch (kept out of git)
STATE_DIR = AIRFLOW_ROOT / "state"           # dedupe checkpoint (kept out of git)
STATE_DB = STATE_DIR / "seen_ids.sqlite"     # SQLite with a single 'seen(message_id TEXT PRIMARY KEY)'

SCRAPER_CMD = f"python '{(PROJECT_SCRIPTS / 'run_pipeline.py').as_posix()}'"

DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,           # optional: set airflow SMTP once if you want emails
    "email": ["alerts@yourcompany.com"]
}

def _prep_dirs(ds: str, **_):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS_DIR / ds.replace("-", "")
    run_dir.mkdir(parents=True, exist_ok=True)
    # ensure SQLite exists
    conn = sqlite3.connect(STATE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (message_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()
    return str(run_dir)

def _validate_output(ti, **_):
    run_dir = pathlib.Path(ti.xcom_pull(task_ids="prep_dirs"))
    files = []
    for pat in ("**/*.json", "**/*.jsonl", "**/*.csv"):
        files += glob.glob(str(run_dir / pat), recursive=True)
    if not files:
        raise RuntimeError(f"No output produced in {run_dir}")
    return files

def _dedupe_and_finalize(ti, ds: str, **_):
    """
    Read the run's JSON/JSONL, drop rows whose message_id we've already seen,
    append only new rows to the repo's /data/YYYYMMDD_new.jsonl, and update SQLite.
    """
    run_dir = pathlib.Path(ti.xcom_pull(task_ids="prep_dirs"))
    output_file = (PROJECT_DATA / f"{ds.replace('-', '')}_new.jsonl")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(STATE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS seen (message_id TEXT PRIMARY KEY)")
    cur = conn.cursor()

    def is_new(mid: str) -> bool:
        if not mid:
            return False
        try:
            cur.execute("INSERT OR IGNORE INTO seen(message_id) VALUES (?)", (mid,))
            return cur.rowcount == 1  # inserted => new
        except sqlite3.DatabaseError:
            return False

    written = 0
    with output_file.open("a", encoding="utf-8") as out:
        for p in sorted(run_dir.rglob("*.json")):
            text = p.read_text(encoding="utf-8").strip()
            if not text:
                continue
            # JSONL vs JSON array/single
            if "\n" in text and text.lstrip().startswith("{"):
                lines = text.splitlines()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    mid = d.get("message_id") or d.get("id") or d.get("url")
                    if is_new(mid):
                        out.write(json.dumps(d, ensure_ascii=False) + "\n")
                        written += 1
            else:
                obj = json.loads(text)
                if isinstance(obj, list):
                    for d in obj:
                        mid = d.get("message_id") or d.get("id") or d.get("url")
                        if is_new(mid):
                            out.write(json.dumps(d, ensure_ascii=False) + "\n")
                            written += 1
                else:
                    d = obj
                    mid = d.get("message_id") or d.get("id") or d.get("url")
                    if is_new(mid):
                        out.write(json.dumps(d, ensure_ascii=False) + "\n")
                        written += 1
    conn.commit()
    conn.close()
    return {"written": written, "output_file": str(output_file)}

with DAG(
    dag_id="amber_daily_files_only",
    description="Run existing scraper daily (3:00 PT), dedupe to files, no DB/RAG.",
    default_args=DEFAULT_ARGS,
    schedule_interval="0 3 * * *",   # 03:00 PT daily
    start_date=datetime(2025, 10, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    tags=["data-eng","daily","scraper"],
) as dag:

    prep_dirs = PythonOperator(
        task_id="prep_dirs",
        python_callable=_prep_dirs,
        op_kwargs={"ds": "{{ ds }}"},
    )

    # Call YOUR existing orchestrator exactly as-is.
    run_scraper = BashOperator(
        task_id="run_scraper",
        bash_command=(
            'RUN_DIR="{{ ti.xcom_pull(task_ids=\'prep_dirs\') }}" && '
            'echo "[run_scraper] Output: $RUN_DIR" && '
            f"{SCRAPER_CMD} --outdir \"$RUN_DIR\""
        ),
        env={"PYTHONUNBUFFERED": "1"},
    )

    validate_output = PythonOperator(
        task_id="validate_output",
        python_callable=_validate_output,
    )

    dedupe_finalize = PythonOperator(
        task_id="dedupe_and_finalize",
        python_callable=_dedupe_and_finalize,
        op_kwargs={"ds": "{{ ds }}"},
    )

    prep_dirs >> run_scraper >> validate_output >> dedupe_finalize