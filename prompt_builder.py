from typing import List, Tuple
from data_schema import Doc

def _trim(text: str, max_len: int = 300) -> str:
    t = " ".join(text.split())
    return t if len(t) <= max_len else t[: max_len - 1].rsplit(" ", 1)[0] + "…"

def build_prompt(query: str, retrieved_docs: List[Doc]) -> Tuple[str, str, List[Tuple[int, Doc]]]:
    """
    Returns:
      system: system message
      user:   user message with [[n]]-labeled context
      items:  list of (index, Doc) for citation mapping
    """
    system = (
        "You are an expert assistant for Amber (AmberTools, sander, pmemd, tleap, cpptraj, antechamber). "
        "Answer accurately and concisely, grounded ONLY in the provided context. "
        "If uncertain, say what would reduce uncertainty. Cite with [[n]]."
    )

    items: List[Tuple[int, Doc]] = []
    lines: List[str] = []
    for i, d in enumerate(retrieved_docs, start=1):
        items.append((i, d))
        lines.append(f"- [[{i}]] {_trim(d.text)}")

    context_block = "\n".join(lines) if lines else "- [[1]] No context found."

    user = (
        f"Question:\n{query}\n\n"
        f"Context:\n{context_block}\n\n"
        "Instructions:\n"
        "1) Provide clear, step-by-step guidance where appropriate.\n"
        "2) Note relevant Amber tools/versions/OS if needed.\n"
        "3) Include commands or input snippets only if helpful.\n"
        "4) Cite with [[n]] corresponding to the context.\n"
    )
    return system, user, items