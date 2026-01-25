# Query Understanding & Prompt Engineering Framework  
*(Pre-ChromaDB RAG Front-End Design)*

## Overview

While ChromaDB integration and large-scale data ingestion are still in progress, the RAG team will focus on building the **query understanding and prompt engineering framework**.  

The objective is to ensure that the **front-end intelligence** of the RAG pipeline—how user queries are interpreted, normalized, and transformed into LLM prompts—is well-defined and ready for seamless integration once retrieval is online.

This work is independent of the vector store and can be developed, tested, and refined using mock retrieval results.

---

## Goals

- Normalize and structure user queries for consistent retrieval
- Improve semantic clarity of technical Amber-related queries
- Design robust prompt templates for downstream LLM usage
- Ensure predictable, controllable LLM behavior
- Minimize hallucinations and irrelevant responses

---

## Scope (Current Phase)

✔ Query parsing and normalization  
✔ Query intent classification  
✔ Prompt template design  
✔ Context formatting strategy  
✔ Guardrails for insufficient or ambiguous context  

✘ ChromaDB integration  
✘ Large-scale document ingestion  
✘ End-to-end production orchestration  

---

## Query Understanding Pipeline

### 1. Raw User Query Input

Examples:
- “tleap unknown atom type”
- “Why does pmemd crash on GPU?”
- “How do I generate frcmod for modified residues?”

Queries may be:
- Short keyword-based
- Natural language questions
- Error-message fragments

---

### 2. Query Normalization

Normalize queries before retrieval to improve semantic matching.

**Normalization steps:**
- Lowercasing
- Trimming whitespace
- Removing non-essential punctuation
- Preserving technical tokens (`tleap`, `pmemd`, atom names, residue IDs)

**Example:**

| Raw Query | Normalized Query |
|----------|------------------|
| “TLeap Unknown Atom Type!!!” | “tleap unknown atom type” |
| “pmemd CUDA crash??” | “pmemd cuda crash” |

This step improves consistency across embedding and retrieval models.

---

### 3. Query Intent Classification (Lightweight)

Classify queries into coarse categories to guide prompt framing.

**Proposed intent classes:**
- `error_debugging`
- `how_to`
- `concept_explanation`
- `configuration/setup`
- `unknown / other`

**Examples:**

| Query | Intent |
|------|--------|
| “tleap unknown atom type” | error_debugging |
| “how to generate frcmod” | how_to |
| “what is histidine protonation” | concept_explanation |

Intent can initially be inferred via simple heuristics (keywords like *error*, *crash*, *how*, *why*), with LLM-based classification added later if needed.

---

## Prompt Engineering Framework

### 4. Context Assembly (Post-Retrieval)

Once retrieval is available, the prompt will include:

- Top-k retrieved chunks
- Source identifiers (document title, chunk id)
- Optional confidence scores (not shown to user)

**Context format (example):**
