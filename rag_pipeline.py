import os
import re
import argparse
from typing import List, Dict, Any, Optional, Tuple

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForCausalLM, BatchEncoding
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

#PDF support
try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except Exception:
    PDF_AVAILABLE = False


# -----------------------
# (A) PORTABLE SETTINGS
# -----------------------
CHROMA_DIR = os.getenv("CHROMA_DIR", "/opt/chromadb/data/prompt_db")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_NAME = os.getenv("LLM_MODEL_NAME", "meta-llama/Meta-Llama-3.1-8B-Instruct")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "amber_messages")
PDF_PATH = os.getenv("PDF_PATH", "Amber25.pdf")

DEFAULT_TOP_K = 8
DEFAULT_MAX_NEW_TOKENS = 400
DEFAULT_DOC_CHAR_LIMIT = 1200
DEFAULT_TOTAL_CONTEXT_CHARS = 8500
DEFAULT_FETCH_K = 30

CHROMA_MIN_SCORE = float(os.getenv("CHROMA_MIN_SCORE", "0.20"))
PDF_MIN_SCORE = float(os.getenv("PDF_MIN_SCORE", "0.35"))


# -----------------------
# (B) INIT EMBEDDINGS + CHROMA
# -----------------------
embedding_model = HuggingFaceEmbeddings(model_name=EMBED_MODEL_NAME)

chroma_client = Chroma(
    persist_directory=CHROMA_DIR,
    embedding_function=embedding_model,
    collection_name=COLLECTION_NAME
)


_pdf_chunks: Optional[List[str]] = None
_pdf_vectors: Optional[np.ndarray] = None


# -----------------------
# (C) UTILITY HELPERS
# -----------------------
def strip_identity_fields(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove person metadata before building model context.
    """
    banned = {
        "author", "sender", "from", "from_name", "email",
        "owner", "name", "person", "user"
    }
    return {k: v for k, v in meta.items() if k not in banned}


def get_source_link(meta: Dict[str, Any]) -> str:
    """
    Returns a source URL if one exists in metadata.
    """
    for key in ["url", "link", "source_url", "thread_url", "message_url"]:
        if meta.get(key):
            return str(meta[key])
    return ""


def cosine_similarity_matrix(query_vec: np.ndarray, doc_matrix: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between one query vector and many doc vectors.
    """
    query_norm = np.linalg.norm(query_vec) + 1e-12
    doc_norms = np.linalg.norm(doc_matrix, axis=1) + 1e-12
    return (doc_matrix @ query_vec) / (doc_norms * query_norm)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> List[str]:
    """
    Split long text into overlapping chunks.
    """
    text = text.strip()
    if not text:
        return []

    chunks = []
    step = max(1, size - overlap)

    for i in range(0, len(text), step):
        chunk = text[i:i + size].strip()
        if chunk:
            chunks.append(chunk)

    return chunks

def clean_chunk_text(text: str) -> str:
    text = text or ""

    # remove common email header formatting
    text = re.sub(r"^[^\n]*<[^>\n]+>\s*\([^)]+\):\s*", "", text)
    text = re.sub(r"^(From|Subject|Date):.*$", "", text, flags=re.MULTILINE)

    # clean whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip()


def remove_repeated_paragraphs(text: str) -> str:
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    seen = set()
    out = []

    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)

    return "\n\n".join(out)

def fallback_answer_from_context(query: str, docs: List[Dict[str, Any]]) -> str:
    """
    Simple fallback answer if the model returns something useless.
    Builds a grounded summary from top retrieved docs.
    """
    snippets = []
    for d in docs[:3]:
        text = clean_chunk_text(d.get("text", ""))
        if text:
            snippets.append(text[:350])

    joined = " ".join(snippets).lower()

    causes = []
    steps = []

    if "double-precision" in joined or "double precision" in joined:
        steps.append("Try the full double-precision CUDA minimization code if available.")
    if "sander" in joined:
        steps.append("Try minimizing with sander first, since it is often more robust.")
    if "overflow" in joined or "large initial forces" in joined:
        causes.append("The error may be caused by very large initial forces or numerical overflow during minimization.")
    if "nan" in joined:
        causes.append("The retrieved discussions also suggest bad contacts or unstable starting coordinates may lead to NaN-related failures.")
    if "segmentation fault" in joined:
        causes.append("Some related reports show that minimization failures can also appear as low-level memory or segmentation errors.")

    if not causes:
        causes.append("The retrieved AMBER discussions suggest this is likely a numerical instability during GPU minimization.")

    if not steps:
        steps = [
            "Check the starting structure for bad contacts or steric clashes.",
            "Run a more conservative minimization first.",
            "Try CPU minimization before returning to pmemd.cuda."
        ]

    return (
        "Likely cause:\n"
        + " ".join(causes[:2])
        + "\n\nWhy:\n"
        + "The retrieved AMBER mailing-list results connect this type of CUDA minimization failure with unstable starting structures, very large forces, or GPU-side numerical problems during minimization."
        + "\n\nWhat to try:\n- "
        + "\n- ".join(steps[:3])
        + "\n\nIf still failing:\nProvide the Amber version, exact command, full error output, and minimization input settings."
    )

def expand_query(query: str) -> str:
    q = query.lower()

    extras = []
    if "pmemd.cuda" in q:
        extras += ["pmemd.cuda", "cuda", "gpu minimization"]
    if "illegal memory access" in q:
        extras += ["illegal memory access", "nan", "overflow", "segmentation fault"]
    if "minimization" in q:
        extras += ["minimization", "large initial forces", "sander", "double precision"]
    if "how do i" in q or "how to" in q:
        extras += ["tutorial", "manual", "example", "workflow"]

    return query + " " + " ".join(dict.fromkeys(extras))


def build_sources_section(docs: List[Dict[str, Any]]) -> str:
    """
    Build a readable Sources section for both emails and tutorials.
    """
    lines = []

    for i, d in enumerate(docs, start=1):
        meta = d.get("metadata", {}) or {}
        source_type = d.get("source_type") or detect_source_type(meta)
        link = get_source_link(meta)
        title = get_display_title(meta, source_type)
        details = get_source_details(meta, source_type)

        label = "Tutorial" if source_type == "tutorial" else "Email"

        if link and details:
            lines.append(f"- [S{i}] {label}: {title} ({details}): {link}")
        elif link:
            lines.append(f"- [S{i}] {label}: {title}: {link}")
        elif details:
            lines.append(f"- [S{i}] {label}: {title} ({details})")
        else:
            lines.append(f"- [S{i}] {label}: {title}")

    return "\n".join(lines)

def detect_source_type(meta: Dict[str, Any]) -> str:
    """
    More reliable source detection.
    Only classify as tutorial if metadata strongly indicates a real PDF/tutorial document.
    """
    meta = meta or {}

    lower_meta = {str(k).lower(): str(v).lower() for k, v in meta.items()}

    
    doc_keys = [
        "file_name", "pdf_name", "document_name", "page", "page_number",
        "source_type", "doc_type", "chunk_id"
    ]
    doc_values = " ".join(lower_meta.values())

    # Explicit source type metadata wins
    if lower_meta.get("source_type") in {"tutorial", "pdf", "manual", "document"}:
        return "tutorial"
    if lower_meta.get("doc_type") in {"tutorial", "pdf", "manual", "document"}:
        return "tutorial"

    # If it has document-style metadata like page/file/pdf, treat as tutorial
    has_doc_structure = any(k in lower_meta for k in doc_keys if k not in {"source_type", "doc_type"})
    has_pdf_signal = any(x in doc_values for x in [".pdf", "manual", "amber tutorial", "ambertools tutorial"])

    if has_doc_structure or has_pdf_signal:
        return "tutorial"

    # Strong signs of email/archive content
    if any(k in lower_meta for k in ["message_id", "thread_url", "subject", "date"]):
        return "email"

    if "archive.ambermd.org" in doc_values:
        return "email"

    return "unknown"

def get_source_details(meta: Dict[str, Any], source_type: str) -> str:
    meta = meta or {}

    if source_type == "tutorial":
        details = []

        file_name = meta.get("file_name") or meta.get("pdf_name") or meta.get("document_name")
        page = meta.get("page") or meta.get("page_number")

        if file_name:
            details.append(str(file_name))
        if page is not None and str(page).strip():
            details.append(f"page {page}")

        return ", ".join(details)

    date = meta.get("date") or meta.get("date_iso")
    return str(date) if date else ""

def tutorial_bias_score(query: str, meta: Dict[str, Any], text: str) -> int:
    """
    Give tutorial chunks a boost for how-to / usage questions,
    and email chunks a boost for error/troubleshooting questions.
    """
    q = query.lower()
    text = (text or "").lower()
    source_type = detect_source_type(meta)

    howto_terms = ["how to", "tutorial", "example", "usage", "run", "setup", "build", "create"]
    trouble_terms = ["error", "crash", "nan", "illegal memory access", "segmentation fault", "fail", "failing"]

    score = 0

    if source_type == "tutorial" and any(t in q for t in howto_terms):
        score += 10

    if source_type == "email" and any(t in q for t in trouble_terms):
        score += 8

    if "tutorial" in text or "example" in text:
        score += 1

    return score

def get_display_title(meta: Dict[str, Any], source_type: str) -> str:
    meta = meta or {}

    if source_type == "tutorial":
        return (
            meta.get("title")
            or meta.get("document_name")
            or meta.get("file_name")
            or meta.get("pdf_name")
            or "Tutorial/Manual Chunk"
        )

    return meta.get("subject") or "Email Thread"

# -----------------------
# (D) OPTIONAL PDF RETRIEVAL
# -----------------------
def build_pdf_index_if_needed() -> None:
    """
    Loads PDF text, chunks it, and embeds it once.
    """
    global _pdf_chunks, _pdf_vectors

    if _pdf_chunks is not None and _pdf_vectors is not None:
        return

    if not PDF_AVAILABLE:
        _pdf_chunks, _pdf_vectors = [], np.array([])
        return

    if not os.path.exists(PDF_PATH):
        _pdf_chunks, _pdf_vectors = [], np.array([])
        return

    reader = PdfReader(PDF_PATH)
    full_text = []

    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            full_text.append(page_text)

    joined = "\n".join(full_text).strip()
    if not joined:
        _pdf_chunks, _pdf_vectors = [], np.array([])
        return

    _pdf_chunks = chunk_text(joined, size=900, overlap=150)

    vectors = embedding_model.embed_documents(_pdf_chunks)
    _pdf_vectors = np.array(vectors, dtype=np.float32)


def retrieve_pdf_chunks(query: str, top_k: int = 4, min_score: float = PDF_MIN_SCORE) -> List[Dict[str, Any]]:
    """
    Retrieve similar chunks from the optional AMBER PDF/manual.
    """
    build_pdf_index_if_needed()

    if not _pdf_chunks or _pdf_vectors is None or len(_pdf_vectors) == 0:
        return []

    query_vec = np.array(embedding_model.embed_query(query), dtype=np.float32)
    sims = cosine_similarity_matrix(query_vec, _pdf_vectors)

    ranked_idx = np.argsort(-sims)[:top_k]
    out = []

    for idx in ranked_idx:
        score = float(sims[idx])
        if score < min_score:
            continue
        out.append({
            "text": _pdf_chunks[idx],
            "metadata": {
                "subject": "AMBER Manual",
                "date": "",
                "id": f"pdf-{idx}",
                "source_type": "pdf"
            },
            "score": score,
            "source_type": "pdf"
        })

    return out


# -----------------------
# (E) CHROMA RETRIEVAL
# -----------------------
def retrieve_context_items(
    query: str,
    chroma_client: Chroma,
    top_k: int = DEFAULT_TOP_K,
    use_mmr: bool = True
):
    """
    Returns LangChain Document objects.
    """
    if use_mmr:
        return chroma_client.max_marginal_relevance_search(
            query,
            k=top_k,
            fetch_k=max(DEFAULT_FETCH_K, top_k * 3)
        )
    return chroma_client.similarity_search(query, k=top_k)


def retrieve_context_items_with_scores(
    query: str,
    chroma_client: Chroma,
    top_k: int = DEFAULT_TOP_K,
    use_mmr: bool = True
) -> List[Tuple[Any, float]]:
    """
    Best-effort retrieval with scores.
    """
    try:
        return chroma_client.similarity_search_with_relevance_scores(query, k=top_k)
    except Exception:
        docs = retrieve_context_items(query, chroma_client, top_k=top_k, use_mmr=use_mmr)
        return [(d, 0.0) for d in docs]


def dedup_docs(docs) -> List:
    """
    Deduplicate by id/message_id if present; otherwise use text prefix.
    """
    seen = set()
    out = []

    for d in docs:
        if isinstance(d, dict):
            meta = d.get("metadata", {}) or {}
            text = d.get("text", "")
        else:
            meta = d.metadata or {}
            text = d.page_content

        key = meta.get("message_id") or meta.get("id") or text[:160]

        if key in seen:
            continue

        seen.add(key)
        out.append(d)

    return out


def retrieve_hybrid_context(
    query: str,
    chroma_client: Chroma,
    top_k: int = DEFAULT_TOP_K,
    use_mmr: bool = True,
    include_pdf: bool = True,
    pdf_top_k: int = 4
) -> List[Dict[str, Any]]:
    """
    Hybrid retriever:
    - Chroma results from prompt_db (emails + tutorial chunks if both are indexed there)
    - optional live PDF retrieval if enabled separately
    """
    chroma_pairs = retrieve_context_items_with_scores(
        query,
        chroma_client,
        top_k=top_k,
        use_mmr=use_mmr
    )

    merged = []

    for d, score in chroma_pairs:
        meta = d.metadata or {}
        source_type = detect_source_type(meta)

        merged.append({
            "text": d.page_content,
            "metadata": meta,
            "score": float(score),
            "source_type": source_type
        })

    if include_pdf:
        merged.extend(retrieve_pdf_chunks(query, top_k=pdf_top_k, min_score=PDF_MIN_SCORE))

    merged = dedup_docs(merged)
    merged = sorted(merged, key=lambda x: x.get("score", 0.0), reverse=True)

    return merged

def debug_retrieval(
    query: str,
    chroma_client: Chroma,
    top_k: int = DEFAULT_TOP_K,
    use_mmr: bool = True,
    include_pdf: bool = True
):
    """
    Prints retrieved docs with useful debug previews.
    """
    docs = retrieve_hybrid_context(
        query,
        chroma_client,
        top_k=top_k,
        use_mmr=use_mmr,
        include_pdf=include_pdf
    )

    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print(f"CHROMA_DIR: {CHROMA_DIR}")
    print(f"COLLECTION_NAME: {COLLECTION_NAME}")
    print(f"PDF_PATH: {PDF_PATH}")
    print(f"Retrieved {len(docs)} combined docs\n")

    for i, d in enumerate(docs, start=1):
        meta = d.get("metadata", {}) or {}
        preview = normalize_whitespace(d.get("text", ""))[:350]

        print(f"--- S{i} ---")
        print("type   :", d.get("source_type", "unknown"))
        print("score  :", round(d.get("score", 0.0), 4))
        print("title  :", get_display_title(meta, d.get("source_type", "unknown")))
        print("details:", get_source_details(meta, d.get("source_type", "unknown")) or "")
        print("id     :", meta.get("id") or meta.get("message_id") or "unknown")
        print("link   :", get_source_link(meta) or "(no link)")
        print("metadata:", meta)
        print("preview:", preview)
        print()

    return docs


# -----------------------
# (F) CONTEXT FILTERING + PROMPT
# -----------------------
def choose_supporting_docs(
    query: str,
    docs: List[Dict[str, Any]],
    max_docs: int = 5,
    min_chroma_score: float = CHROMA_MIN_SCORE
) -> List[Dict[str, Any]]:
    """
    Keep the strongest docs, but allow tutorial chunks to rank higher for how-to questions.
    """
    selected = []
    important_terms = [
        "minimization", "pmemd.cuda", "illegal memory access", "nan",
        "sander", "double precision", "tleap", "cpptraj", "tutorial"
    ]

    for d in docs:
        score = float(d.get("score", 0.0))
        meta = d.get("metadata", {}) or {}
        text = d.get("text", "") or ""
        source_type = d.get("source_type", "unknown")

        if source_type in ("email", "tutorial", "unknown"):
            if score != 0.0 and score < min_chroma_score:
                continue

        keyword_hits = sum(1 for t in important_terms if t.lower() in text.lower())
        bias = tutorial_bias_score(query, meta, text)

        d["keyword_hits"] = keyword_hits
        d["bias"] = bias
        selected.append(d)

    selected = sorted(
        selected,
        key=lambda x: (x.get("bias", 0), x.get("keyword_hits", 0), x.get("score", 0.0)),
        reverse=True
    )

    return selected[:max_docs]


def format_context(docs, max_chars_per_doc=DEFAULT_DOC_CHAR_LIMIT, max_total_chars=DEFAULT_TOTAL_CONTEXT_CHARS):
    """
    Convert retrieved evidence into a clean context block.
    """
    blocks = []
    total = 0

    for i, d in enumerate(docs, start=1):
        raw_meta = d.get("metadata", {}) or {}
        meta = strip_identity_fields(raw_meta)
        label = f"S{i}"

        header_bits = [
            meta.get("date") or meta.get("date_iso"),
            meta.get("subject"),
            f"id={meta.get('id') or raw_meta.get('message_id') or 'unknown'}",
            f"type={d.get('source_type', 'unknown')}"
        ]
        header = " | ".join([str(x) for x in header_bits if x])

        text = clean_chunk_text((d.get("text") or "").strip())
        if len(text) > max_chars_per_doc:
            text = text[:max_chars_per_doc].rsplit(" ", 1)[0] + "…"

        block = f"[{label}] ({header})\n{text}\n"

        if total + len(block) > max_total_chars:
            break

        blocks.append(block)
        total += len(block)

    return "\n".join(blocks).strip()


def looks_relevant(query: str, context_block: str) -> bool:

    if not context_block or not context_block.strip():
        return False

    query_words = [w.lower() for w in re.findall(r"\b\w+\b", query) if len(w) > 4]
    if not query_words:
        return True

    amber_terms = {
        "amber", "ambertools", "pmemd", "sander", "cpptraj",
        "tleap", "cuda", "minimization", "mdin", "gaff", "parm", "prmtop"
    }

    c = context_block.lower()
    hits = sum(1 for w in set(query_words) if w in c)
    amber_hits = sum(1 for w in amber_terms if w in query.lower() and w in c)

    return hits >= 2 or amber_hits >= 1

def build_prompt(query: str, context_block: str) -> str:
    return f"""You are Amber Support Assistant.

Use only the retrieved context below.

The retrieved context may include:
- AMBER mailing-list troubleshooting threads
- tutorial or manual chunks from PDF documents

Rules:
- Do not use outside knowledge.
- Do not repeat the user's question.
- Do not copy long passages from the context.
- Prefer tutorial/manual evidence for "how to" or workflow questions.
- Prefer mailing-list evidence for troubleshooting or error questions.
- Summarize the likely cause and what to try next.
- Do not suggest nvidia-smi, gdb, driver updates, hardware checks, or generic GPU debugging unless those are explicitly mentioned in the retrieved context.
- Do not mention author names, sender names, or email formatting.
- If the context is incomplete, say what is missing.
- Do not claim hardware failure, GPU failure, corrupted executables, driver problems, or OS issues unless those are explicitly stated in the retrieved context.
- Do not present a specific user example or file names from the retrieved context as a general workflow unless the context clearly states it is a general procedure.
- Do not present example file names, frcmod files, library files, or PDB names from a retrieved email as general required steps unless the context clearly says they are general.

Write exactly in this format:

Likely cause:
<1-3 sentences>

Why:
<1-3 sentences based only on the retrieved context>

What to try:
- <step 1>
- <step 2>
- <step 3>

If still failing:
<what details are still needed>

Retrieved context:
{context_block if context_block else "[No retrieved context]"}

User question:
{query}
"""

# -----------------------
# (G) LLM INIT + GENERATION
# -----------------------
def load_model(device: str = None):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=True)

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map="auto" if device == "cuda" else None
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if device != "cuda":
        model = model.to(device)

    return tokenizer, model


def generate_answer(prompt, tokenizer, model, max_new_tokens=DEFAULT_MAX_NEW_TOKENS):

    if hasattr(tokenizer, "apply_chat_template"):
        messages = [
            {"role": "system", "content": "You are Amber Support Assistant."},
            {"role": "user", "content": prompt},
        ]
        enc = tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt"
        )
    else:
        enc = tokenizer(prompt, return_tensors="pt", truncation=True)

    if torch.is_tensor(enc):
        input_ids = enc.to(model.device)
        attention_mask = None
    elif isinstance(enc, (dict, BatchEncoding)):
        input_ids = enc["input_ids"].to(model.device)
        attention_mask = enc.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(model.device)
    else:
        raise TypeError(f"Unexpected tokenizer output type: {type(enc)}")

    gen_kwargs = dict(
        max_new_tokens=max_new_tokens,
        do_sample=False,
        num_beams=1,
        temperature=None,
        pad_token_id=tokenizer.eos_token_id,
    )

    if attention_mask is not None:
        gen_kwargs["attention_mask"] = attention_mask

    with torch.no_grad():
        output_ids = model.generate(input_ids=input_ids, **gen_kwargs)

    gen_ids = output_ids[0][input_ids.shape[-1]:]
    answer = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()

    answer = re.sub(r"\n{3,}", "\n\n", answer).strip()
    answer = remove_repeated_paragraphs(answer)
    return answer


# -----------------------
# (H) FULL RAG PIPELINE
# -----------------------
def rag_pipeline(
    user_query,
    top_k=DEFAULT_TOP_K,
    use_mmr=True,
    max_new_tokens=DEFAULT_MAX_NEW_TOKENS,
    device=None,
    include_pdf=True
):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    expanded_query = expand_query(user_query)

    docs = retrieve_hybrid_context(
        expanded_query,
        chroma_client,
        top_k=top_k,
        use_mmr=use_mmr,
        include_pdf=include_pdf
    )

    if not docs:
        return (
            "I couldn't retrieve relevant Amber support context for that question.\n"
            "Please provide the Amber version, exact command, full error output, and relevant input snippet."
        )

    docs = choose_supporting_docs(user_query, docs, max_docs=top_k)
    context_block = format_context(docs)

    if not looks_relevant(user_query, context_block):
        return (
            "I retrieved some context, but it does not look strongly related to your question.\n"
            "Please provide the Amber version, exact command, full error output, and the relevant input snippet."
        )

    tokenizer, model = load_model(device)
    prompt = build_prompt(user_query, context_block)
    answer = generate_answer(prompt, tokenizer, model, max_new_tokens=max_new_tokens)

    unsupported_phrases = [
        "nvidia-smi",
        "gdb",
        "GPU driver",
        "system architecture",
        "memory allocation failure",
        "compatibility issues",
        "failing GPU",
        "different computer",
        "corrupted file",
        "corrupted executable",
        "operating system",
        "overheating",
        "low memory",
        "CUDA library"
    ]

    bad_answer = (
        not answer.strip()
        or answer.strip().lower() == user_query.strip().lower()
        or len(answer.split()) < 8
        or any(p.lower() in answer.lower() for p in unsupported_phrases)
    )

    if bad_answer:
        answer = fallback_answer_from_context(user_query, docs)

    sources_section = build_sources_section(docs)
    return answer + "\n\nSources:\n" + sources_section


# -----------------------
# (I) TEST SET RUNNER
# -----------------------
def run_test_set(test_file: str, top_k: int, use_mmr: bool, device: str, max_new_tokens: int, include_pdf: bool):
    with open(test_file, "r", encoding="utf-8") as f:
        queries = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    for q in queries:
        debug_retrieval(q, chroma_client, top_k=top_k, use_mmr=use_mmr, include_pdf=include_pdf)

        ans = rag_pipeline(
            q,
            top_k=top_k,
            use_mmr=use_mmr,
            device=device,
            max_new_tokens=max_new_tokens,
            include_pdf=include_pdf
        )
        print("ANSWER:\n", ans)
        print("\n" + "-" * 80)


# -----------------------
# (J) CLI ENTRYPOINT
# -----------------------
def main():
    parser = argparse.ArgumentParser(description="Amber RAG Pipeline Tester")

    parser.add_argument(
        "--mode",
        choices=["retrieve", "rag", "test"],
        default="rag",
        help="retrieve = retrieval-only, rag = full pipeline, test = run queries from a file"
    )
    parser.add_argument(
        "--query",
        type=str,
        default="pmemd.cuda illegal memory access during minimization",
        help="Single query to test (used in retrieve/rag modes)"
    )
    parser.add_argument("--top_k", type=int, default=DEFAULT_TOP_K, help="Number of docs to retrieve")
    parser.add_argument("--mmr", action="store_true", help="Use MMR retrieval")
    parser.add_argument("--test_file", type=str, default="test_queries.txt", help="File with one query per line")
    parser.add_argument("--device", type=str, choices=["cpu", "cuda"], default=None, help="Force device; default auto-detect")
    parser.add_argument("--max_new_tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS, help="Max tokens for generation")
    parser.add_argument("--no_pdf", action="store_true", help="Disable optional PDF/manual retrieval")

    args = parser.parse_args()

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    include_pdf = not args.no_pdf

    if args.mode == "retrieve":
        debug_retrieval(
            args.query,
            chroma_client,
            top_k=args.top_k,
            use_mmr=args.mmr,
            include_pdf=include_pdf
        )

    elif args.mode == "rag":
        debug_retrieval(
            args.query,
            chroma_client,
            top_k=args.top_k,
            use_mmr=args.mmr,
            include_pdf=include_pdf
        )

        ans = rag_pipeline(
            args.query,
            top_k=args.top_k,
            use_mmr=args.mmr,
            device=device,
            max_new_tokens=args.max_new_tokens,
            include_pdf=include_pdf
        )
        print("\nANSWER:\n", ans)

    elif args.mode == "test":
        run_test_set(
            args.test_file,
            top_k=args.top_k,
            use_mmr=args.mmr,
            device=device,
            max_new_tokens=args.max_new_tokens,
            include_pdf=include_pdf
        )


if __name__ == "__main__":
    main()









