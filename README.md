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

