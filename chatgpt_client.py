import os
from typing import Optional


def generate_chatgpt_answer(
    question: str,
    model: Optional[str] = None,
    max_output_tokens: int = 500,
) -> str:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "The openai package is required for ChatGPT evaluation. Install it with `python -m pip install openai`."
        ) from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)
    model_name = model or os.getenv("OPENAI_MODEL", "gpt-5.2")

    response = client.responses.create(
        model=model_name,
        instructions=(
            "You are Amber Support Assistant. "
            "Answer the user's AMBER question as clearly and directly as possible. "
            "Do not invent citations."
        ),
        input=question,
        max_output_tokens=max_output_tokens,
    )
    return (response.output_text or "").strip()
