import csv
import math
from collections import defaultdict

import matplotlib.pyplot as plt


RESULTS_CSV = "ranking_results.csv"
SUMMARY_CSV = "ranking_summary.csv"


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_results_csv(path):
    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["ce_score"] = safe_float(row.get("ce_score"))
            row["kw_score"] = safe_float(row.get("kw_score"))
            row["answer_length"] = safe_int(row.get("answer_length"))
            row["run_number"] = safe_int(row.get("run_number"))
            rows.append(row)
    return rows


def mean(values):
    return sum(values) / len(values) if values else 0.0


def group_by_pipeline(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["pipeline"]].append(row)
    return grouped


def plot_avg_ce_score(rows):
    grouped = group_by_pipeline(rows)

    pipelines = []
    avg_scores = []

    for pipeline, items in grouped.items():
        pipelines.append(pipeline)
        avg_scores.append(mean([x["ce_score"] for x in items]))

    plt.figure(figsize=(8, 5))
    plt.bar(pipelines, avg_scores)
    plt.title("Average Cross-Encoder Score by Pipeline")
    plt.xlabel("Pipeline")
    plt.ylabel("Average CE Score")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig("avg_ce_score_by_pipeline.png")
    plt.close()


def plot_avg_kw_score(rows):
    grouped = group_by_pipeline(rows)

    pipelines = []
    avg_scores = []

    for pipeline, items in grouped.items():
        pipelines.append(pipeline)
        avg_scores.append(mean([x["kw_score"] for x in items]))

    plt.figure(figsize=(8, 5))
    plt.bar(pipelines, avg_scores)
    plt.title("Average Keyword Overlap by Pipeline")
    plt.xlabel("Pipeline")
    plt.ylabel("Average KW Score")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig("avg_kw_score_by_pipeline.png")
    plt.close()


def plot_avg_answer_length(rows):
    grouped = group_by_pipeline(rows)

    pipelines = []
    avg_lengths = []

    for pipeline, items in grouped.items():
        pipelines.append(pipeline)
        avg_lengths.append(mean([x["answer_length"] for x in items]))

    plt.figure(figsize=(8, 5))
    plt.bar(pipelines, avg_lengths)
    plt.title("Average Answer Length by Pipeline")
    plt.xlabel("Pipeline")
    plt.ylabel("Average Answer Length")
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig("avg_answer_length_by_pipeline.png")
    plt.close()


def plot_ce_score_scatter(rows):
    grouped = group_by_pipeline(rows)

    plt.figure(figsize=(8, 5))

    for pipeline, items in grouped.items():
        x = [row["answer_length"] for row in items]
        y = [row["ce_score"] for row in items]
        plt.scatter(x, y, label=pipeline)

    plt.title("CE Score vs Answer Length")
    plt.xlabel("Answer Length")
    plt.ylabel("CE Score")
    plt.legend()
    plt.tight_layout()
    plt.savefig("ce_score_vs_answer_length.png")
    plt.close()


def plot_ce_score_by_run(rows):
    grouped = group_by_pipeline(rows)

    plt.figure(figsize=(8, 5))

    for pipeline, items in grouped.items():
        items_sorted = sorted(items, key=lambda r: r["run_number"])
        x = list(range(1, len(items_sorted) + 1))
        y = [row["ce_score"] for row in items_sorted]
        plt.plot(x, y, marker="o", label=pipeline)

    plt.title("CE Score by Run Order")
    plt.xlabel("Run Index")
    plt.ylabel("CE Score")
    plt.legend()
    plt.tight_layout()
    plt.savefig("ce_score_by_run.png")
    plt.close()


def main():
    rows = load_results_csv(RESULTS_CSV)

    if not rows:
        print("No rows found in ranking_results.csv")
        return

    plot_avg_ce_score(rows)
    plot_avg_kw_score(rows)
    plot_avg_answer_length(rows)
    plot_ce_score_scatter(rows)
    plot_ce_score_by_run(rows)

    print("Saved graphs:")
    print("  avg_ce_score_by_pipeline.png")
    print("  avg_kw_score_by_pipeline.png")
    print("  avg_answer_length_by_pipeline.png")
    print("  ce_score_vs_answer_length.png")
    print("  ce_score_by_run.png")


if __name__ == "__main__":
    main()