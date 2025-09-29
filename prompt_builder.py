def build_prompt(query: str, retrieved_docs: list) -> str:
    def trim(text: str, max_len: int = 300):
        return text[:max_len].strip().replace("\n", " ") + ("..." if len(text) > max_len else "")

    context = "\n".join(f"- {trim(doc.body)}" for doc in retrieved_docs)

    return (
        f"You are a scientific assistant helping researchers understand Amber simulation techniques.\n"
        f"Summarize the discussion below and answer the question clearly and thoroughly.\n\n"
        f"Question: {query}\n\n"
        f"Email Messages:\n{context}\n\n"
        f"Answer:"
    )
