import os
import argparse
from typing import List
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers import BatchEncoding
import torch

# -----------------------
# (A) PORTABLE SETTINGS
# -----------------------
# Use env var if set; otherwise default to local folder
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chromadb_data")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "all-MiniLM-L6-v2")
MODEL_NAME = os.getenv("LLM_MODEL_NAME", "meta-llama/Meta-Llama-3.1-8B-Instruct")

# -----------------------
# (B) INIT EMBEDDINGS + CHROMA
# -----------------------
embedding_model = HuggingFaceEmbeddings(model_name=EMBED_MODEL_NAME)

COLLECTION_NAME = os.getenv("COLLECTION_NAME", "amber_messages")

chroma_client = Chroma(
    persist_directory=CHROMA_DIR,
    embedding_function=embedding_model,
    collection_name=COLLECTION_NAME
)


# -----------------------
# (C) RETRIEVAL
# -----------------------
def retrieve_context_items(query: str, chroma_client: Chroma, top_k: int = 5, use_mmr: bool = True):
    """
    Returns LangChain Document objects with .page_content and .metadata
    """
    if use_mmr:
        # fetch_k pulls more candidates, MMR selects diverse top_k
        return chroma_client.max_marginal_relevance_search(query, k=top_k, fetch_k=max(top_k * 4, 20))
    return chroma_client.similarity_search(query, k=top_k)

def dedup_docs(docs) -> List:
    """
    Deduplicate based on message_id/id if available, otherwise a snippet of text.
    """
    seen = set()
    out = []
    for d in docs:
        meta = d.metadata or {}
        key = meta.get("message_id") or meta.get("id") or d.page_content[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out

def debug_retrieval(query: str, chroma_client: Chroma, top_k: int = 5, use_mmr: bool = True):
    """
    Prints retrieved docs + metadata previews. This is your main "retrieval relevance" test.
    """
    docs = retrieve_context_items(query, chroma_client, top_k=top_k, use_mmr=use_mmr)
    docs = dedup_docs(docs)

    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print(f"CHROMA_DIR: {CHROMA_DIR}")
    print(f"Retrieved {len(docs)} docs (top_k={top_k}, mmr={use_mmr})\n")

    for i, d in enumerate(docs, start=1):
        meta = d.metadata or {}
        print(f"--- S{i} ---")
        print("subject:", meta.get("subject"))
        print("date   :", meta.get("date"))
        print("author :", meta.get("author"))
        print("id     :", meta.get("id") or meta.get("message_id") or "unknown")
        preview = d.page_content[:350].replace("\n", " ")
        print("preview:", preview)
        print()

    return docs


# -----------------------
# (D) CONTEXT + PROMPT
# -----------------------
def format_context(docs, max_chars_per_doc=1200, max_total_chars=6000):
    blocks = []
    total = 0
    for i, d in enumerate(docs, start=1):
        meta = d.metadata or {}
        label = f"S{i}"
        header_bits = [
            meta.get("date"),
            meta.get("subject"),
            meta.get("author"),
            f"id={meta.get('id') or meta.get('message_id') or 'unknown'}"
        ]
        header = " | ".join([x for x in header_bits if x])

        text = d.page_content.strip()
        if len(text) > max_chars_per_doc:
            text = text[:max_chars_per_doc].rsplit(" ", 1)[0] + "…"

        block = f"[{label}] ({header})\n{text}\n"
        if total + len(block) > max_total_chars:
            break
        blocks.append(block)
        total += len(block)

    return "\n".join(blocks).strip()

def looks_relevant(query: str, context_block: str) -> bool:
    """
    Simple heuristic: if at least 2 meaningful query words appear in context, treat as relevant.
    Prevents garbage-context hallucinations.
    """
    if not context_block or context_block.strip() == "":
        return False

    q_words = [w.lower() for w in query.split() if len(w) > 4]
    if not q_words:
        return True

    c = context_block.lower()
    hits = sum(1 for w in set(q_words) if w in c)
    return hits >= 2

def build_prompt(query, context_block):
    return f"""You are Amber Support Assistant.

STRICT RULES:
- Use ONLY the retrieved context below.
- BEFORE answering, you MUST extract evidence from the context.
- Do NOT use placeholders like X, A, B, "try A then B", "as suggested", or generic GPU advice.
- Every section must include citations like [S1].
- If the context does not contain enough info, say:
  "The retrieved sources do not contain enough information to answer this question."
  Then ask for: Amber version, exact command, full error text, and input snippet.
  
Retrieved context:
{context_block if context_block else "[No retrieved context]"}

User question:
{query}

STEP 1 — Evidence (REQUIRED):
Write 3–6 bullet points. Each bullet must include:
- a specific quoted/paraphrased detail from the context (error text, symptom, command, scenario)
- a citation at the end like [S3]

STEP 2 — Final Answer (REQUIRED):
1) Most likely explanation (must cite)
2) Step-by-step fix (must cite)
3) How to verify (must cite)
4) If still failing: what to collect next (must cite)
"""


# -----------------------
# (E) LLM INIT + GENERATION
# -----------------------
def load_model(device: str):
    device = "cuda" if torch.cuda.is_available() else "cpu"

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=True)

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        device_map="auto" if device == "cuda" else None
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    return tokenizer, model
from transformers import BatchEncoding
import torch

def generate_answer(prompt, tokenizer, model, max_new_tokens=350):
    # --- Build encoded inputs ---
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

    # --- Normalize to tensors ---
    # Some tokenizers return a Tensor, others return BatchEncoding (dict-like)
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
        pad_token_id=tokenizer.eos_token_id,
    )
    if attention_mask is not None:
        gen_kwargs["attention_mask"] = attention_mask

    with torch.no_grad():
        output_ids = model.generate(input_ids=input_ids, **gen_kwargs)

    gen_ids = output_ids[0][input_ids.shape[-1]:]
    return tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
# -----------------------
# (F) FULL RAG PIPELINE
# -----------------------
def rag_pipeline(user_query, top_k=5, use_mmr=True, max_new_tokens=300, device=None):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    docs = retrieve_context_items(user_query, chroma_client, top_k=top_k, use_mmr=use_mmr)
    docs = dedup_docs(docs)
    context_block = format_context(docs)
    if not docs:
        return ("I couldn't retrieve relevant Amber mailing-list context for that question.\n"
                "Please paste: Amber version, the exact command you ran, the full error output, and the relevant input $

    if not looks_relevant(user_query, context_block):
        return ("I retrieved context, but it doesn't look strongly related to your question.\n"
                "Please paste: Amber version, the exact command you ran, the full error output, and the relevant input $

    tokenizer, model = load_model(device)
    prompt = build_prompt(user_query, context_block)
    answer = generate_answer(prompt, tokenizer, model, max_new_tokens=max_new_tokens)

    # Hard requirements: citations + evidence section must exist

    if "[S" not in answer or "STEP 1" not in answer:
        return (
            "FAIL: Answer is not grounded (missing citations and/or missing evidence extraction).\n"
            "Try: increase top_k, increase context size, or switch to a stronger instruction-following model."
        )

    # Kill obvious generic filler / placeholders
    banned = ["Try A", "then B", "associated with X", "as suggested", "X.", "A,", "B,"]
    if any(x in answer for x in banned):
        return (
            "FAIL: Answer contains generic placeholders/filler.\n"
            "Your prompt rules were not followed."
        )
    return answer

# -----------------------
# (G) TEST SET RUNNER
# -----------------------
def run_test_set(test_file: str, top_k: int, use_mmr: bool, device: str, max_new_tokens: int):
    with open(test_file, "r", encoding="utf-8") as f:
        queries = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    for q in queries:
        # Retrieval debug first (so you can inspect relevance)
        debug_retrieval(q, chroma_client, top_k=top_k, use_mmr=use_mmr)

        # Then full answer
        ans = rag_pipeline(q, top_k=top_k, use_mmr=use_mmr, device=device, max_new_tokens=max_new_tokens)
        print("ANSWER:\n", ans)
        print("\n" + "-" * 80)

# -----------------------
# (H) CLI ENTRYPOINT
# -----------------------
def main():
    parser = argparse.ArgumentParser(description="Amber RAG Pipeline Tester")
    parser.add_argument("--mode", choices=["retrieve", "rag", "test"], default="rag",
                        help="retrieve = retrieval-only, rag = full pipeline, test = run queries from a file")
    parser.add_argument("--query", type=str, default="pmemd.cuda illegal memory access during minimization",
                        help="Single query to test (used in retrieve/rag modes)")
    parser.add_argument("--top_k", type=int, default=8, help="Number of docs to retrieve")
    parser.add_argument("--mmr", action="store_true", help="Use MMR (diverse) retrieval")
    parser.add_argument("--test_file", type=str, default="test_queries.txt", help="File with one query per line")
    parser.add_argument("--device", type=str, choices=["cpu", "cuda"], default=None,
                        help="Force device; default auto-detect")
    parser.add_argument("--max_new_tokens", type=int, default=300, help="Max tokens for generation")

    args = parser.parse_args()

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    if args.mode == "retrieve":
        debug_retrieval(args.query, chroma_client, top_k=args.top_k, use_mmr=args.mmr)

    elif args.mode == "rag":
        # Show retrieval first (helps you confirm relevance)
        debug_retrieval(args.query, chroma_client, top_k=args.top_k, use_mmr=args.mmr)
        ans = rag_pipeline(args.query, top_k=args.top_k, use_mmr=args.mmr, device=device, max_new_tokens=args.max_new_t$
        print("\nANSWER:\n", ans)

    elif args.mode == "test":
        run_test_set(args.test_file, top_k=args.top_k, use_mmr=args.mmr, device=device, max_new_tokens=args.max_new_tok$

if __name__ == "__main__":
    main()







