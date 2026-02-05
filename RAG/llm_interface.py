# RAG/llm_interface.py
import re
from transformers import pipeline

# ---------- Output cleanup heuristics ----------
NAME_DATE_LINE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s*\([^)]+\):")
CODEY = re.compile(
    r"[/\\][\w\-.]+|[\w\-.]+\.(c|cpp|h|hpp|py|f90|f|sh|md|txt)|`|::|#include|int\s+main|class\s+\w+"
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

FALLBACK_AMBER_DEF = (
    "Amber is a molecular dynamics software suite used to build, simulate, and analyze biomolecular systems. "
    "It provides preparation tools, MD engines, and analysis utilities."
)

FALLBACK_CLUSTERING = (
    "Use cpptraj’s cluster command to group structures by RMSD. Choose a method (e.g., hierarchical or k-means), "
    "select an atom mask/metric (e.g., backbone or CA atoms), tune parameters (e.g., linkage or k/epsilon), "
    "then write representative structures and cluster populations for analysis."
)

NO_PRIOR_ANSWER = (
    "No sufficiently relevant prior answer was found in the knowledge base for that query. "
    "Please submit a support ticket so the team can provide an authoritative answer."
)

# ---------- Prompt parsing (baseline prompt aware) ----------
_Q_FROM_BASELINE = re.compile(
    r"A user has asked the following question:\s*(.*?)\s*(?:Relevant technical context|Using the information provided:)",
    re.S | re.I,
)

def _extract_question(prompt: str) -> str:
    m = _Q_FROM_BASELINE.search(prompt)
    if m:
        return m.group(1).strip()
    # fallback: try a "Question:" pattern if you ever swap templates
    m2 = re.search(r"(?mi)^Question:\s*(.+)$", prompt)
    return (m2.group(1).strip() if m2 else prompt.strip())

def _asks_clustering(question: str) -> bool:
    return bool(re.search(r"\bcluster|clustering\b", question, re.I))

def _asks_definition(question: str) -> bool:
    return bool(re.search(r"^(what is|summarize|define|briefly)\b", question.strip(), re.I))

def _postfilter(question: str, text: str) -> str:
    """Question-aware cleanup. If clustering question, keep clustering-related sentences."""
    lines = [
        ln for ln in text.splitlines()
        if not NAME_DATE_LINE.match(ln.strip()) and not QUOTED.match(ln.strip())
    ]
    text = " ".join(lines).strip()

    require_cluster = _asks_clustering(question)
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

    return " ".join(clean).strip()

def _is_llama_like(model_name: str) -> bool:
    m = model_name.lower()
    return any(k in m for k in ["llama", "mistral", "qwen", "gemma", "phi", "falcon"])

class LLM:
    """
    Supports:
    - Seq2Seq (FLAN-T5): pipeline('text2text-generation')
    - Causal (LLaMA): pipeline('text-generation') with return_full_text=False
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

        pipe_kwargs = {"model": model_name}
        if use_device_map:
            pipe_kwargs["device_map"] = "auto"

        # For causal models, returning only the continuation reduces prompt-echo issues a lot.
        if self.is_causal:
            pipe_kwargs["return_full_text"] = False

        self.pipe = pipeline(task, **pipe_kwargs)

        self.gen_cfg = {
            "max_new_tokens": max_new_tokens,
            "do_sample": temperature > 0.0,
            "temperature": float(temperature) if temperature > 0.0 else None,
            # beams only makes sense for seq2seq here
            "num_beams": 4 if (not self.is_causal and temperature == 0.0) else None,
        }

    def _fallback(self, question: str, filtered: str, had_context: bool) -> str:
        wants_cluster = _asks_clustering(question)
        wants_def = _asks_definition(question)

        if filtered:
            # If clustering question but clustering keywords didn’t survive, use clustering fallback.
            if wants_cluster and not CLUSTER_ALLOWED.search(filtered):
                return FALLBACK_CLUSTERING
            return filtered

        # If we have no usable text:
        if wants_cluster:
            return FALLBACK_CLUSTERING
        if wants_def:
            return FALLBACK_AMBER_DEF

        # For general troubleshooting Qs: if retrieval happened but nothing solid emerged, prefer "no prior answer"
        return NO_PRIOR_ANSWER if had_context else FALLBACK_AMBER_DEF

    def generate(self, prompt: str) -> str:
        question = _extract_question(prompt)
        gen_args = {k: v for k, v in self.gen_cfg.items() if v is not None}

        out = self.pipe(prompt, **gen_args)
        raw = (out[0].get("generated_text") or "").strip()

        filtered = _postfilter(question, raw)
        had_context = "<context>" in prompt or "Relevant technical context" in prompt
        text = self._fallback(question, filtered, had_context)

        # enforce concise
        if len(text.split()) > 90:
            out2 = self.pipe(prompt + "\n\nMake the answer half as long.", **gen_args)
            raw2 = (out2[0].get("generated_text") or "").strip()
            filtered2 = _postfilter(question, raw2)
            text = self._fallback(question, filtered2, had_context)

        return " ".join(text.split())