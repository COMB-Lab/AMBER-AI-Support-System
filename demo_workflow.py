from retriever import StubRetriever
from prompt_builder import build_prompt
from llm_interface import HuggingFaceLLM
from real_data import load_query_and_messages
import json

# def load_query(json_path: str) -> str:
#     with open(json_path, "r", encoding="utf-8") as f:
#         data = json.load(f)
#     return data.get("query", "")

def run_demo():
    query, messages = load_query_and_messages("thread_level.json")

    retriever = StubRetriever()
    retriever.add(messages)
    retrieved_docs = retriever.query(query, n_results=1)

    prompt = build_prompt(query, retrieved_docs)
    llm = HuggingFaceLLM()
    answer = llm.generate(prompt)

    print("Generated Answer:\n", answer)


if __name__ == "__main__":
    run_demo()
