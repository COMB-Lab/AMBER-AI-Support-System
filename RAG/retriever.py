from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


class ChromaRetriever:
    def __init__(
        self,
        persist_directory: str = "/opt/chromadb/data/prompt_db",
        embedding_model_name: str = "all-MiniLM-L6-v2",
        top_k: int = 8,
    ):
        self.top_k = top_k
        self.embedding_model = HuggingFaceEmbeddings(
            model_name=embedding_model_name
        )

        self.vectorstore = Chroma(
            persist_directory=persist_directory,
            embedding_function=self.embedding_model,
        )

    def retrieve(self, query: str):
        results = self.vectorstore.similarity_search(query, k=self.top_k)

        out = []
        for r in results:
            out.append(
                {
                    "text": r.page_content,
                    "metadata": r.metadata,
                }
            )

        return out