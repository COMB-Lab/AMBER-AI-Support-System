import argparse
from typing import Dict, List, Optional

import rag_pipeline
from chatgpt_client import generate_chatgpt_answer
from evaluation_common import (
    answer_without_sources,
    average_source_score,
    read_eval_rows,
    response_similarity,
    safe_similarity_text,
    write_result_rows,
)


def evaluate_rows(
    rows: List[Dict[str, str]],
    top_k: int,
    use_mmr: bool,
    include_pdf: bool,
    device: Optional[str],
    max_new_tokens: int,
    include_chatgpt: bool,
    chatgpt_model: Optional[str],
) -> List[Dict[str, str]]:
    output_rows = []

    for idx, row in enumerate(rows, start=1):
        question = (row.get("question") or row.get("Query") or "").strip()
        actual_answer = (row.get("actual_answer") or row.get("Actual Answer") or "").strip()
        if not question:
            continue

        print(f"[{idx}] Evaluating: {question}")

        _, selected_docs = rag_pipeline.select_supporting_docs(
            question,
            rag_pipeline.chroma_client,
            top_k=top_k,
            use_mmr=use_mmr,
            include_pdf=include_pdf,
        )

        rag_answer_full = rag_pipeline.rag_pipeline(
            question,
            top_k=top_k,
            use_mmr=use_mmr,
            max_new_tokens=max_new_tokens,
            device=device,
            include_pdf=include_pdf,
        )
        rag_answer = answer_without_sources(rag_answer_full)
        rag_similarity = response_similarity(rag_answer, actual_answer)

        llm_answer = rag_pipeline.llm_only_answer(
            question,
            device=device,
            max_new_tokens=max_new_tokens,
        )
        llm_similarity = response_similarity(llm_answer, actual_answer)

        chatgpt_answer = (row.get("chatgpt_answer") or row.get("ChatGPT Answer") or "").strip()
        chatgpt_similarity = None
        chatgpt_status = "provided_in_input" if chatgpt_answer else "skipped"

        if include_chatgpt and not chatgpt_answer:
            try:
                chatgpt_answer = generate_chatgpt_answer(
                    question=question,
                    model=chatgpt_model,
                    max_output_tokens=max_new_tokens,
                )
                chatgpt_status = "generated_via_api"
            except Exception as exc:
                chatgpt_answer = ""
                chatgpt_status = f"error: {exc}"

        if chatgpt_answer:
            chatgpt_similarity = response_similarity(chatgpt_answer, actual_answer)

        output_rows.append({
            "question": question,
            "actual_answer": actual_answer,
            "rag_answer": rag_answer,
            "chatgpt_answer": chatgpt_answer,
            "llm_without_rag_answer": llm_answer,
            "rag_vs_actual_similarity": safe_similarity_text(rag_similarity),
            "chatgpt_vs_actual_similarity": safe_similarity_text(chatgpt_similarity),
            "llm_vs_actual_similarity": safe_similarity_text(llm_similarity),
            "avg_top5_source_score": f"{average_source_score(selected_docs, top_k=top_k):.4f}",
            "sources": rag_pipeline.build_sources_section(selected_docs[:top_k]),
            "chatgpt_status": chatgpt_status,
        })

    return output_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG, ChatGPT, and local no-RAG LLM answers side by side."
    )
    parser.add_argument("--input", required=True, help="CSV/TSV with question and actual_answer columns")
    parser.add_argument("--output", default="all_model_evaluation_results.csv", help="CSV/TSV output path")
    parser.add_argument("--top_k", type=int, default=5, help="Use top-k selected sources")
    parser.add_argument("--mmr", action="store_true", help="Use MMR retrieval")
    parser.add_argument("--no_pdf", action="store_true", help="Disable PDF retrieval")
    parser.add_argument("--pdf_path", type=str, default=None, help="Override Amber PDF path")
    parser.add_argument("--include_chatgpt", action="store_true", help="Generate ChatGPT answers via OpenAI API when not provided in the input file")
    parser.add_argument("--chatgpt_model", type=str, default=None, help="Override OpenAI model for ChatGPT answers")
    parser.add_argument("--device", type=str, choices=["cpu", "cuda"], default=None)
    parser.add_argument("--max_new_tokens", type=int, default=rag_pipeline.DEFAULT_MAX_NEW_TOKENS)

    args = parser.parse_args()

    if args.pdf_path:
        rag_pipeline.PDF_PATH = args.pdf_path

    rows = read_eval_rows(args.input)
    results = evaluate_rows(
        rows=rows,
        top_k=args.top_k,
        use_mmr=args.mmr,
        include_pdf=not args.no_pdf,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        include_chatgpt=args.include_chatgpt,
        chatgpt_model=args.chatgpt_model,
    )

    write_result_rows(args.output, results)
    print(f"Wrote results: {args.output}")


if __name__ == "__main__":
    main()
