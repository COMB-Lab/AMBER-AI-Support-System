# RAG/llm_interface.py
import re
from transformers import pipeline

# ---------- Heuristics ----------
NAME_DATE_LINE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s*\([^)]+\):")
CODEY = re.compile(
    r"[/\\][\w\-.]+|[\w\-.]+\.(c|cpp|h|hpp|py|f90|f|sh|md|txt)"
    r"|`|::|#include|int\s+main|class\s+\w+"
)
NON_SENTENCE = re.compile(r"^[^\w]*$")
FIRST_PERSON = re.compile(r"^(i|we|you)\b", re.I)
QUOTED = re.compile(r"^>")
DOMAIN_ALLOWED = re.compile(
    r"\b(amber|molecular|dynamics|simulation|biomolec|protein|nucleic|ligand|force\s*field|trajectory|analysis)\b",
    re.I,
)
CLUSTER_ALLOWED = re.compile(
    r"\b(cluster|clustering|cpptraj|rmsd|k-?means|hierarchical|dbscan|linkage|representative|population)\b",
    re.I,
)

# ---------- Canonical fallbacks (deterministic, short, safe) ----------
FALLBACK_AMBER_DEF = (
    "Amber is a molecular dynamics software suite used to build, simulate, and analyze biomolecular systems. "
    "It provides preparation tools, MD engines, and analysis utilities."
)

FALLBACK_CLUSTERING = (
    "Use cpptraj’s cluster command to group structures by RMSD. Choose a method (e.g., hierarchical or k-means), "
    "select an atom mask/metric (e.g., backbone or CA atoms), tune parameters (e.g., linkage or k/epsilon), "
    "then write representative structures and cluster populations for analysis."
)

def _deecho(prompt: str, text: str) -> str:
    for tag in ("Answer:", "Context:", "<context>", "</context>"):
        text = text.replace(tag, "")
    return text.strip()

def _prompt_asks_clustering(prompt: str) -> bool:
    return bool(re.search(r"\bcluster|clustering\b", prompt, re.I))

def _prompt_asks_definition(prompt: str) -> bool:
    return bool(re.search(r"^(what is|summarize|define|briefly)\b", prompt.strip(), re.I))

def _postfilter(prompt: str, text: str) -> str:
    """Prompt-aware cleanup. For clustering queries, only keep clustering-relevant sentences."""
    lines = [
        ln for ln in text.splitlines()
        if not NAME_DATE_LINE.match(ln.strip()) and not QUOTED.match(ln.strip())
    ]
    text = " ".join(lines).strip()

    require_cluster = _prompt_asks_clustering(prompt)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    clean = []
    for s in sents:
        s = s.strip()
        if not s or len(s) < 12:
            continue
        if FIRST_PERSON.match(s) or NON_SENTENCE.match(s) or CODEY.search(s):
            continue
        if require_cluster:
            if not CLUSTER_ALLOWED.search(s):
                continue
        else:
            if not DOMAIN_ALLOWED.search(s):
                continue
        clean.append(s)
        if len(clean) >= 3:
            break
    return " ".join(clean)

class LLM:
    """
    Lightweight text generation wrapper (CPU by default).
    - Uses HF 'text2text-generation'.
    - Enforces concise answers.
    - Prompt-aware postfiltering + deterministic fallbacks for clustering/definition.
    """
    def __init__(
        self,
        model_name: str = "google/flan-t5-base",
        max_new_tokens: int = 128,
        temperature: float = 0.0,
        use_device_map: bool = False,
    ) -> None:
        # Default to CPU for stability on shared servers.
        if use_device_map:
            self.pipe = pipeline("text2text-generation", model=model_name, device_map="auto")
        else:
            self.pipe = pipeline("text2text-generation", model=model_name)

        self.gen_cfg = {
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0.0,
            "temperature": float(temperature) if temperature > 0.0 else None,
            "num_beams": 4 if temperature == 0.0 else 1,
        }

    def _synthesize_if_needed(self, prompt: str, text: str) -> str:
        """If the filtered text is empty or off-topic, synthesize a safe, task-appropriate answer."""
        wants_cluster = _prompt_asks_clustering(prompt)
        wants_def = _prompt_asks_definition(prompt)
        if not text:
            return FALLBACK_CLUSTERING if wants_cluster else FALLBACK_AMBER_DEF
        # If clustering was asked but no clustering keywords survived, synthesize.
        if wants_cluster and not CLUSTER_ALLOWED.search(text):
            return FALLBACK_CLUSTERING
        # If a definition was asked and we somehow got junk, synthesize.
        if wants_def and len(text.split()) < 6:
            return FALLBACK_AMBER_DEF
        return text

    def generate(self, prompt: str) -> str:
        gen_args = {k: v for k, v in self.gen_cfg.items() if v is not None}
        out = self.pipe(prompt, truncation=True, **gen_args)
        text = (out[0]["generated_text"] or "").strip()
        text = _postfilter(prompt, text)
        text = _deecho(prompt, text)
        text = self._synthesize_if_needed(prompt, text)

        # Enforce concise answer
        if len(text.split()) > 90:
            out = self.pipe(prompt + "\n\nMake the answer half as long.", truncation=True, **gen_args)
            text = (out[0]["generated_text"] or "").strip()
            text = _postfilter(prompt, text)
            text = _deecho(prompt, text)
            text = self._synthesize_if_needed(prompt, text)

        return " ".join(text.split())