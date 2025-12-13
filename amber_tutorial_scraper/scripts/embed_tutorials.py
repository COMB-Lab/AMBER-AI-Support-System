import os
import json
import chromadb
from sentence_transformers import SentenceTransformer

# --- CONFIG ---
CLEAN_DIR = "tutorial_data/cleaned"      
EMBEDDING_MODEL = "all-MiniLM-L6-v2"      
COLLECTION_NAME = "amber_tutorials"       


os.makedirs("tutorial_data/embeddings", exist_ok=True)


model = SentenceTransformer(EMBEDDING_MODEL)


client = chromadb.Client()

# Create or get collection
if COLLECTION_NAME in [c.name for c in client.list_collections()]:
    collection = client.get_collection(COLLECTION_NAME)
else:
    collection = client.create_collection(name=COLLECTION_NAME)


with open(os.path.join(CLEAN_DIR, "tutorials_cleaned.json"), "r", encoding="utf-8") as f:
    tutorials = json.load(f)

# --- GENERATE EMBEDDINGS AND STORE ---
for tut in tutorials:
    content = tut["content"]
    tut_id = tut["file"]  # unique ID for the tutorial
    vector = model.encode(content).tolist()  # convert embedding to list

    collection.add(
        ids=[tut_id],
        documents=[content],
        metadatas=[{"source": tut_id}],
        embeddings=[vector]
    )


