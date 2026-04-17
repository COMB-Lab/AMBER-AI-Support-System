from evaluation import f1_token_overlap
import matplotlib.pyplot as plt

cases = [
    {
        "id": "Q1",
        "question": "amb2gro_top_gro.py missing parmed",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Find the correct Python interpreter, run amb2gro_top_gro.py with the absolute path to that Python, check whether parmed is installed, and verify that PYTHONPATH and AMBERHOME are set correctly.",
        "actual": "Check PYTHONPATH and AMBERHOME, run which parmed and echo $AMBERHOME, and confirm import parmed works in the same Python being used.",
        "chatgpt": "Use the Amber-provided Python environment and verify that parmed is installed there. Run echo $AMBERHOME and $AMBERHOME/bin/python -c \"import parmed\" to confirm. If it fails, install parmed into the same interpreter or source the Amber environment before running the script.",
        "avg_retrieval_similarity": 0.4436,
    },
    {
        "id": "Q2",
        "question": "MMPBSA.py.MPI TypeError bytes-like object required not str",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check that PYTHONPATH points to the correct Amber environment, verify that mpi4py is installed there, and test the imports used by MMPBSA.py with the Amber Python interpreter.",
        "actual": "Check the receptor mdout file for the failing rank and look for something unusual near the end.",
        "chatgpt": "Start by inspecting the output files for the failing MPI rank, especially the receptor mdout file for that rank. Look near the end for unusual messages or errors, as the root cause is likely revealed there rather than in the Python traceback.",
        "avg_retrieval_similarity": 0.5846,
    },
    {
        "id": "Q3",
        "question": "Best OS recommendation for Amber + CUDA on RTX 3070",
        "generated": "Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine, and switching to this setup is recommended. Newer Ubuntu releases may include unsupported GCC versions, so sticking with 22.04 LTS is advised.",
        "actual": "Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine, and sticking with 22.04 LTS is advised because later releases may ship with unsupported gcc versions.",
        "chatgpt": "Ubuntu 22.04 LTS is recommended because it is known to work well with AmberTools23 and CUDA 12.3. It is also important to avoid newer Ubuntu releases that may include unsupported GCC versions, so sticking with 22.04 LTS ensures better compatibility.",
        "avg_retrieval_similarity": 0.5902,
    },
    {
        "id": "Q4",
        "question": "What happens if you run paramfit with no command line options?",
        "generated": "Running paramfit without any command line options starts a wizard that prompts for the relevant settings and helps create a job control file.",
        "actual": "Running paramfit without any options launches a wizard that prompts the user for relevant settings and generates a job control file.",
        "chatgpt": "If paramfit is run without any command line options, it launches an interactive wizard that guides the user through setting up the run and generates a job control file. This wizard is recommended because it ensures all required parameters are correctly configured.",
        "avg_retrieval_similarity": 0.5221,
    },
    {
        "id": "Q5",
        "question": "What is pdb4amber used for in Amber?",
        "generated": "pdb4amber is used to prepare PDB files for Amber by making them more suitable for input into LEaP.",
        "actual": "pdb4amber analyzes and cleans PDB files before loading them into LEaP so the structure can be used to generate topology and coordinate files.",
        "chatgpt": "pdb4amber is used to analyze and clean PDB files before they are used in Amber workflows. It helps fix issues like naming inconsistencies, missing atoms, and formatting so the structure can be properly loaded into LEaP to generate topology and coordinate files.",
        "avg_retrieval_similarity": 0.5899,
    },
]


def main():
    labels = []
    pipeline_scores = []
    chatgpt_scores = []
    retrieval_scores = []   

    print("\nEvaluation Results\n" + "-" * 80)

    for case in cases:
        pipeline_score = f1_token_overlap(case["generated"], case["actual"])
        chatgpt_score = f1_token_overlap(case["chatgpt"], case["actual"])
        retrieval_score = float(case["avg_retrieval_similarity"])

        labels.append(case["id"])
        pipeline_scores.append(pipeline_score)
        chatgpt_scores.append(chatgpt_score)
        retrieval_scores.append(retrieval_score)

        print(f"{case['id']} - {case['question']}")
        print(f"  Pipeline F1:         {pipeline_score:.4f}")
        print(f"  ChatGPT F1:          {chatgpt_score:.4f}")
        print(f"  Retrieval similarity:{retrieval_score:.4f}")
        print()

    plt.figure(figsize=(10, 6))
    x = list(range(len(labels)))

    plt.bar([i - 0.3 for i in x], retrieval_scores, width=0.25, label="Avg Top-5 Retrieval")
    plt.bar([i for i in x], pipeline_scores, width=0.25, label="Pipeline vs Actual")
    plt.bar([i + 0.3 for i in x], chatgpt_scores, width=0.25, label="ChatGPT vs Actual")

    plt.xticks(x, labels)
    plt.ylim(0, 1.0)
    plt.ylabel("F1 Token Overlap")
    plt.title("RAG Evaluation Comparison (F1)")
    plt.legend()
    plt.tight_layout()
    plt.savefig("answer_similarity_scores.png", dpi=200)


if __name__ == "__main__":
    main()