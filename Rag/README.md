## 1.) Run AMBER_Extract_Tutorial.py

This script scrapes and extracts the tutorial page **https://ambermd.org/tutorials/** and creates a JSONL file
called **amber_tutorials.jsonl**

## 2.) Run ChromaDB_Ingestion.py 

This script ingests all the data created from **amber_tutorials.jsonl** into the ChromaDB library. It will
provide you with a folder called **chroma_db** with subfolders that have **.bin** and **.sqlite3** files.

