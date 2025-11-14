# RAG/prompt_builder.py
import re
from typing import List

NOISE_PATTERNS = [
    r"(?mi)^(>+).*$",                             # quoted lines
    r"(?mi)^(From|Sent|To|Cc|Subject):.*$",       # email headers in body
    r"http[s]?://\S+",                            # raw URLs
    r"(?mi)^--\s*$[\s\S]*?$",                     # signature to end
]

# Lines like: "John Doe (Tue, 7 Jan 2020 15:41:25 -0500): ..."
NAME_DATE_LINE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s*\([^)]+\):")

# Short salutations/closers that add noise
SALUTATION = re.compile(r"(?i)^(hi|hello|dear)\b")
CLOSERS = re.compile(r"(?i)\b(thanks|thank you|best regards|best,|cheers)\b")

def _clean_email_like(text: str) -> str:
    t = text
    for pat in NOISE_PATTERNS:
        t = re.sub(pat, "", t)
    # Drop lines that look like "Name (Date):"
    t = "\n".join(line for line in t.splitlines() if not NAME_DATE_LINE.match(line.strip()))
    # Collapse whitespace
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()

DOMAIN = re.compile(r"\b(amber|molecular|dynamics|md|force\s*field|simulation|biomolec|protein|nucleic|ligand|trajectory|analysis)\b", re.I)

# --- replace your existing _sentences + compress_context with this ---

CLUSTER_DOMAIN = re.compile(r"\b(cluster|clustering|k-?means|hierarchical|dbscan|rmsd|cpptraj)\b", re.I)

def _sentences(text: str, require_cluster: bool = False) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text.strip())
    out = []
    for s in parts:
        s = s.strip()
        if not s or len(s) < 20 or len(s) > 400:
            continue
        if NAME_DATE_LINE.match(s) or SALUTATION.match(s) or CLOSERS.search(s):
            continue
        if not DOMAIN.search(s):
            continue
        if require_cluster and not CLUSTER_DOMAIN.search(s):
            continue
        out.append(s)
    return out

def compress_context(query: str, docs: List[str], max_sentences: int = 8) -> str:
    cleaned = [_clean_email_like(d) for d in docs if d and d.strip()]
    # if the question is about clustering, only keep clustering-related sentences
    require_cluster = bool(re.search(r"\b(cluster|clustering)\b", query, re.I))
    all_sents: List[str] = []
    for c in cleaned:
        all_sents.extend(_sentences(c, require_cluster=require_cluster))
    if not all_sents:
        # fallback: use lightly cleaned text (still truncated) so the model can synthesize an answer
        return "\n".join(cleaned)[:2000]

    scored = sorted(all_sents, key=lambda s: _keyword_score(query, s), reverse=True)
    picked, seen = [], set()
    for s in scored:
        k = s[:120]
        if k in seen:
            continue
        seen.add(k)
        picked.append(s)
        if len(picked) >= max_sentences:
            break
    return "\n".join(picked)

def _keyword_score(query: str, sentence: str) -> int:
    q = set(re.findall(r"[A-Za-z0-9]+", query.lower()))
    s = set(re.findall(r"[A-Za-z0-9]+", sentence.lower()))
    return len(q & s)

def build_prompt(user_query: str, contexts: List[str], max_ctx_chars: int = 2000) -> str:
    """
    Build a concise, answer-only prompt.
    - If contexts is empty (definition-style query), do NOT include a context block.
    - If contexts is non-empty, compress it and include it, while forbidding copying.
    """
    if not contexts:  # definition mode: no retrieval used
        system = (
            "You are Amber Support Assistant. Answer in 2–3 plain sentences. "
            "Do not restate the question. Do not include names, dates, IDs, file paths, code, or citations. "
            "If uncertain, say so briefly."
        )
        return f"{system}\n\nQuestion: {user_query}\n\nAnswer:"

    # retrieval mode
    focused = compress_context(user_query, contexts, max_sentences=8)[:max_ctx_chars]
    system = (
        "You are Amber Support Assistant. Answer in 2–3 plain sentences. "
        "Use the context only to inform your answer; DO NOT copy phrases, file paths, code, or quotes. "
        "Do not restate the question. Do not include names, dates, IDs, or citations. "
        "If uncertain, say so briefly."
    )
    return (
        f"{system}\n\n"
        f"Question: {user_query}\n"
        "<context>\n"
        f"{focused}\n"
        "</context>\n\n"
        "Answer:"
    )