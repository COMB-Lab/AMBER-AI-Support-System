import requests

OLLAMA_URL = "http://127.0.0.1:11434"


SYSTEM_PROMPT = """
You are AmberRAG, an expert AI assistant specializing in the AMBER molecular
dynamics suite and AmberTools workflows.

You answer questions clearly and accurately.

- Provide direct answers first
- Then give concise technical explanations
- Do not fabricate commands or flags
- If unsure, say so
"""

def build_prompt(question: str):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]


def generate_llama(messages, model="llama3.1:latest", temperature=0.2):

    prompt = ""

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "system":
            prompt += f"System: {content}\n"
        elif role == "user":
            prompt += f"User: {content}\n"
        elif role == "assistant":
            prompt += f"Assistant: {content}\n"

    prompt += "Assistant:"

    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": False
        },
        timeout=60
    )

    print("Received response")

    response.raise_for_status()

    return response.json()["response"].strip()


def run_no_rag(question):
    messages = build_prompt(question)
    no_rag_answer = generate_llama(messages)

    return {
        "answer": no_rag_answer
    }