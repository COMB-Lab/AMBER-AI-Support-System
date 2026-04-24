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
    {
        "id": "Q6",
        "question": "Amber22 cmake says CUDA 11.7 and GCC are incompatible. Does Amber22 support CUDA 11.7 and what should I do?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Update your CUDA version to 12.3, edit the relevant cmake files as described in the referenced Amber archive thread, and prefer GCC 11.x. Charo's experience suggests newer GCC may sometimes work, but that is not presented as the recommended path.",
        "actual": "Update CUDA to 12.3 and edit the cmake files as described in the referenced archive thread. Todd also recommended using GCC 11.x and noted that Ubuntu 22.04 LTS with CUDA 12.3 and AmberTools23 works as expected.",
        "chatgpt": "Amber22 should be treated as not reliably supported out of the box for CUDA 11.7 in this setup. The recommended path is to move to CUDA 12.3, apply the cmake edits described in the referenced Amber archive thread, and use GCC 11.x for a known good configuration.",
        "avg_retrieval_similarity": 0.7262
    },
    {
        "id": "Q7",
        "question": "MMPBSA.py fails with CalcError: cpptraj failed with prmtop ... (protein-protein complex). Where do I look and what common setup issues cause this?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check that the protein-protein complex is defined correctly in the MMPBSA.py input, verify that the cp, rp, and lp topology files are correct, review calculation options such as nonpolar solvation, and inspect warnings and temporary MMPBSA files for clues.",
        "actual": "Todd first asked for the actual mmpbsa.in and tleap.in files. He then pointed out two likely setup issues: the tleap input appeared to be missing PBRadii settings, and the salt concentration in tleap did not match the value used in mmpbsa.in. He suggested merging tleap preparation into one script and trying the GB calculation first before PB.",
        "chatgpt": "Start by checking the exact mmpbsa.in and tleap.in files. The main setup issues called out in the thread were missing PBRadii settings in tleap and a salt concentration mismatch between tleap and mmpbsa.in. A good next step is to merge system preparation into one tleap script and test GB-only before turning PB back on.",
        "avg_retrieval_similarity": 0.5864
    },
    {
        "id": "Q8",
        "question": "GAMESS optimization exits without minimizing and SCF energy loops for 200 iterations. What should I try to resolve SCF convergence?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check the SCF convergence threshold, verify that the maximum iteration count is not too low, consider increasing the DFT grid size, and confirm that any multithreading settings are configured correctly. No sufficiently relevant prior answer was found in the knowledge base regarding a direct fix.",
        "actual": "The mailing list reply in this thread did not provide a concrete troubleshooting procedure. It mostly explained that GAMESS is iteratively searching for a self-consistent solution during the SCF procedure.",
        "chatgpt": "The thread itself does not give a real fix. It mostly explains that the SCF procedure is iteratively searching for a self-consistent solution, so there is not enough grounded information in that thread alone to recommend a reliable correction.",
        "avg_retrieval_similarity": 0.6013
    },
    {
        "id": "Q9",
        "question": "Best OS recommendation for installing Amber + CUDA on an RTX 3070 server: Rocky Linux vs Ubuntu? What setup is known to work?",
        "generated": "Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine, and Todd advised sticking with that version because newer Ubuntu releases may include unsupported GCC versions. The retrieved context also suggests checking that the cmake files are modified appropriately for CUDA 12.3.",
        "actual": "Todd said Ubuntu 22.04 LTS with AmberTools23 and CUDA 12.3 works fine, encouraged switching if possible, and advised sticking with 22.04 LTS because later releases may ship with a higher-than-supported GCC compiler.",
        "chatgpt": "Ubuntu 22.04 LTS is the known working setup here, paired with AmberTools23 and CUDA 12.3. The recommendation is to prefer that configuration over Rocky Linux for this case and avoid newer Ubuntu releases that may bring unsupported GCC versions.",
        "avg_retrieval_similarity": 0.5552
    },
    {
        "id": "Q10",
        "question": "After a constant pH simulation, how can I get the charge of residues over time and visualize/analyze it?",
        "generated": "The context suggests using cphstats to analyze residue charges after a constant pH MD simulation. It recommends computing running averages of protonation states and totals, and then visualizing the resulting values with plotting tools.",
        "actual": "Amy recommended using cphstats. She pointed to the Amber 22 manual section on cumulative, running, and chunk averages, and noted that the reported total charge is relative to the lowest possible charge state of the system.",
        "chatgpt": "Use cphstats to analyze the residue charge behavior after a constant pH simulation. The relevant Amber manual section explains how to compute running or chunk averages of fraction protonated per residue and their total, with the total charge reported relative to the lowest possible charge state.",
        "avg_retrieval_similarity": 0.6139
    },
    {
        "id": "Q11",
        "question": "Amber22 build fails at pytraj: fatal error: longintrepr.h: No such file or directory (Python 3.11 via miniconda). How do I fix the build?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check whether Amber is using the Miniforge Python interpreter, remove conflicting miniconda paths from PATH during the build, apply available Amber updates, and verify that the Python executable variable points to the interpreter managed by Amber.",
        "actual": "Todd said this issue is tied to the miniconda Python 3.11 setup. He recommended setting -DDOWNLOAD_MINICONDA=FALSE in run_cmake and ensuring that the system Python version is 3.10 at most.",
        "chatgpt": "The practical fix is to avoid the Amber-managed miniconda Python 3.11 build path. Set -DDOWNLOAD_MINICONDA=FALSE in run_cmake and build against a system Python version no newer than 3.10.",
        "avg_retrieval_similarity": 0.5953
    },
    {
        "id": "Q12",
        "question": "CpHMD in Amber22: constantpH.F90 ignores my &CNSTPHE_LIMITS block in cpin and MAX_TITR_RES overflows. What can I try?",
        "generated": "Increase ntres to a sufficiently large number, such as 273, and see whether the calculation proceeds. The retrieved context also mentions trying a smaller time step and restraints, but the main direct suggestion is to test with larger CNSTPHE limits.",
        "actual": "Vinícius suggested testing with a larger CNSTPHE_LIMITS block: ntres=273, maxh=5, natchrg=273, ntstates=273, to see whether the calculation goes through.",
        "chatgpt": "As a direct test, try increasing the CNSTPHE_LIMITS values to larger numbers, for example ntres=273, maxh=5, natchrg=273, and ntstates=273, and then see whether the calculation runs successfully.",
        "avg_retrieval_similarity": 0.5117
    },
    {
        "id": "Q13",
        "question": "CpHMD with pmemd.cuda gives illegal memory access launching kernel kNLSkinTest when cpin has more than 12 titratable residues. How can I debug this?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Inspect the generated diff file under the Amber test logs, try running the CUDA tests manually with the selected GPU, and review whether the issue is reproducible under the standard test setup.",
        "actual": "Vinícius said CUDA errors like this often point to problems with the input files. He suggested running the same calculation with the serial code and checking the mdout, running the same input with constant pH turned off, and then repeating the same checks with sander if needed.",
        "chatgpt": "Treat this as an input-debugging problem rather than a confirmed CUDA limit. Run the same case with the serial code and inspect mdout, then rerun with constant pH disabled to isolate whether CpHMD is the trigger, and if needed repeat the same checks with sander.",
        "avg_retrieval_similarity": 0.5263
    },
    {
        "id": "Q14",
        "question": "MMPBSA.py.MPI crashes with TypeError: a bytes-like object is required, not 'str' on one rank. What should I check first?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check that mpi4py is installed in the Amber environment, verify that PYTHONPATH points to the intended Amber environment, try the imports used by MMPBSA.py manually, and inspect any mpi4py-related installation errors.",
        "actual": "Bill said to check the receptor mdout for the failing rank, which in this case was rank 39, and look near the end for something unusual or an error message that would help diagnose the problem.",
        "chatgpt": "Start with the output from the failing MPI rank. The thread specifically suggests checking the receptor mdout for the failing rank and looking near the end for an unusual message or the real underlying error.",
        "avg_retrieval_similarity": 0.572
    },
    {
        "id": "Q15",
        "question": "amb2gro_top_gro.py fails because 'No module named parmed'. How do I fix this in Amber22?",
        "generated": "The context suggests debugging steps rather than a confirmed fix. Check PYTHONPATH and AMBERHOME, try installing parmed, report the output of which parmed and echo $AMBERHOME, and verify from a Python prompt that parmed imports correctly.",
        "actual": "Todd suggested first checking environment setup: run which parmed and echo $AMBERHOME, and confirm that import parmed works in the same Python being used. Shiyu also suggested explicitly running the script with the correct Python interpreter, such as the Amber-managed one.",
        "chatgpt": "Use the Amber Python environment rather than an arbitrary system interpreter. Check which parmed, echo $AMBERHOME, verify that parmed imports in that same Python, and if needed run the script explicitly with the Amber-managed Python interpreter.",
        "avg_retrieval_similarity": 0.5639
    }
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