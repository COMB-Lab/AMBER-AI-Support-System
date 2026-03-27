import os
import re
import argparse
from typing import List, Dict, Any, Optional, Tuple

import faiss
import torch
import numpy as np
from transformers import AutoTokenizer, AutoModelForCausalLM, BatchEncoding
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

#PDF support
PDF_IMPORT_ERROR = ""
try:
    from pypdf import PdfReader
    PDF_AVAILABLE = True
except Exception as exc:
    PDF_AVAILABLE = False
    PDF_IMPORT_ERROR = str(exc)


# -----------------------
# (A) PORTABLE SETTINGS
# -----------------------
CHROMA_DIR = os.getenv("CHROMA_DIR", "/opt/chromadb/data/prompt_db")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_NAME = os.getenv("LLM_MODEL_NAME", "meta-llama/Meta-Llama-3.1-8B-Instruct")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "amber_messages")
PDF_PATH = os.getenv("PDF_PATH", "/home/azeped70/amber_rag/data/Amber25.pdf")
PDF_PUBLIC_URL = os.getenv("PDF_PUBLIC_URL", "https://ambermd.org/doc12/Amber25.pdf")
PDF_TOP_K = 5
PDF_MIN_SCORE = 0.45
PDF_CHUNK_SIZE = 700
PDF_CHUNK_OVERLAP = 100

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
    meta = meta or {}
    if meta.get("source_type") == "pdf" or meta.get("pdf_path") or meta.get("file_name", "").lower().endswith(".pdf"):
        page = meta.get("page")
        if PDF_PUBLIC_URL:
            if page is not None:
                return f"{PDF_PUBLIC_URL}#page={page}"
            return PDF_PUBLIC_URL

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


def extract_query_terms(query: str) -> List[str]:
    stopwords = {
        "the", "and", "for", "with", "from", "that", "this", "does", "into",
        "during", "about", "what", "when", "where", "which", "your", "have",
        "using", "used", "use", "how", "why", "can", "not", "are", "was",
        "were", "will", "would", "should", "into", "build", "system"
    }
    terms = []
    for token in re.findall(r"\b[a-zA-Z][\w\.\-]+\b", query.lower()):
        if len(token) < 3 or token in stopwords:
            continue
        terms.append(token)
    return list(dict.fromkeys(terms))


def keyword_overlap_score(query: str, text: str) -> float:
    query_terms = extract_query_terms(query)
    if not query_terms:
        return 0.0

    text_lower = (text or "").lower()
    hits = sum(1 for term in query_terms if term in text_lower)
    phrase_bonus = 0.0
    query_lower = query.lower()
    if "tleap" in query_lower and "tleap" in text_lower:
        phrase_bonus += 1.0
    if "solvate" in query_lower and ("solvatebox" in text_lower or "solvateoct" in text_lower):
        phrase_bonus += 1.5
    if "pmemd.cuda" in query_lower and "pmemd.cuda" in text_lower:
        phrase_bonus += 1.0
    return hits + phrase_bonus


def make_preview_snippet(text: str, query: str, max_chars: int = 350) -> str:
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= max_chars:
        return cleaned

    query_terms = extract_query_terms(query)
    lower_cleaned = cleaned.lower()

    best_pos = -1
    for term in query_terms:
        pos = lower_cleaned.find(term)
        if pos != -1:
            best_pos = pos
            break

    if best_pos == -1:
        return cleaned[:max_chars].rstrip() + "..."

    start = max(0, best_pos - max_chars // 3)
    end = min(len(cleaned), start + max_chars)
    snippet = cleaned[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(cleaned):
        snippet = snippet.rstrip() + "..."
    return snippet


def get_candidate_pdf_paths(configured_path: str) -> List[str]:
    base_name = os.path.basename(configured_path) or "Amber25.pdf"
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()

    candidates = [
        configured_path,
        os.path.join(script_dir, base_name),
        os.path.join(script_dir, "data", base_name),
        os.path.join(os.getcwd(), base_name),
        os.path.join(os.getcwd(), "data", base_name),
        os.path.join(os.path.dirname(configured_path), base_name),
        os.path.join(os.path.dirname(os.path.dirname(configured_path)), base_name),
    ]

    seen = set()
    deduped = []
    for path in candidates:
        if path and path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def resolve_pdf_path(configured_path: str = PDF_PATH) -> str:
    for candidate in get_candidate_pdf_paths(configured_path):
        if os.path.exists(candidate):
            return candidate
    return configured_path


def find_pdf_candidates(
    filename: Optional[str] = None,
    search_roots: Optional[List[str]] = None,
    max_results: int = 20
) -> List[str]:
    filename = filename or (os.path.basename(PDF_PATH) or "Amber25.pdf")
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()

    if search_roots is None:
        search_roots = [
            os.getcwd(),
            script_dir,
            os.path.dirname(PDF_PATH),
            os.path.dirname(os.path.dirname(PDF_PATH)),
            "/home",
            "/opt",
            "/srv",
            "/data",
        ]

    matches = []
    seen = set()
    for root in search_roots:
        if not root or root in seen or not os.path.exists(root):
            continue
        seen.add(root)

        if os.path.isfile(root):
            if os.path.basename(root).lower() == filename.lower():
                matches.append(root)
            continue

        for current_root, _, files in os.walk(root):
            for name in files:
                if name.lower() == filename.lower():
                    matches.append(os.path.join(current_root, name))
                    if len(matches) >= max_results:
                        return matches

    return matches


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


def howto_answer_from_context(query: str, docs: List[Dict[str, Any]]) -> str:
    snippets = [clean_chunk_text(d.get("text", "")) for d in docs[:6] if clean_chunk_text(d.get("text", ""))]
    joined = " ".join(snippets).lower()

    steps = []
    if "source leaprc" in joined or "leaprc" in joined:
        steps.append("Load the relevant LEaP parameter files first, such as the appropriate protein, nucleic-acid, water, or GAFF leaprc files for your system.")
    if "loadpdb" in joined:
        steps.append("Load your solute structure into tleap with `loadpdb`, after loading any needed residue libraries or frcmod files.")
    if "solvatebox" in joined or "tip3pbox" in joined:
        steps.append("Solvate the loaded unit with `solvateBox`, using a solvent box such as `TIP3PBOX` and a buffer distance.")
    if "addions" in joined or "addion" in joined:
        steps.append("Add counterions after solvation if you need to neutralize the system or set ionic conditions.")
    if "saveamberparm" in joined:
        steps.append("Write out the final topology and coordinates with `saveAmberParm` once the system is built.")
    if "savepdb" in joined:
        steps.append("Optionally save a PDB with `savePdb` to inspect the solvated structure.")

    deduped_steps = []
    seen = set()
    for step in steps:
        key = step.lower()
        if key not in seen:
            seen.add(key)
            deduped_steps.append(step)

    if not deduped_steps:
        deduped_steps = [
            "Load the needed LEaP parameter files and any custom residue libraries.",
            "Load the solute structure into tleap, then solvate it with an appropriate solvent box and buffer.",
            "Save the resulting AMBER topology and coordinate files."
        ]

    why_parts = []
    if any(d.get("source_type") == "pdf" for d in docs):
        why_parts.append("The Amber25 manual chunks show tleap commands and examples for loading units, solvating with `solvateBox`, and saving output files.")
    if any(d.get("source_type") == "email" for d in docs):
        why_parts.append("The email results add practical examples and common mistakes, such as needing a solvent unit like `TIP3PBOX` rather than passing a plain string incorrectly.")
    if not why_parts:
        why_parts.append("The retrieved context points to the standard tleap workflow of loading parameters, building the unit, solvating it, and saving the outputs.")

    return (
        "Likely answer:\n"
        "Use tleap by first loading the relevant force-field and solvent parameters, then loading your solute, solvating it with a water box such as `TIP3PBOX`, optionally adding ions, and finally saving the AMBER topology and coordinate files."
        "\n\nWhy:\n"
        + " ".join(why_parts[:2])
        + "\n\nWhat to try:\n- "
        + "\n- ".join(deduped_steps[:5])
        + "\n\nIf still missing information:\n"
        + "You may still need the exact leaprc files, any custom residue libraries or frcmod files, and the solvent model/buffer size appropriate for your system."
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
    lines = []

    for i, d in enumerate(docs, start=1):
        meta = d.get("metadata", {}) or {}
        source_type = d.get("source_type", "unknown")
        title = get_display_title(meta, source_type)
        details = get_source_details(meta, source_type)
        link = get_source_link(meta)

        if source_type == "pdf":
            label = "PDF"
        elif source_type == "tutorial":
            label = "Tutorial"
        else:
            label = "Email"

        if source_type == "pdf" and not link and meta.get("pdf_path"):
            page = meta.get("page")
            link = f"{meta['pdf_path']}#page={page}" if page is not None else str(meta["pdf_path"])

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

    # Strong signs of a real document/tutorial chunk
    doc_keys = [
        "file_name", "pdf_name", "document_name", "page", "page_number",
        "source_type", "doc_type", "chunk_id"
    ]
    doc_values = " ".join(lower_meta.values())

    # Explicit source type metadata wins
    if lower_meta.get("source_type") == "pdf":
        return "pdf"
    if lower_meta.get("source_type") in {"tutorial", "manual", "document"}:
        return "tutorial"
    if lower_meta.get("doc_type") in {"tutorial", "pdf", "manual", "document"}:
        return "pdf" if lower_meta.get("doc_type") == "pdf" else "tutorial"

    # If it has document-style metadata like page/file/pdf, treat as tutorial
    has_doc_structure = any(k in lower_meta for k in doc_keys if k not in {"source_type", "doc_type"})
    has_pdf_signal = any(x in doc_values for x in [".pdf", "manual", "amber tutorial", "ambertools tutorial"])

    if has_doc_structure or has_pdf_signal:
        return "pdf" if "page" in lower_meta or "file_name" in lower_meta or ".pdf" in doc_values else "tutorial"

    # Strong signs of email/archive content
    if any(k in lower_meta for k in ["message_id", "thread_url", "subject", "date"]):
        return "email"

    if "archive.ambermd.org" in doc_values:
        return "email"

    return "unknown"

def get_source_details(meta: Dict[str, Any], source_type: str) -> str:
    meta = meta or {}
    if source_type in {"pdf", "tutorial"}:
        file_name = meta.get("file_name", "")
        page = meta.get("page")
        details = []
        if file_name:
            details.append(str(file_name))
        if page is not None:
            details.append(f"page {page}")
        return ", ".join(details)
    date = meta.get("date") or meta.get("date_iso") or ""
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
    if source_type in {"pdf", "tutorial"}:
        return meta.get("title") or meta.get("file_name") or "Amber25 Reference Manual"
    return meta.get("subject") or "Email Thread"

def chunk_pdf_text(text: str, size: int = PDF_CHUNK_SIZE, overlap: int = PDF_CHUNK_OVERLAP) -> list[str]:
    chunks = []
    step = max(1, size - overlap)
    for i in range(0, len(text), step):
        chunk = text[i:i + size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def build_or_load_pdf_index(pdf_path: str):
    base_name = os.path.splitext(pdf_path)[0]
    index_path = base_name + ".faiss"
    chunks_path = base_name + ".chunks.npy"
    metas_path = base_name + ".meta.npy"

    if os.path.exists(index_path) and os.path.exists(chunks_path) and os.path.exists(metas_path):
        index = faiss.read_index(index_path)
        chunks = np.load(chunks_path, allow_pickle=True).tolist()
        metas = np.load(metas_path, allow_pickle=True).tolist()
        return index, chunks, metas

    reader = PdfReader(pdf_path)
    all_chunks = []
    all_metas = []

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if not page_text.strip():
            continue

        page_chunks = chunk_pdf_text(page_text)
        for chunk_idx, chunk in enumerate(page_chunks, start=1):
            all_chunks.append(chunk)
            all_metas.append({
                "source_type": "pdf",
                "title": "Amber25 Reference Manual",
                "file_name": os.path.basename(pdf_path),
                "pdf_path": pdf_path,
                "page": page_num,
                "chunk_index": chunk_idx,
            })

    if not all_chunks:
        raise ValueError(f"No readable text extracted from PDF: {pdf_path}")

    embeddings = embedding_model.embed_documents(all_chunks)
    embeddings = np.asarray(embeddings, dtype=np.float32)
    embeddings = np.ascontiguousarray(embeddings)
    faiss.normalize_L2(embeddings)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    faiss.write_index(index, index_path)
    np.save(chunks_path, np.array(all_chunks, dtype=object), allow_pickle=True)
    np.save(metas_path, np.array(all_metas, dtype=object), allow_pickle=True)

    return index, all_chunks, all_metas

def retrieve_pdf_chunks(query: str, pdf_path: str = PDF_PATH, top_k: int = PDF_TOP_K, min_score: float = PDF_MIN_SCORE):
    resolved_pdf_path = resolve_pdf_path(pdf_path)

    if not PDF_AVAILABLE or not os.path.exists(resolved_pdf_path):
        return []

    try:
        index, chunks, metas = build_or_load_pdf_index(resolved_pdf_path)
    except Exception as exc:
        print(f"[pdf] Failed to load PDF chunks from {resolved_pdf_path}: {exc}")
        return []

    if len(chunks) == 0:
        return []

    query_embedding = embedding_model.embed_query(query)
    query_embedding = np.asarray(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_embedding) + 1e-12
    query_embedding = np.ascontiguousarray((query_embedding / query_norm).reshape(1, -1))

    fetch_k = min(max(top_k * 4, 12), len(chunks))
    scores, indices = index.search(query_embedding, fetch_k)

    out = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        semantic_score = float(score)
        if semantic_score < min_score:
            continue

        text = chunks[idx]
        meta = dict(metas[idx])
        meta["pdf_path"] = resolved_pdf_path
        overlap_score = keyword_overlap_score(query, text)
        combined_score = semantic_score + (0.04 * overlap_score)

        out.append({
            "text": text,
            "metadata": meta,
            "score": combined_score,
            "semantic_score": semantic_score,
            "keyword_score": overlap_score,
            "source_type": "pdf",
        })

    out.sort(
        key=lambda x: (
            x.get("keyword_score", 0.0),
            x.get("semantic_score", 0.0),
            x.get("score", 0.0),
        ),
        reverse=True,
    )
    return out[:top_k]

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
    pdf_top_k: int = PDF_TOP_K
) -> List[Dict[str, Any]]:
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
        if source_type == "unknown":
            source_type = "email"

        merged.append({
            "text": d.page_content,
            "metadata": meta,
            "score": float(score),
            "source_type": source_type,
        })

    if include_pdf:
        merged.extend(retrieve_pdf_chunks(query, pdf_path=PDF_PATH, top_k=pdf_top_k, min_score=PDF_MIN_SCORE))

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
    retrieved_docs, docs = select_supporting_docs(
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
    resolved_pdf_path = resolve_pdf_path(PDF_PATH)
    print(f"PDF_RESOLVED_PATH: {resolved_pdf_path}")
    print(f"PDF_READER_AVAILABLE: {PDF_AVAILABLE}")
    if not PDF_AVAILABLE and PDF_IMPORT_ERROR:
        print(f"PDF_IMPORT_ERROR: {PDF_IMPORT_ERROR}")
    print(f"PDF_EXISTS: {os.path.exists(resolved_pdf_path)}")
    print(f"Retrieved {len(retrieved_docs)} combined docs")
    print(f"Selected {len(docs)} supporting docs\n")

    for i, d in enumerate(docs, start=1):
        meta = d.get("metadata", {}) or {}
        preview = make_preview_snippet(d.get("text", ""), query)

        print(f"--- S{i} ---")
        print("type   :", d.get("source_type", "unknown"))
        print("score  :", round(d.get("score", 0.0), 4))
        if "semantic_score" in d:
            print("semantic_score:", round(d.get("semantic_score", 0.0), 4))
        if "keyword_score" in d:
            print("keyword_score :", round(d.get("keyword_score", 0.0), 4))
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
    max_docs: int = 6,
    min_chroma_score: float = CHROMA_MIN_SCORE
) -> List[Dict[str, Any]]:
    q = query.lower()
    is_howto = any(x in q for x in ["how do i", "how to", "use tleap", "build", "prepare", "setup", "workflow"])
    is_troubleshooting = any(x in q for x in ["error", "nan", "illegal memory access", "segmentation fault", "crash", "fail"])

    selected = []

    for d in docs:
        score = float(d.get("score", 0.0))
        source_type = d.get("source_type", "unknown")
        text = (d.get("text") or "").lower()

        if source_type == "email" and score != 0.0 and score < min_chroma_score:
            continue

        keyword_hits = sum(1 for term in [
            "tleap", "solvatebox", "tip3pbox", "minimization",
            "pmemd.cuda", "nan", "sander", "double precision"
        ] if term in text)
        keyword_hits += int(round(d.get("keyword_score", 0.0)))

        command_hits = sum(1 for term in [
            "loadpdb", "saveamberparm", "savepdb", "addions",
            "addion", "solvatebox", "solvateoct", "source leaprc"
        ] if term in text)
        procedural_bonus = command_hits * 2

        bias = 0
        if is_howto and source_type in {"pdf", "tutorial"}:
            bias += 10
        if is_troubleshooting and source_type == "email":
            bias += 8
        if is_howto and source_type == "email" and command_hits > 0:
            bias += 4
        if is_howto and source_type in {"pdf", "tutorial"} and command_hits > 0:
            bias += 6

        d["keyword_hits"] = keyword_hits
        d["command_hits"] = command_hits
        d["procedural_bonus"] = procedural_bonus
        d["bias"] = bias
        selected.append(d)

    selected = sorted(
        selected,
        key=lambda x: (
            x.get("bias", 0),
            x.get("procedural_bonus", 0),
            x.get("keyword_hits", 0),
            x.get("score", 0.0),
        ),
        reverse=True
    )

    if is_howto:
        pdf_docs = [d for d in selected if d.get("source_type") in {"pdf", "tutorial"}]
        email_docs = [d for d in selected if d.get("source_type") == "email"]
        mixed = []

        mixed.extend(pdf_docs[: max(1, min(3, max_docs - 2 if max_docs > 2 else max_docs))])
        mixed.extend(email_docs[: min(3, max_docs - len(mixed))])

        for d in selected:
            if len(mixed) >= max_docs:
                break
            if d not in mixed:
                mixed.append(d)

        return mixed[:max_docs]

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
            meta.get("subject") or meta.get("title") or meta.get("file_name"),
            f"id={meta.get('id') or raw_meta.get('message_id') or 'unknown'}",
            f"type={d.get('source_type', 'unknown')}"
        ]
        header = " | ".join([str(x) for x in header_bits if x])

        text = clean_chunk_text((d.get("text") or "").strip())
        if len(text) > max_chars_per_doc:
            text = text[:max_chars_per_doc].rsplit(" ", 1)[0] + "..."

        block = f"[{label}] ({header})\n{text}\n"

        if total + len(block) > max_total_chars:
            break

        blocks.append(block)
        total += len(block)

    return "\n".join(blocks).strip()


def select_supporting_docs(
    query: str,
    chroma_client: Chroma,
    top_k: int = DEFAULT_TOP_K,
    use_mmr: bool = True,
    include_pdf: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    expanded_query = expand_query(query)
    retrieved_docs = retrieve_hybrid_context(
        expanded_query,
        chroma_client,
        top_k=top_k,
        use_mmr=use_mmr,
        include_pdf=include_pdf
    )
    selected_docs = choose_supporting_docs(query, retrieved_docs, max_docs=top_k)
    return retrieved_docs, selected_docs


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

The context may include:
- AMBER mailing-list email threads
- Amber25 Reference Manual PDF chunks

Rules:
- Use only the retrieved context.
- Do not use outside knowledge.
- Do not repeat the user's question.
- Do not copy large passages from the context.
- Prefer PDF/manual evidence for how-to and workflow questions.
- Prefer email evidence for troubleshooting and error questions.
- Do not present one user's example filenames, frcmod files, library files, or PDB names as general required steps.
- If the context contains examples rather than a complete procedure, say that clearly.
- Do not mention sender names or email formatting.

Write exactly in this format:

Likely answer:
<1-3 sentences>

Why:
<1-3 sentences based only on the retrieved context>

What to try:
- <step 1>
- <step 2>
- <step 3>

If still missing information:
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
        dtype=torch.float16 if device == "cuda" else torch.float32,
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

def llm_only_answer(user_query: str, device: str = None, max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS) -> str:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    tokenizer, model = load_model(device)
    prompt = f"""You are Amber Support Assistant.

Answer the following question as best as you can.

Question:
{user_query}
"""
    return generate_answer(prompt, tokenizer, model, max_new_tokens=max_new_tokens)


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

    _, docs = select_supporting_docs(
        user_query,
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
        "corrupted executable",
        "operating system",
        "overheating",
        "low memory",
        "CUDA library",
        "1DX.frcmod",
        "idx.lib",
        "hbay.pdb",

    ]

    bad_answer = (
        not answer.strip()
        or answer.strip().lower() == user_query.strip().lower()
        or len(answer.split()) < 8
        or "1. load the necessary" in answer.lower()
        or "2. add ions" in answer.lower()
        or "3. use tleap to build" in answer.lower()
        or "you need to load the necessary" in answer.lower()
        or any(p.lower() in answer.lower() for p in unsupported_phrases)
    )

    if bad_answer:
        q_lower = user_query.lower()
        is_howto = any(x in q_lower for x in ["how do i", "how to", "use tleap", "build", "prepare", "setup", "workflow"])
        answer = howto_answer_from_context(user_query, docs) if is_howto else fallback_answer_from_context(user_query, docs)

    sources_section = build_sources_section(docs[:6])
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
        choices=["retrieve", "rag", "test", "llm"],
        default="rag",
        help="retrieve = retrieval-only, rag = full pipeline, test = run queries from a file, llm = no-RAG baseline"
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
    parser.add_argument("--pdf_path", type=str, default=None, help="Override the Amber PDF path")
    parser.add_argument("--find_pdf", action="store_true", help="Search common server locations for Amber25.pdf and exit")

    args = parser.parse_args()

    global PDF_PATH
    if args.pdf_path:
        PDF_PATH = args.pdf_path

    if args.find_pdf:
        matches = find_pdf_candidates(filename=os.path.basename(PDF_PATH) or "Amber25.pdf")
        print("\nPDF search results:")
        if matches:
            for path in matches:
                print(path)
        else:
            print(f"No matches found for {os.path.basename(PDF_PATH) or 'Amber25.pdf'}")
        return

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

    elif args.mode == "llm":
        ans = llm_only_answer(
            args.query,
            device=device,
            max_new_tokens=args.max_new_tokens
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









