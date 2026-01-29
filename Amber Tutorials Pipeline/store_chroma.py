import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

def init_chroma(persist_dir, collection_name):
    client = chromadb.Client(
        Settings(
            persist_directory=persist_dir,
            anonymized_telemetry=False
        )
    )

    collection = client.get_or_create_collection(name=collection_name)
    return client, collection


def store_chunks(chunks, collection, model_name):
    model = SentenceTransformer(model_name)

    texts = [c["content"] for c in chunks]
    embeddings = model.encode(texts).tolist()

    collection.add(
        documents=texts,
        embeddings=embeddings,
        metadatas=[{
            "source": c["source"],
            "title": c["title"],
            "section": c["section"],
            "url": c["url"]
        } for c in chunks],
        ids=[f"{c['url']}#{i}" for i in range(len(chunks))]
    )
