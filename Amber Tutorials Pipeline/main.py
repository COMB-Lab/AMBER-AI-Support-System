from discover_tutorials import discover_tutorial_links
from scrape_tutorial import scrape_tutorial
from store_chroma import init_chroma, store_chunks
from config import *
from tqdm import tqdm

def main():
    client, collection = init_chroma(
        CHROMA_PERSIST_DIR,
        COLLECTION_NAME
    )

    tutorial_links = discover_tutorial_links()
    all_chunks = []

    for url in tqdm(tutorial_links, desc="Scraping Amber Tutorials"):
        all_chunks.extend(scrape_tutorial(url))

    store_chunks(
        all_chunks,
        collection,
        EMBEDDING_MODEL
    )

    client.persist()
    print(f"Ingested {len(all_chunks)} tutorial chunks")

if __name__ == "__main__":
    main()
