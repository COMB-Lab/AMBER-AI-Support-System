# Amber Tutorial Scraping

## Overview

This project scrapes tutorial content from the Amber website and saves the extracted data into structured JSON files. The goal is to prepare Amber tutorial data so it can be used by the database team and the RAG chatbot pipeline.

## Purpose

The scraper is used to collect Amber tutorial information such as:

- Tutorial titles
- Tutorial URLs
- Page sections
- Headings
- Text content

The scraped data is then processed into chunked JSON files for embeddings, database storage, and retrieval in the chatbot system.

---

# Output Files

## `amber_tutorials.json`

This file contains the scraped Amber tutorials in one combined JSON file.

## `amber_chunks.json`

This file contains smaller text chunks from the tutorials. These chunks are useful for embeddings and RAG retrieval.

## `amber_chunks_big.json`

This file stores each tutorial as one large chunk. This format was created for the database team so each tutorial can be stored as a single entry.


---

# How to Run

## 1. Install Dependencies

```bash
pip install requests beautifulsoup4
```

## 2. Run the Scraper

```bash
python scrape_amber.py
```

This creates:

```text
output/amber_tutorials.json
```

## 3. Generate Smaller Chunks

```bash
python chunk_tutorials.py
```

This creates:

```text
chunks/amber_chunks.json
```

## 4. Generate One Big Chunk Per Tutorial

```bash
python chunk_tutorials_big.py
```

This creates:

```text
chunks/amber_chunks_big.json
```

---

# JSON Format

## Example from `amber_chunks.json`

```json
{
  "id": "1.1_p0_s0_c0",
  "text": "Learning Outcomes...",
  "tutorial_label_id": "1.1",
  "tutorial_title": "Preparing Structure",
  "tutorial_url": "https://ambermd.org/tutorials/basic/tutorial9/index.php",
  "page_url": "https://ambermd.org/tutorials/basic/tutorial9/index.php",
  "heading": "Learning Outcomes",
  "section_type": "text"
}
```

## Example from `amber_chunks_big.json`

```json
{
  "id": "1.1",
  "text": "Amber Tutorial: Preparing Structure...",
  "metadata": {
    "tutorial_label_id": "1.1",
    "tutorial_title": "Preparing Structure",
    "tutorial_url": "https://ambermd.org/tutorials/basic/tutorial9/index.php",
    "source": "Amber Tutorials",
    "chunk_type": "full_tutorial"
  }
}
```

---

# Challenges

Some tutorial links returned 404 errors. Based on project guidance, these links were not fixed individually. Instead, the scraper focuses on collecting and consolidating the tutorial pages that are available and working.


---

# Current Status

The scraper successfully extracts Amber tutorial content and creates structured JSON files. The data is ready for database storage, embedding generation, and RAG chatbot integration.

---

# Author

Alejandro Urbano
