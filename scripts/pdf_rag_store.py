#!/usr/bin/env python3
"""Download and store a PDF for RAG pipeline use.

Usage:
    python scripts/pdf_rag_store.py --url https://ambermd.org/doc12/Amber25.pdf

Outputs (repo-relative):
  data/pdfs/<slug>/<filename>.pdf
  data/pdfs/<slug>/metadata.json (SHA256 verification)

This is a minimal R&D prototype to determine the best way to store PDFs for RAG.
The raw PDF is preserved for provenance and potential binary analysis.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests


def slug_from_url(url: str) -> str:
    p = urlparse(url)
    name = Path(p.path).stem.lower()
    return name or "pdf_doc"


def ensure_dirs(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_pdf(url: str, out_path: Path) -> Path:
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    ensure_dirs(out_path.parent)
    with out_path.open("wb") as f:
        for chunk in r.iter_content(8192):
            if chunk:
                f.write(chunk)
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="PDF URL to download")
    p.add_argument("--out-root", default="data", help="Output root dir")
    args = p.parse_args()

    url = args.url
    slug = slug_from_url(url)
    out_root = Path(args.out_root)
    pdf_dir = out_root / "pdfs" / slug
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_name = Path(urlparse(url).path).name or f"{slug}.pdf"
    pdf_path = pdf_dir / pdf_name

    print(f"Downloading {url} -> {pdf_path}")
    download_pdf(url, pdf_path)
    sha = sha256_file(pdf_path)
    print(f"Saved PDF, sha256={sha}")

    # write metadata summary for provenance
    meta = {"url": url, "filename": str(pdf_path.name), "sha256": sha}
    with (pdf_dir / "metadata.json").open("w", encoding="utf8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("Done. Outputs:")
    print(f"  raw PDF: {pdf_path}")
    print(f"  metadata: {pdf_dir / 'metadata.json'}")


if __name__ == "__main__":
    main()
