import os
import requests
from typing import List, Dict, Any


DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")


def generate_ollama(
    messages: List[Dict[str, str]],
    model: str = "llama3.1:8b",
    temperature: float = 0.2,
    ollama_url: str = DEFAULT_OLLAMA_URL,
) -> str:
    """
    Mirrors the notebook:
    - Convert chat messages into a single prompt text:
        System: ...
        User: ...
        Assistant:
    - POST to /api/generate
    """
    prompt_parts: list[str] = []
    for msg in messages:
        role = (msg.get("role") or "").lower()
        content = msg.get("content") or ""
        if role == "system":
            prompt_parts.append(f"System: {content}")
        elif role == "user":
            prompt_parts.append(f"User: {content}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant: {content}")

    prompt_parts.append("Assistant:")
    prompt = "\n".join(prompt_parts)

    resp = requests.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "temperature": float(temperature),
            "stream": False,
        },
        timeout=600,
    )
    resp.raise_for_status()
    return (resp.json().get("response") or "").strip()