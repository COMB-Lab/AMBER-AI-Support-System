import csv
from typing import Dict, List, Optional

import numpy as np

import rag_pipeline


def read_eval_rows(path: str) -> List[Dict[str, str]]:
    delimiter = "\t" if path.lower().endswith(".tsv") else ","
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def write_result_rows(path: str, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return

    delimiter = "\t" if path.lower().endswith(".tsv") else ","
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
    return float((a @ b) / denom)


def response_similarity(generated_answer: str, actual_answer: str) -> Optional[float]:
    if not generated_answer.strip() or not actual_answer.strip():
        return None

    embeddings = rag_pipeline.embedding_model.embed_documents([
        generated_answer.strip(),
        actual_answer.strip(),
    ])
    return cosine_similarity(np.asarray(embeddings[0]), np.asarray(embeddings[1]))


def average_source_score(docs: List[Dict], top_k: int = 5) -> float:
    scores = [float(d.get("score", 0.0)) for d in docs[:top_k]]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def answer_without_sources(answer: str) -> str:
    return answer.split("\n\nSources:", 1)[0].strip()


def safe_similarity_text(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.4f}"
