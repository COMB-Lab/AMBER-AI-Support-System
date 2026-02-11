#!/usr/bin/env python3
"""Quick script to download Amber25 PDF with embeddings for RAG.

This is a convenience wrapper that downloads the Amber 25 tutorials PDF
and stores it with embeddings in Chroma for retrieval-augmented generation.

Usage:
    python scripts/store_amber_tutorials_pdf.py
    
    # Or with options:
    python scripts/store_amber_tutorials_pdf.py --use-openai --collection my_collection

By default uses local embeddings (sentence-transformers).
Set OPENAI_API_KEY environment variable to use OpenAI embeddings instead.
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.download_amber_pdf_with_embeddings import main as download_and_embed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download Amber25 PDF and store with embeddings"
    )
    parser.add_argument(
        "--collection",
        default="amber_tutorials",
        help="Chroma collection name (default: amber_tutorials)"
    )
    parser.add_argument(
        "--use-openai",
        action="store_true",
        help="Use OpenAI embeddings (requires OPENAI_API_KEY env var)"
    )
    parser.add_argument(
        "--skip-chroma",
        action="store_true",
        help="Skip storing in Chroma (only download and extract)"
    )
    
    args = parser.parse_args()
    
    # Reconstruct arguments for the main function
    sys.argv = [
        sys.argv[0],
        "--url", "https://ambermd.org/doc12/Amber25.pdf",
        "--collection", args.collection,
    ]
    
    if args.use_openai:
        sys.argv.append("--use-openai")
    
    if args.skip_chroma:
        sys.argv.append("--skip-chroma")
    
    download_and_embed()
