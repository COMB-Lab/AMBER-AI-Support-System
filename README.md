# AMBER-RAG Pipeline

## Overview
This Retrieval-Augmented Generation (RAG) pipeline was designed to answer complex questions for the AMBER software.

Instead of relying on generic LLM knowledge, which frequently hallucinates, this pipeline dynamically pulls from databases to provide highly accurate, context-aware, and cited answers.

## How It Works
This pipeline searches two different databases at the same time to find the best possible answer:
* **Vector Embeddings:** Uses `all-MiniLM-L6-v2` to convert text into vector space.
* **Database 1 (Archives & Tutorials):** Connects to a ChromaDB server containing both historical AMBER troubleshooting discussions and official AMBER tutorials.
* **Database 2 (Manual):** Builds an in-memory FAISS vector index from the `Amber25.pdf` manual.
* **Filtering Process:** The pipeline retrieves the top 5 results from both databases (10 total results), combines them, sorts them by relevance, and strictly filters down to the Top 5 overall chunks before passing them to the LLM. This allows for only the highest ranked context to be used.
* **LLM:** Generates the final response using Llama 3.1 (8B) via Ollama.

## Prerequisites
1. **Python Packages:** `pip install chromadb sentence-transformers faiss-cpu pypdf ollama numpy`
2. **LLM:** Ollama must be running with the Llama 3.1 model:
    `ollama pull llama3.1:8b`
3. **Data Sources:**
    * The `Amber25.pdf` manual must be present in the execution directory.
    * The ChromaDB archive must be located at `/opt/chromadb/data/prompt_db`.

## Usage
Run the pipeline via terminal:
```bash
python rag_pipeline.py
```