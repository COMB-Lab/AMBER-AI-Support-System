# Embedding Model Evaluation for Amber RAG System

## Overview

The goal of this evaluation is to identify a **free, open-source embedding model** suitable for semantic search in an Amber-focused Retrieval-Augmented Generation (RAG) system. The selected model should balance:

- **Retrieval quality** for technical Amber mailing list content  
- **Speed** on small to medium corpora  
- **Resource usage**, preferably CPU-only for ease of deployment  

We conducted small-scale qualitative testing using mock Amber mailing list messages and representative technical queries.

---

## Models Evaluated

All models are open-source and available via Hugging Face.

### 1. `all-MiniLM-L6-v2`
- **Dimensions:** 384  
- **Type:** General-purpose sentence embedding  
- **Speed:** Very fast (CPU-friendly)  
- **Resource Needs:** CPU-only  
- **Domain Suitability:** General technical text  

**Notes:**  
Widely used baseline model with excellent speed. Provides reasonable semantic matching for short technical messages but may miss subtle domain-specific distinctions.

---

### 2. `all-mpnet-base-v2`
- **Dimensions:** 768  
- **Type:** General-purpose sentence embedding  
- **Speed:** Medium  
- **Resource Needs:** CPU (GPU helpful but not required)  
- **Domain Suitability:** General technical text  

**Notes:**  
Higher semantic accuracy than MiniLM, especially for longer or more complex messages. Slower embedding time and larger memory footprint.

---

### 3. `multi-qa-mpnet-base-dot-v1`
- **Dimensions:** 768  
- **Type:** Question–answer–optimized embedding  
- **Speed:** Medium  
- **Resource Needs:** CPU  
- **Domain Suitability:** Query-to-document retrieval  

**Notes:**  
Designed specifically for QA-style semantic search. Performs well when queries are phrased as questions or error descriptions (e.g., “tleap unknown atom type”).

---

### 4. `allenai/scibert_scivocab_uncased`
- **Dimensions:** 768  
- **Type:** Domain-specific (scientific text)  
- **Speed:** Medium–slow  
- **Resource Needs:** GPU recommended (CPU usable)  
- **Domain Suitability:** Scientific / computational chemistry  

**Notes:**  
Captures scientific terminology common in Amber discussions, but is not explicitly trained for sentence-level semantic search and requires careful pooling.

---

### 5. `dmis-lab/biobert-base-cased-v1.2`
- **Dimensions:** 768  
- **Type:** Domain-specific (biomedical / biochemical)  
- **Speed:** Medium–slow  
- **Resource Needs:** GPU recommended  
- **Domain Suitability:** Biochemistry, biomolecular systems  

**Notes:**  
Strong understanding of biochemical terminology, but less aligned with general Amber tooling discussions and more computationally expensive.

---

## Prototype Testing Setup

### Dataset
- 10–20 mock Amber mailing list messages covering:
  - `tleap` errors  
  - Force-field parameter issues  
  - `pmemd` GPU crashes  
  - Residue protonation and topology questions  

### Example Queries
- “tleap unknown atom type”  
- “frcmod parameters for modified residues”  
- “pmemd cuda segmentation fault”  

### Methodology
For each model:
1. Encode all messages into vector embeddings.
2. Encode each query.
3. Perform similarity search using FAISS (inner product on normalized vectors).
4. Inspect top-k results for qualitative relevance.

---

## Evaluation Results (Qualitative)

| Model | Semantic Accuracy | Speed | Resource Notes |
|------|------------------|-------|----------------|
| all-MiniLM-L6-v2 | Medium | ⭐⭐⭐⭐⭐ | Excellent CPU performance |
| all-mpnet-base-v2 | High | ⭐⭐⭐ | Slower but more precise |
| multi-qa-mpnet-base-dot-v1 | **Very High** | ⭐⭐⭐ | Best query → document alignment |
| SciBERT | High | ⭐⭐ | Strong domain language, slower |
| BioBERT | Medium–High | ⭐⭐ | Overkill for general Amber queries |

**Key observations:**
- All models retrieved sensible results for clear, well-formed queries.
- `multi-qa-mpnet-base-dot-v1` consistently ranked the most relevant error messages highest for question-like queries.
- Domain-specific models (SciBERT, BioBERT) understood terminology well but did not significantly outperform MPNet-based models in retrieval relevance.
- MiniLM was fastest but occasionally missed nuanced distinctions between similar error messages.

---

## Recommendation for MVP

### ✅ Recommended Model: `multi-qa-mpnet-base-dot-v1`

**Rationale:**
- Best alignment with Amber usage patterns (users asking error-style questions).
- Strong semantic accuracy without requiring GPU.
- Balanced performance suitable for an MVP RAG system.
- Easy drop-in replacement within an existing SentenceTransformers + FAISS pipeline.

### Alternative Options
- **If speed is the top priority:** `all-MiniLM-L6-v2`  
- **If higher semantic precision is needed:** `all-mpnet-base-v2`  
- **If future domain-specific tuning is planned:** SciBERT (with proper pooling and potential fine-tuning)

---

## Conclusion

For the Amber RAG system MVP, **`multi-qa-mpnet-base-dot-v1`** provides the best balance of retrieval quality, speed, and resource efficiency. It is well-suited to technical mailing list data and can be deployed locally on CPU-only infrastructure.
