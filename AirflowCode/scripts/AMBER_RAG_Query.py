import os, json, argparse, sys
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--question", required=True, help="Natural-language query to search.")
    p.add_argument("--k", type=int, default=4, help="Top-k results")
    p.add_argument("--emb_model", default="sentence-transformers/all-MiniLM-L6-v2")
    p.add_argument("--chroma_dir", default=os.environ.get("CHROMA_DIR", "/opt/airflow/data/chroma_db"))
    args = p.parse_args()

    # Load vector store (must match the embedding used at index time)
    emb = HuggingFaceEmbeddings(model_name=args.emb_model)
    db = Chroma(persist_directory=args.chroma_dir, embedding_function=emb)

    # Retrieve
    docs_scores = db.similarity_search_with_score(args.question, k=args.k)

    # Shape a concise, machine-friendly result for Airflow logs/XCom scraping
    out = {
        "question": args.question,
        "k": args.k,
        "results": [
            {
                "score": float(score),
                "content": doc.page_content,
                "metadata": doc.metadata,
                "id": getattr(doc, "id", None),
            }
            for doc, score in docs_scores
        ],
    }

    print(json.dumps(out, ensure_ascii=False))  # visible in task logs
    return 0

if __name__ == "__main__":
    sys.exit(main())
