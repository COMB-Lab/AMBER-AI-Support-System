# AMBER Tutorial 3.2 – Jupyter Notebook

## Overview

This project demonstrates how to run AMBER Tutorial 3.2 inside a Jupyter Notebook using an Apptainer container.

The notebook:

* Uses `pdb4amber` to clean a PDB file
* Uses `tleap` to build the system
* Uses `sander` to run a short minimization

The original tutorial used `pmemd.cuda`, but this project was adapted to use CPU-based `sander` for compatibility.

---

# Requirements

* Jupyter Notebook
* Apptainer
* `amber_ready.sif`

---

# Files

Generated files:

* `1l2y.amber.pdb`
* `tc5b.1l2y.parm7`
* `tc5b.1l2y.rst7`
* `min.out`
* `min.rst7`

---

# Running the Notebook

Start Jupyter:

```bash
jupyter notebook
```

Run the notebook cells from top to bottom.

---

# Notebook Workflow

## Cell 1

Helper function for running Apptainer commands.

## Cell 2

Verify AMBER tools inside the container.

## Cell 3

Download the PDB file.

## Cell 4

Run `pdb4amber`.

## Cell 5

Create `tleap.in`.

## Cell 6

Run `tleap`.

## Cell 7

Create `min.in`.

## Cell 8

Run minimization using `sander`.

## Cell 9

Check minimization output.

---

# Notes



---

# Author

Alejandro Urbano  
CS 4962 Senior Design Project
