Fetch a single Amber archive email page and save raw HTML.

Run:

python scripts/fetch_single_email.py

Output: data/html/202204/0000.html (by default)

Airflow (optional)
------------------
To run the daily automated crawl using Airflow, place the DAG in an Airflow
`dags` folder (this repo contains `airflow/dags/amber_crawl_dag.py`). The DAG
will: crawl the monthly archive for the DAG execution date month, reparse
downloaded HTML into JSON, and load merged threads into a local SQLite DB at
`data/amber_messages.db`.

Key notes:
- The loader uses `message_id` as the PRIMARY KEY in SQLite to avoid duplicates.
- Notifications on failure write to `airflow_failure_notifications.log`; you can
	replace `scripts/notify_on_failure.py` with a real email/Slack notifier.
- Install Airflow separately and configure the `AIRFLOW_HOME` and DAGs folder
	per Airflow docs. The DAG uses bash/python operators to invoke the scripts.

Quick script usage
------------------
Below are the main scripts in this repository and example commands to run them
manually. Run these from the repo root.

1) Fetch a single message (proof-of-capability)

python scripts/fetch_single_email.py

Optional args:
--url URL (default: http://archive.ambermd.org/202204/0000.html)
--out PATH (default: data/html/202204/0000.html)

2) Parse a single downloaded HTML into JSON

python scripts/parse_single_email.py --in data/html/202204/0000.html

Optional args:
--out PATH (default: data/json/html/202204/0000.json)
--url URL (original page URL, optional)

3) Crawl monthly archives (demo / small runs)

python scripts/crawl_archive.py --start-year 2022 --end-year 2022 --months 4

Options:
--start-year, --end-year: numeric year range to crawl
--months: comma-separated months (e.g., "1,2,3" or single "4")
--delay: seconds to sleep between requests (default 0.5)

4) Re-parse all downloaded HTML files (useful after parser updates)

python scripts/reparse_all.py

5) Merge parsed per-message JSON into per-thread JSON files

python scripts/merge_threads.py

Output: data/threads_merged/<sanitized-subject>.json

6) Load merged threads into a local SQLite DB (deduplicated)

python scripts/load_to_sqlite.py

Output: data/amber_messages.db (table `messages` with message_id primary key)

7) Link replies across parsed messages (best-effort heuristics)

python scripts/link_replies.py

This script attempts to add `replies` arrays to per-message JSON and write an
index `data/links/replies_index.json`. It uses normalized subjects and nav
titles; for more reliable linking, run a full crawl + parse of neighboring
messages so nav hrefs can be used.

Airflow DAG
-----------
If you run Airflow, drop `airflow/dags/amber_crawl_dag.py` into your DAGs
folder. The DAG will run daily and call the scripts above. Update the DAG
if you want different schedule, an alternate crawl window, or to run on a
different executor.

Dependencies
------------
Install required packages:

pip install -r requirements.txt

Note: Airflow must be installed following Apache Airflow's official docs and
is not installed via this repo's `requirements.txt` by default.


Tutorials scraping (R&D prototype)
----------------------------------
This repository includes a prototype scraper for the Amber tutorials and a
short R&D report describing the approach. The prototype is purpose-built to
discover tutorial pages, extract the main text and headings, and emit two
outputs suitable for downstream use:

- Per-tutorial JSON files: `data/tutorials/<slug>.json` (title, sections,
	full_text, url)
- Chunked JSONL files for vector DB ingestion: `data/tutorials_chunks/<slug>_chunks.jsonl`

How to run the tutorial scraper (PowerShell)

1) Create and activate a virtualenv and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Run the prototype (demo mode — limited):

```powershell
python .\scripts\scrape_amber_tutorials.py
```

By default the script runs in a safe demo mode (limit=10). To run the full
discovery edit the script or call `main(limit=None)` from a small wrapper.

Outputs and next steps
- `data/tutorials/` — per-page JSON for manual inspection and QA
- `data/tutorials_chunks/` — JSONL files with `{id,text,metadata}` ready for
	embedding + upsert into a vector DB (Chroma). See `docs/amber_tutorials_scrape_report.md`
	for details and suggested chunk sizes.


Airflow R&D — how to wire and test the workflow
-----------------------------------------------
This project contains an Airflow DAG (`airflow/dags/amber_crawl_dag.py`) that
orchestrates the existing scripts on a daily schedule. The DAG was written to
reuse the existing Python scripts with minimal modification and to provide
basic failure notification.

Key notes for testing and running the DAG locally

- Place the DAG file in your Airflow `dags/` folder (or configure Airflow to
	include this repository's `airflow/dags/` path).
- The DAG uses `@daily` scheduling and `catchup=False` by default.
- Tasks use `on_failure_callback` to call `scripts/notify_on_failure.py` (a
	placeholder logger) and the loader uses a picklable top-level wrapper so the
	DAG is compatible with executors that require picklable callables (Celery,
	Kubernetes).

Testing tips (PowerShell)

1) Quick syntax check (fast, no Airflow required):

```powershell
python -m py_compile .\airflow\dags\amber_crawl_dag.py
```

2) Run a local end-to-end test that mirrors what the DAG does (no Airflow
	 required). This repo includes `scripts/test_pipeline_run.py` which runs a
	 demo crawl (April 2022), reparse, merge, and load steps, then prints DB
	 counts.

```powershell
python .\scripts\test_pipeline_run.py
```

3) If you run Airflow locally and want to test tasks using the Airflow CLI
	 (Airflow must be installed and initialized):

```powershell
# test a single task
airflow tasks test amber_archive_daily_crawl crawl_month 2025-10-24

# test the full DAG run
airflow dags test amber_archive_daily_crawl 2025-10-24
```

Deployment and production notes
- For production, run Airflow with a proper metadata DB (Postgres) and an
	executor suitable for your scale (Celery or Kubernetes). The DAG's
	PythonOperator is picklable and should work with those executors.
- Harden the scripts before production: add retries/backoff, per-URL
	checkpointing, and robust parsing (use BeautifulSoup per the tutorials
	prototype). Ensure `message_id` stability (the DB dedupe depends on it).
- The repo includes a `Dockerfile` and `docker-compose.yml` to run the
	pipeline as a container; see the repo top-level files if you'd prefer to
	run the pipeline in containers rather than installing Airflow locally.

If you want, I can add a short CI job (GitHub Actions) that runs the demo
test on push, or I can add a Chroma ingestion script to take the tutorial
chunks JSONL and upsert them into a Chroma collection. Tell me which you
prefer and I will add it.


