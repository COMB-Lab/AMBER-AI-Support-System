from sentence_transformers import SentenceTransformer
import numpy as np

EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")


def cosine_similarity(a: str, b: str) -> float:
    emb = EMBEDDER.encode([a, b], convert_to_numpy=True).astype("float32")
    a_vec, b_vec = emb[0], emb[1]

    a_norm = np.linalg.norm(a_vec)
    b_norm = np.linalg.norm(b_vec)

    if a_norm == 0 or b_norm == 0:
        return 0.0

    return float(np.dot(a_vec, b_vec) / (a_norm * b_norm))

def f1_token_overlap(a: str, b: str) -> float:
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())

    overlap = a_tokens & b_tokens

    if len(overlap) == 0:
        return 0.0

    precision = len(overlap) / len(a_tokens)
    recall = len(overlap) / len(b_tokens)

    return 2 * (precision * recall) / (precision + recall)

def average_top_k_similarity(chunks, k: int = 5) -> float:
    scores = [float(ch.get("similarity", 0.0)) for ch in chunks[:k]]
    if not scores:
        return 0.0
    return float(sum(scores) / len(scores))