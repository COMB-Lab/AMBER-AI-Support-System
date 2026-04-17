from evaluation import f1_token_overlap
import matplotlib.pyplot as plt

cases = [
    {
        "id": "Q1",
        "question": "amb2gro_top_gro.py missing parmed",
        "generated": "The Context suggests debugging steps rather than a confirmed fix.  1. Find the location of the right Python interpreter. 2. Run the `amb2gro_top_gro.py` with the absolute path of Python, like `/usr/local/python amb2gro_top_gro.py -h` or `$AMBERHOME/miniconda/bin/python amb2gro_top_gro.py -h`. 3. Check if you have installed the parmed module. If not, install it. 4. Verify that your PYTHONPATH and/or AMBERHOME is correctly set. Note: These steps are based on Todd Minehardt's response in [CITE 6] and Shiyu Wang's response in [CITE 7]. Sources: - [Re: [AMBER] Amber to gromacs conversion](http://archive.ambermd.org/202401/0003.html) - [Re: [AMBER] Amber to gromacs conversion](http://archive.ambermd.org/202401/0005.html) - [[AMBER] Grumpy GROMBER over a ZeroDivisionError](http://archive.ambermd.org/202108/0128.html)",
        "actual": "Check PYTHONPATH and AMBERHOME, run which parmed and echo $AMBERHOME, and confirm import parmed works in the same Python being used.",
        "chatgpt": "Use the Amber-provided Python environment and verify that parmed is installed there. Run echo $AMBERHOME and $AMBERHOME/bin/python -c \"import parmed\" to confirm. If it fails, install parmed into the same interpreter or source the Amber environment before running the script.",
        "avg_retrieval_similarity": 0.4436,
    },
    {
        "id": "Q2",
        "question": "MMPBSA.py.MPI TypeError bytes-like object required not str",
        "generated": "MMPBSA.py.MPI TypeError: bytes-like object required, not str. The Context suggests debugging steps rather than a confirmed fix. To troubleshoot the issue: 1. Check your PYTHONPATH to ensure it is pointing to the correct directory. 2. Verify that mpi4py is installed in the amber environment. If not, install it using 'amber.conda'. 3. Try executing the imports at the top of $AMBERHOME/AmberTools/src/mmpbsa_py/MMPBSA.py with amber.python under circumstances where you know that the PYTHONPATH is the amber one. No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket: https://ambermd.org/MailingLists.php Sources: - [Re: [AMBER] can't install MMPBSA.py.MPI](http://archive.ambermd.org/201511/0144.html) - [Re: [AMBER] mpi4py Problem](http://archive.ambermd.org/202202/0083.html) - [Re: [AMBER] MMPBSA.py.MPI and pytraj bugs](http://archive.ambermd.org/202204/0013.html)",
        "actual": "Check the receptor mdout file for the failing rank and look for something unusual near the end.",
        "chatgpt": "Start by inspecting the output files for the failing MPI rank, especially the receptor mdout file for that rank. Look near the end for unusual messages or errors, as the root cause is likely revealed there rather than in the Python traceback.",
        "avg_retrieval_similarity": 0.5846,
    },
    {
        "id": "Q3",
        "question": "Best OS recommendation for Amber + CUDA on RTX 3070",
        "generated": "The Context does not provide a clear answer to the best OS recommendation for Amber + CUDA on RTX 3070. However, it suggests that compatibility depends on various factors such as operating system, CUDA version, and drivers. Maria Nagan's response in the email thread recommends checking the NVIDIA site for full details on compatibility. The Context also mentions that suitable information can be found at https://ambermd.org/GPUHardware.php, but this is not a direct answer to the question. Since there is no clear solution or debugging advice provided in the Context, and considering that it does not contain enough information for either a clear solution or reliable debugging advice, the answer should be: No sufficiently relevant prior answer was found in the knowledge base. Please submit a support ticket: https://ambermd.org/MailingLists.php Sources: - [Re: [AMBER] Compatibility of NVIDIA RTX 5060/5070/4060/4080 GPUs with Amber installation](http://archive.ambermd.org/202509/0024.html) - [Re: [AMBER] Can L4 GPU cards be used with AMBER 22?](http://archive.ambermd.org/202306/0098.html) - [Re: [AMBER] Recompile amber12 whit cuda 6.0](http://archive.ambermd.org/201405/0273.html)",
        "actual": "Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine, and sticking with 22.04 LTS is advised because later releases may ship with unsupported gcc versions.",
        "chatgpt": "Ubuntu 22.04 LTS is recommended because it is known to work well with AmberTools23 and CUDA 12.3. It is also important to avoid newer Ubuntu releases that may include unsupported GCC versions, so sticking with 22.04 LTS ensures better compatibility.",
        "avg_retrieval_similarity": 0.5902,
    },
    {
        "id": "Q4",
        "question": "What happens if you run paramfit with no command line options?",
        "generated": "A wizard will be initiated that will prompt you for options and help create a job control file. This is recommended when running Paramfit for the first time, as it prompts for all relevant settings for your run and creates the job control file for you, which can then be easily edited by hand. Sources: - [Re: [AMBER] LEaP and PARMSETs](http://archive.ambermd.org/201609/0460.html) - [Re: [AMBER] problems with paramfit](http://archive.ambermd.org/201407/0459.html) - [Re: [AMBER] Question on Paramfit QM File](http://archive.ambermd.org/202108/0011.html)",
        "actual": "Running paramfit without any options launches a wizard that prompts the user for relevant settings and generates a job control file.",
        "chatgpt": "If paramfit is run without any command line options, it launches an interactive wizard that guides the user through setting up the run and generates a job control file. This wizard is recommended because it ensures all required parameters are correctly configured.",
        "avg_retrieval_similarity": 0.5221,
    },
    {
        "id": "Q5",
        "question": "What is pdb4amber used for in Amber?",
        "generated": "pdb4amber is used to prepare PDB files for use in Amber simulations by modifying them to make them more suitable for input into LEaP. It achieves this with the --reduce option, which can be used with the -i and -o options as shown in the example commands. Sources: - [Re: [AMBER] trouble with pdb4amber](http://archive.ambermd.org/201802/0272.html) - [Re: [AMBER] trouble with pdb4amber](http://archive.ambermd.org/201802/0261.html) - [Re: [AMBER] trouble with pdb4amber](http://archive.ambermd.org/201802/0259.html)",
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