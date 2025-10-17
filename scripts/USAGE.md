# Usage & Troubleshooting

This document explains how to set up the environment and run the included
scripts on Windows (PowerShell) and general tips for Airflow.

1) Create a virtual environment and install requirements

PowerShell:

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

2) Fetch a single message (proof-of-capability)

PowerShell:

python .\scripts\fetch_single_email.py

Options:
--url "http://archive.ambermd.org/202204/0000.html"
--out "data/html/202204/0000.html"

3) Parse a single message

python .\scripts\parse_single_email.py --in data/html/202204/0000.html

4) Crawl a month (demo)

python .\scripts\crawl_archive.py --start-year 2022 --end-year 2022 --months 4 --delay 0.5

5) Re-parse all downloaded HTML files

python .\scripts\reparse_all.py

6) Merge threads

python .\scripts\merge_threads.py

7) Load into SQLite

python .\scripts\load_to_sqlite.py

8) Link replies (best-effort)

python .\scripts\link_replies.py

Airflow notes
-------------
- Copy `airflow/dags/amber_crawl_dag.py` into your Airflow `dags` folder.
- Airflow must be installed and configured separately (see Airflow docs). Use
  a pinned Airflow version compatible with your Python version.
- Configure your Airflow environment so the DAG can access the project path
  (or install the project into the Airflow worker environment).

Troubleshooting
---------------
- If `requests` fails with TLS or SSL errors, ensure your Python is up-to-date
  and CA certificates are present. On Windows, installing the latest Python
  from python.org often resolves issues.
- If you see parse differences (missing fields), re-run `reparse_all.py` after
  any parser changes.
- If Airflow DAG doesn't appear, verify `AIRFLOW_HOME` and `dags_folder`, and
  that the scheduler is running.

Contact
-------
If you need help adapting this to production (Postgres, containerized Airflow,
or hosted SLACK notifications), I can help implement those steps.
