# AMBER-AI-Support-System
# NAME: Ira Vizcarra

# amber_rag_llm.py
The Retrieval-Augmented Generation (RAG) pipeline is designed for answering technical questions about the AmberMD software and AmberTools workflows.

# evaluate_pipelines.py
Evaluates the performance of AMBER RAG Pipeline compared to:
    ChatGPT
    LLM without RAG
Compares all 3 responses based on given developer response to the query. If ChatGPT LLM does not work, provide a manual response from ChatGPT website.

# FEATURES
- Hybrid retrieval pipeline
    - ChromaDB semantic search
    - PDF semantic search using FAISS
- Automatic PDF chunking and indexing
- Context ranking and similarity scoring

# INSTALLATION
- Download .py files
    > git clone

- Create virtual environment
    > python -m venv venv
    > source venv/bin/activate

- Install required dependencies
    > pip install numpy faiss-cpu requests pypdf sentence-transformers

- You must also install / have access to:
    - Ollama
    - LLaMA 3
    - AMBER ChromaDB

# OLLAMA SETUP
- Install Ollama and pull the model
    > ollama pull llama3

- Start Ollama locally
    > ollama serve

- AMBER Ollama URL
    > http://127.0.0.1:11434