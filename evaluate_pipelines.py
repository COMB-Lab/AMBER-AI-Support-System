import numpy as np
from sentence_transformers import SentenceTransformer

from amber_rag_llm import run_rag
from llm_without_rag import run_no_rag
from chatgpt_llm import run_chatgpt

EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")

def normalize(vecs, axis=None):
    return vecs / np.linalg.norm(vecs, axis=axis, keepdims=True)

def cosine(a, b):
    return float(np.dot(a, b.T)[0][0])

# --------------------------------------------------------
#                  SIMILARITY SCORES
# --------------------------------------------------------

def coverage_score(answer, reference):
    ref_sentences = [s.strip() for s in reference.split(".") if s.strip()]
    ans_sentences = [s.strip() for s in answer.split(".") if s.strip()]

    if not ref_sentences or not ans_sentences:
        return 0.0

    ref_embs = EMBEDDER.encode(ref_sentences, convert_to_numpy=True)
    ans_embs = EMBEDDER.encode(ans_sentences, convert_to_numpy=True)

    ref_embs = normalize(ref_embs, axis=1)
    ans_embs = normalize(ans_embs, axis=1)

    sims = np.dot(ref_embs, ans_embs.T)
    best_matches = np.max(sims, axis=1)

    return float(np.mean(best_matches))

def precision_score(answer, reference):
    ref_sentences = [s.strip() for s in reference.split(".") if s.strip()]
    ans_sentences = [s.strip() for s in answer.split(".") if s.strip()]

    if not ref_sentences or not ans_sentences:
        return 0.0

    ref_embs = EMBEDDER.encode(ref_sentences, convert_to_numpy=True)
    ans_embs = EMBEDDER.encode(ans_sentences, convert_to_numpy=True)

    ref_embs = normalize(ref_embs, axis=1)
    ans_embs = normalize(ans_embs, axis=1)

    sims = np.dot(ans_embs, ref_embs.T)
    best_matches = np.max(sims, axis=1)

    return float(np.mean(best_matches))

def answer_similarity(answer, reference):
    coverage = coverage_score(answer, reference)
    precision = precision_score(answer, reference)

    if coverage + precision == 0:
        f1 = 0.0
    else:
        f1 = 2 * (coverage * precision) / (coverage + precision)

    return {
        "similarity": f1,
        "coverage": coverage,
        "precision": precision
    }

# --------------------------------------------------------
#                     RELEVANCE
# --------------------------------------------------------
def relevance_score(question, answer):
    q_emb = EMBEDDER.encode([question], convert_to_numpy=True)
    a_emb = EMBEDDER.encode([answer], convert_to_numpy=True)

    q_emb = normalize(q_emb)
    a_emb = normalize(a_emb)

    return cosine(q_emb, a_emb)

# --------------------------------------------------------
#                     COMPLETENESS
# --------------------------------------------------------
def completeness_score(answer):
    sentences = [s.strip() for s in answer.split(".") if s.strip()]

    if len(sentences) < 2:
        return 0.3

    length_score = min(len(answer) / 500, 1.0)

    return 0.5 + 0.5 * length_score

# --------------------------------------------------------
#                     REDUNDANCY
# --------------------------------------------------------
def clarity_score(answer):
    sentences = [s.strip() for s in answer.split(".") if s.strip()]

    if len(sentences) < 2:
        return 0.7

    embs = EMBEDDER.encode(sentences, convert_to_numpy=True)
    embs = normalize(embs, axis=1)

    sim_matrix = np.dot(embs, embs.T)

    redundancy = np.mean(sim_matrix)

    return float(1.0 - 0.5 * redundancy)

# --------------------------------------------------------
#                     GROUNDING
# --------------------------------------------------------
def grounding_score(answer, chunks):
    if not chunks:
        return 0.0

    answer_emb = EMBEDDER.encode([answer], convert_to_numpy=True)
    chunk_embs = EMBEDDER.encode(
        [c["text"] for c in chunks],
        convert_to_numpy=True
    )

    answer_emb = normalize(answer_emb)
    chunk_embs = normalize(chunk_embs, axis=1)

    sims = np.dot(chunk_embs, answer_emb.T).flatten()

    return float(
        0.7 * np.mean(sims) +
        0.3 * np.max(sims)
    )

# --------------------------------------------------------
#                     FINAL SCORES
# --------------------------------------------------------
def score_answer(question, answer, reference=None, chunks=None):

    relevance = relevance_score(question, answer)

    if reference:
        sim = answer_similarity(answer, reference)
        correctness = sim["similarity"]
    else:
        correctness = 0.5  # fallback if no ground truth

    completeness = completeness_score(answer)
    clarity = clarity_score(answer)

    score = (
        0.5 * correctness +
        0.2 * relevance +
        0.2 * completeness +
        0.1 * clarity
    )

    if chunks:
        grounding = grounding_score(answer, chunks)
        score += 0.2 * grounding

    return {
        "total": score,
        "correctness": correctness,
        "relevance": relevance,
        "completeness": completeness,
        "clarity": clarity
    }

# --------------------------------------------------------
#                     MAIN EVALUATION
# --------------------------------------------------------
def evaluate_one(question, rag_result, no_rag_result, chatgpt_result, reference=None):

    rag_scores = score_answer(
        question,
        rag_result["answer"],
        reference,
        rag_result.get("chunks", [])
    )

    no_rag_scores = score_answer(
        question,
        no_rag_result["answer"],
        reference
    )

    chatgpt_scores = score_answer(
        question,
        chatgpt_result["answer"],
        reference
    )

    scores = {
        "RAG": rag_scores["total"],
        "No-RAG": no_rag_scores["total"],
        "ChatGPT": chatgpt_scores["total"]
    }

    winner = max(scores, key=scores.get)

    return {
        "scores": scores,
        "winner": winner,
        "breakdown": {
            "RAG": rag_scores,
            "No-RAG": no_rag_scores,
            "ChatGPT": chatgpt_scores
        }
    }

# --------------------------------------------------------
#                         RUN
# --------------------------------------------------------
if __name__ == "__main__":

    question = input("Question: ")
    reference = input("Reference answer (optional, press enter to skip): ").strip()

    if reference == "":
        reference = None

    rag_result = run_rag(question)
    no_rag_result = run_no_rag(question)

    try:
        chatgpt_result = run_chatgpt(question)
    except Exception as e:
        print("\nChatGPT failed:", e)
        chatgpt_result = {"answer": ""}

    result = evaluate_one(
        question,
        rag_result,
        no_rag_result,
        chatgpt_result,
        reference
    )

    print("\n=== RESPONSES ===")

    print("\n--- RAG ---")
    print(rag_result.get("answer", ""))

    print("\n--- No-RAG ---")
    print(no_rag_result.get("answer", ""))

    print("\n--- ChatGPT ---")
    print(chatgpt_result.get("answer", ""))

    print("\n=== FINAL SCORES ===")
    for k, v in result["scores"].items():
        print(f"{k}: {v:.4f}")

    print("\nWinner:", result["winner"])

    print("\n=== BREAKDOWN ===")
    for model, details in result["breakdown"].items():
        print(f"\n{model}")
        for metric, value in details.items():
            print(f"  {metric}: {value:.4f}")