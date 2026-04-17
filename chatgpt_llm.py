from openai import OpenAI

# Initialize OpenAI client
client = OpenAI(api_key="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")

# --------------------------------------------------------
#                  SYSTEM PROMPT
# --------------------------------------------------------
SYSTEM_PROMPT = """
You are AmberRAG, an expert AI assistant specializing in the AMBER molecular
dynamics suite and AmberTools workflows.

You answer questions clearly and accurately.

- Provide direct answers first
- Then give concise technical explanations
- Do not fabricate commands or flags
- If unsure, say so
"""

# --------------------------------------------------------
#                  BUILD PROMPT
# --------------------------------------------------------
def build_prompt(question: str):
    return [
        # System message defines assistant behavior
        {"role": "system",
        "content": SYSTEM_PROMPT},

        # User message contains context + question
        {"role": "user",
        "content": question}
    ]

# --------------------------------------------------------
#                  GENERATE (OPENAI)
# --------------------------------------------------------
def generate_chatgpt(messages, model="gpt-5-mini", temperature=0.2):
    """
    Sends messages to OpenAI ChatGPT model.
    """

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature
    )

    return response.choices[0].message.content.strip()

# --------------------------------------------------------
#                  MAIN EXECUTION
# --------------------------------------------------------
def run_chatgpt(question):
    messages = build_prompt(question)
    chatgpt_answer = generate_chatgpt(messages)

    return {
        "answer": chatgpt_answer
    }
