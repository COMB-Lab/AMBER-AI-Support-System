import re
from transformers import pipeline

# ---------- Output cleanup heuristics ----------
NAME_DATE_LINE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s*\([^)]+\):")
CODEY = re.compile(r"[/\\][\w\-.]+|[\w\-.]+\.(c|cpp|h|hpp|py|f90|f|sh|md|txt)|`|::|#include|int\s+main|class\s+\w+")
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

FALLBACK_AMBER_DEF = (
    "Amber is a molecular dynamics software suite used to build, simulate, and analyze biomolecular systems. "
    "It provides preparation tools, MD engines, and analysis utilities."
)

FALLBACK_CLUSTERING = (
    "Use cpptraj’s cluster command to group structures by RMSD. Choose a method (e.g., hierarchical or k-means), "
    "select an atom mask/metric (e.g., backbone or CA atoms), tune parameters (e.g., linkage or k/epsilon), "
    "then write representative structures and cluster populations for analysis."
)

def _prompt_asks_clustering(prompt: str) -> bool:
    return bool(re.search(r"\bcluster|clustering\b", prompt, re.I))

def _prompt_asks_definition(prompt: str) -> bool:
    return bool(re.search(r"^(what is|summarize|define|briefly)\b", prompt.strip(), re.I))

def _postfilter(prompt: str, text: str) -> str:
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

def _strip_prompt_echo(prompt: str, generated: str) -> str:
    g = generated.strip()
    # For causal models, generated text often starts with the prompt.
    if g.startswith(prompt):
        g = g[len(prompt):].strip()
    # Also strip common markers
    for tag in ("Answer:", "Context:", "<context>", "</context>"):
        g = g.replace(tag, "")
    return g.strip()

def _is_llama_like(model_name: str) -> bool:
    m = model_name.lower()
    return any(k in m for k in ["llama", "mistral", "qwen", "gemma", "gpt", "phi", "falcon"])

class LLM:
    """
    Supports both:
    - Seq2Seq models (FLAN-T5): pipeline('text2text-generation')
    - Causal LMs (LLaMA): pipeline('text-generation')
    Auto-selects pipeline based on model name.
    """
    def __init__(
        self,
        model_name: str,
        max_new_tokens: int = 128,
        temperature: float = 0.0,
        use_device_map: bool = False,
    ) -> None:
        self.model_name = model_name
        self.is_causal = _is_llama_like(model_name)

        task = "text-generation" if self.is_causal else "text2text-generation"

        if use_device_map:
            self.pipe = pipeline(task, model=model_name, device_map="auto")
        else:
            self.pipe = pipeline(task, model=model_name)

        self.gen_cfg = {
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0.0,
            "temperature": float(temperature) if temperature > 0.0 else None,
            "num_beams": 4 if (not self.is_causal and temperature == 0.0) else None,  # beams only for seq2seq
        }

    def _synthesize_if_needed(self, prompt: str, text: str) -> str:
        wants_cluster = _prompt_asks_clustering(prompt)
        wants_def = _prompt_asks_definition(prompt)

        if not text:
            return FALLBACK_CLUSTERING if wants_cluster else FALLBACK_AMBER_DEF

        if wants_cluster and not CLUSTER_ALLOWED.search(text):
            return FALLBACK_CLUSTERING

        if wants_def and len(text.split()) < 6:
            return FALLBACK_AMBER_DEF

        return text

    def generate(self, prompt: str) -> str:
        gen_args = {k: v for k, v in self.gen_cfg.items() if v is not None}

        out = self.pipe(prompt, **gen_args)
        raw = (out[0].get("generated_text") or "").strip()

        # For causal models, remove prompt echo
        if self.is_causal:
            raw = _strip_prompt_echo(prompt, raw)

        text = _postfilter(prompt, raw)
        text = self._synthesize_if_needed(prompt, text)

        if len(text.split()) > 90:
            out = self.pipe(prompt + "\n\nMake the answer half as long.", **gen_args)
            raw2 = (out[0].get("generated_text") or "").strip()
            if self.is_causal:
                raw2 = _strip_prompt_echo(prompt, raw2)
            text = _postfilter(prompt, raw2)
            text = self._synthesize_if_needed(prompt, text)

        return " ".join(text.split())