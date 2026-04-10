from evaluation import cosine_similarity
import matplotlib.pyplot as plt


# Fill these in with your real test cases
cases = [
    {
        "id": "Q1",
        "question": "amb2gro_top_gro.py missing parmed",
        "generated": "Install parmed via pip and ensure it is available in the correct Python environment.",
        "actual": "Check PYTHONPATH and AMBERHOME, run which parmed and echo $AMBERHOME, and confirm import parmed works in the same Python being used.",
        "avg_retrieval_similarity": 0.0,
    },
    {
        "id": "Q2",
        "question": "MMPBSA.py.MPI TypeError bytes-like object required not str",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check if mpi4py is installed correctly in the Amber environment and verify PYTHONPATH.",
        "actual": "Check the receptor mdout file for the failing rank and look for something unusual near the end.",
        "avg_retrieval_similarity": 0.0,
    },
    {
        "id": "Q3",
        "question": "Best OS recommendation for Amber + CUDA on RTX 3070",
        "generated": "Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine and is recommended.",
        "actual": "Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine, and sticking with 22.04 LTS is advised because later releases may ship with unsupported gcc versions.",
        "avg_retrieval_similarity": 0.0,
    },
    {
        "id": "Q4",
        "question": "What happens if you run paramfit with no command line options?",
        "generated": "To use the wizard, simply run paramfit without any options. It will prompt for relevant options and create a job control file.",
        "actual": "Running paramfit without any options launches a wizard that prompts the user for relevant settings and generates a job control file.",
        "avg_retrieval_similarity": 0.0,
    },
    {
        "id": "Q5",
        "question": "What is pdb4amber used for in Amber?",
        "generated": "pdb4amber analyses PDB files and cleans them for further usage, especially with the LEaP programs of Amber.",
        "actual": "pdb4amber analyzes and cleans PDB files before loading them into LEaP so the structure can be used to generate topology and coordinate files.",
        "avg_retrieval_similarity": 0.0,
    },
]


def main():
    labels = []
    answer_scores = []
    retrieval_scores = []

    print("\nEvaluation Results\n" + "-" * 80)

    for case in cases:
        answer_score = cosine_similarity(case["generated"], case["actual"])
        retrieval_score = float(case["avg_retrieval_similarity"])

        labels.append(case["id"])
        answer_scores.append(answer_score)
        retrieval_scores.append(retrieval_score)

        print(f"{case['id']} - {case['question']}")
        print(f"  Answer similarity:   {answer_score:.4f}")
        print(f"  Retrieval similarity:{retrieval_score:.4f}")
        print()

    plt.figure(figsize=(10, 6))
    x = range(len(labels))

    plt.bar([i - 0.2 for i in x], retrieval_scores, width=0.4, label="Avg Top-5 Retrieval Similarity")
    plt.bar([i + 0.2 for i in x], answer_scores, width=0.4, label="Generated vs Actual Similarity")

    plt.xticks(list(x), labels)
    plt.ylim(0, 1.0)
    plt.ylabel("Cosine Similarity")
    plt.title("AMBER RAG Evaluation")
    plt.legend()
    plt.tight_layout()
    plt.savefig("answer_similarity_scores.png", dpi=200)
    print("Saved graph to answer_similarity_scores.png")


if __name__ == "__main__":
    main()