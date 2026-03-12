# Amber Tutorial Scraper Pipeline

This repository provides a simple pipeline for harvesting the AmberMD tutorials. It
can:

1. Crawl the main tutorials index (`https://ambermd.org/tutorials/`) and follow the
   links to HTML pages and PDFs.
2. Download PDFs and extract their text, or scrape HTML pages and get their visible
   text.
3. Chunk the text (using `processing/chunker.py`).
4. Generate embeddings and persist the chunks in a local ChromaDB collection
   (`amber_tutorials`).
5. Optionally dump the scraped content into JSON files for inspection or further
   processing.

## Installation

```bash
pip install -r requirements.txt
```

> **Note:** `sentence-transformers` pulls in `torch`, which may need a Python
> version that PyTorch supports (3.12 or earlier on Windows). If you hit
> installation errors with Python 3.13, create a 3.12/3.11 virtual environment and
> reinstall the dependencies there.

## Running the pipeline

```bash
python run_pipeline.py
```

- The script will create (if missing) the directories `downloaded_pdfs/` and
  `chroma_db/` as needed for PDF storage and the ChromaDB persistence layer.
- **JSON output** is written to a single file:
  `scraped_all_tutorials_output/all_tutorials.json`.
  The file contains one object per source URL with raw text and token chunks.
  If you want to refresh output, delete `scraped_all_tutorials_output/all_tutorials.json`
  and rerun.

## Test utilities

Several helper scripts under `tests/` demonstrate targeted scraping behaviors:

- `test_scrape_store_tutorial_7_4.py` – scrapes Tutorial 3 sections (1–3.6); it
  produces one combined JSON (`tutorial_3_sections.json`) and individual section
  files under `scraped_tutorial3_output/`. Running it clears that folder first
  so outputs are overwritten on each invocation.

## Cleaning up

- Remove `downloaded_pdfs/` to re‑download PDFs.
- Delete `chroma_db/` to reset the vector store (be careful; you’ll lose all
  embeddings).
- Delete any `scraped_*_output` folders to remove JSON exports; they will be
  generated again on the next run.
- `__pycache__/` directories and `.txt` files under `scraped_output/` are
  leftover artifacts and can be safely deleted.

## Extending or customizing

- Add new scraping logic in `scraper/amber_crawler.py` if the site structure
  changes.
- Modify chunking rules in `processing/chunker.py`.
- Adjust storage behavior in `storage/chroma_store.py`.