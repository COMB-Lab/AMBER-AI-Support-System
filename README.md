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


Tutorial Scraper R&D & Pipeline
--------------------------------

## Overview

This repository includes a production-capable scraper for AmberMD tutorials
(from https://ambermd.org/tutorials) and associated ingestion pipeline. The
scraper discovers tutorial pages, extracts structured content (sections,
headings, paragraphs), and emits two outputs:

- **Per-tutorial JSON**: `data/tutorials/<slug>.json` containing title, sections,
  full_text, and source URL
- **Chunked JSONL**: `data/tutorials_chunks/<slug>_chunks.jsonl` with `{id, text,
  metadata}` records ready for vector database ingestion

## R&D Summary & Approach

### Goals
- Reuse existing script patterns and keep modifications minimal
- Respect site structure and be polite (rate limits, user-agent, robots.txt)
- Produce text chunks with metadata so each chunk can be inserted as a Chroma
  document with fields: id, text, metadata

### Strategy

**1. Discovery (index parsing)**
- Fetch the main index at `/tutorials/` and collect all links pointing to
  tutorial pages or directories containing `index.php`
- Accept multiple link styles found on the site (e.g., `basic/tutorial7/index.php`,
  `BuildingSystems.php`)

**2. Fetching pages**
- Use requests with a descriptive User-Agent
- Implement fallback heuristics: if a candidate URL returns 404, try appending
  `/index.php` or requesting the directory URL
- Rate-limit requests (default 0.5s between requests)

**3. Parsing and cleaning**
- Use BeautifulSoup (`lxml`) to parse HTML
- Heuristic selection of main content: prefer `#content`, then `<main>`,
  `<article>`, else fallback to `<body>`
- Remove navigation and unrelated elements (nav, header, footer, breadcrumbs)
- Extract headings and paragraph/code/list nodes into a list of sections:
  `[{heading, text}, ...]`
- Create `full_text` by joining sections

**4. Chunking for ChromaDB**
- Use paragraph-based greedy chunking, grouping paragraphs until reaching a
  character cap (default 2000 chars ≈ ~500 tokens)
- Emit JSONL records with `{id, text, metadata}` where metadata includes `url`
  and `title`

**5. Deduplication & IDs**
- Use stable IDs derived from URL path (slug) plus chunk index
- When ingesting into Chroma, choose `document_id` or `id` consistently to allow
  upserts

### Prototype Behavior & Limitations
- HTML on the site is heterogeneous; the parser uses conservative heuristics and
  requires manual inspection of failed pages
- This prototype does not execute JavaScript (uses requests + BeautifulSoup). If
  some tutorials rely on JS to render content, a headless-browser approach
  (Playwright/Selenium) will be required

## How to Run the Tutorial Scraper

### Setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Run the scraper

```powershell
python .\scripts\scrape_amber_tutorials.py
```

**Default**: runs in safe demo mode (limit=10 pages). To run full discovery,
pass `--limit None` or edit the script.

**CLI options**:
- `--limit N` (default: 10) — max pages to scrape
- `--domain DOMAIN` (default: https://ambermd.org) — base domain
- `--delay SECONDS` (default: 0.5) — seconds between requests
- `--checkpoint PATH` (default: checkpoints/) — checkpoint directory

**Example**: scrape with custom delay and limit

```powershell
python .\scripts\scrape_amber_tutorials.py --limit 50 --delay 1.0
```

### Outputs
- `data/tutorials/` — per-page JSON for manual inspection and QA
- `data/tutorials_chunks/` — JSONL files with `{id, text, metadata}` ready for
  Chroma ingestion

## Chroma Ingestion

### Load tutorial chunks into Chroma

```powershell
python .\scripts\chroma_ingest.py --jsonl-dir data/tutorials_chunks/
```

**CLI options**:
- `--jsonl-dir DIR` (default: data/tutorials_chunks/) — location of chunk JSONL
  files
- `--chroma-collection NAME` (default: amber_tutorials) — Chroma collection name
- `--openai-embed` — generate embeddings via OpenAI API (requires `OPENAI_API_KEY`
  env var)
- `--chroma-host HOST` (default: None — uses local client) — remote Chroma server
  host

**Example**: ingest with OpenAI embeddings into a remote Chroma server

```powershell
$env:OPENAI_API_KEY = "sk-..."
python .\scripts\chroma_ingest.py --openai-embed --chroma-host http://localhost:8000
```

## Production Next Steps

### 1. Robustness
- Replace heuristics with per-section extraction rules if the site has consistent
  templates
- Add retry/backoff and per-page caching to avoid repeated downloads
- Implement comprehensive error logging and per-page failure reporting

### 2. Politeness & Scale
- Honor `robots.txt` and consider site owner contact
- Add configurable concurrency limits; consider a job queue and checkpointing
  (persist processed URLs)
- Respect crawl-delay directives in robots.txt

### 3. Content Normalization
- Normalize code blocks and file downloads; extract example input files when
  available
- Store language metadata for code snippets
- Handle tables and complex formatting consistently

### 4. QA & Human Review
- Provide a small UI (static HTML or simple notebook) for subject matter experts
  to review parsed pages and flag OCR/parse errors
- Collect feedback to refine parsing heuristics

### 5. Security & Licensing
- Respect site terms and license; Amber tutorials are educational material
- Check site terms before mass scraping and downstream distribution
- Document any restrictions on redistribution or derivative works

## Reference: Sample Chroma Ingestion (Pseudocode)

```python
import chromadb
import json

client = chromadb.Client()
col = client.create_collection('amber_tutorials')

# Read chunked JSONL
with open('data/tutorials_chunks/tutorial_001_chunks.jsonl') as f:
    docs = [json.loads(line) for line in f]
    texts = [d['text'] for d in docs]
    metadatas = [d['metadata'] for d in docs]
    ids = [d['id'] for d in docs]
    
    # Obtain embeddings via your chosen embedding function (OpenAI, HuggingFace, etc.)
    # embeddings = [...] 
    
    # Upsert into Chroma
    col.add(ids=ids, documents=texts, metadatas=metadatas)
    # col.upsert(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
```


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