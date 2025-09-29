from typing import List
from data_schema import Message

class Retriever:
    def add(self, documents: List[Message]):
        raise NotImplementedError

    def query(self, query_text: str, n_results: int = 5) -> List[Message]:
        raise NotImplementedError

class StubRetriever(Retriever):
    def __init__(self):
        self._documents = []

    def add(self, documents: List[Message]):
        self._documents = documents

    def query(self, query_text: str, n_results: int = 5) -> List[Message]:
        # Return the first n messages from the loaded data
        return self._documents[:n_results]