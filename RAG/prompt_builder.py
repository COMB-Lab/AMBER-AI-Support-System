from typing import List, Tuple
from RAG.data_schema import Doc

# ---- budgets (≈4 chars/token) ----
MAX_PROMPT_CHARS = 6000
HEADER_RESERVE   = 1400   # was 1200
PER_DOC_MAX      = 500

def _clean(s: str) -> str:
    return " ".join((s or "").split()).strip()

def _clip(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    s = s[: n - 1]
    if " " in s:
        s = s.rsplit(" ", 1)[0]
    return s + "…"


def build_prompt(query: str, retrieved_docs: List[Doc]) -> Tuple[str, str, List[Tuple[int, Doc]]]:
    """
    Returns:
      system: system message
      user:   user message with [[n]] context
      items:  list of (index, Doc) for citation mapping
    """
    system = (
        "You are an expert Amber assistant (AmberTools, sander, pmemd, tleap, cpptraj, antechamber). "
        "Synthesize the answer using ONLY the provided context. Do NOT repeat the context bullets verbatim. "
        "Cite claims inline with [[n]]. If the context is insufficient, say so and state what is missing."
    )

    used = 0
    budget = max(1000, MAX_PROMPT_CHARS - HEADER_RESERVE)
    items: List[Tuple[int, Doc]] = []
    lines: List[str] = []

    for i, d in enumerate(retrieved_docs, start=1):
        snippet = _clip(_clean(d.text), PER_DOC_MAX)
        line = f"- [[{i}]] {snippet}"
        if used + len(line) > budget:
            break
        lines.append(line)
        items.append((i, d))
        used += len(line)

    if not lines:
        lines = ["- [[1]] No context found."]

    context_block = "\n".join(lines)

    user = (
        
        f"QUESTION:\n{_clean(query)}\n\n"
        f"CONTEXT (use for citations):\n{context_block}\n\n"
        "FORMAT:\n"
        "• Start with: ANSWER:\n"
        "• Length: 2–5 sentences max.\n"
        "• Cite with [[n]] immediately after the sentence they support.\n"
        "• Do NOT start the answer with [[n]] and do NOT copy context bullets.\n"
        "• If unclear, say what extra info is needed.\n"
        "... Now write the ANSWER only."
    )

    return system, user, items