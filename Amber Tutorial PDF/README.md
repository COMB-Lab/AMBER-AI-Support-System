# AMBER25 PDF Storage

## Overview
This project downloads the AMBER25 PDF tutorial and performs semantic search using SentenceTransformers.

---

## Features
- Download the AMBER25 PDF
- Extract text from the PDF
- Create text chunks
- Generate embeddings
- Search the PDF using a query

---

## Files

```text
amber25_download_and_embed.py
Amber25.pdf
README.md
```

---

## Requirements

Install the required packages:

```bash
pip install requests pypdf sentence-transformers torch
```

---

## Run the Script

```bash
python amber25_download_and_embed.py
```

---

## Example Query

```python
query="Amber25 tutorial"
```

---

## Attribution

The embedding and search implementation is based on a reference script provided by the course TA.

---

## Author

Alejandro Urbano
