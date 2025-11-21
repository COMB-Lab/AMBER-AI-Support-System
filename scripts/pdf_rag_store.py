#!/usr/bin/env python3
"""Download a PDF, extract per-page text, chunk, and write JSON/JSONL outputs.

Usage:
    python scripts/pdf_rag_store.py --url https://ambermd.org/doc12/Amber25.pdf

Outputs (repo-relative):
  data/pdfs/<slug>/<filename>.pdf
  data/pdfs/<slug>/pages/page_000.json
  data/pdf_chunks/<slug>_chunks.jsonl

This is a small R&D prototype — adjust chunk size and extraction library as
needed for production.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    import pdfplumber
except Exception:
    pdfplumber = None
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


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


def extract_pages_with_pdfplumber(pdf_path: Path):
    if pdfplumber is None:
        raise RuntimeError("pdfplumber not installed. Add it to requirements.txt")
    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append({"page_index": i, "text": text})
    return pages


def extract_pages_with_pypdf(pdf_path: Path):
    if PdfReader is None:
        raise RuntimeError("pypdf not installed. Add it to requirements.txt")
    pages = []
    reader = PdfReader(str(pdf_path))
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append({"page_index": i, "text": text})
    return pages


def simple_char_chunker(text: str, max_chars: int = 2000):
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    cur = []
    cur_len = 0
    for p in paragraphs:
        if cur_len + len(p) + 1 <= max_chars:
            cur.append(p)
            cur_len += len(p) + 1
        else:
            chunks.append("\n\n".join(cur))
            cur = [p]
            cur_len = len(p)
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def write_page_jsons(slug: str, pages: list, out_dir: Path):
    pages_dir = out_dir / "pages"
    ensure_dirs(pages_dir)
    for pg in pages:
        idx = pg["page_index"]
        out = pages_dir / f"page_{idx:03d}.json"
        with out.open("w", encoding="utf8") as f:
            json.dump(pg, f, ensure_ascii=False, indent=2)


def write_chunks_jsonl(slug: str, pages: list, out_dir: Path, max_chars: int = 2000):
    ensure_dirs(out_dir)
    out_file = out_dir / f"{slug}_chunks.jsonl"
    with out_file.open("w", encoding="utf8") as f:
        for pg in pages:
            page_idx = pg["page_index"]
            text = pg.get("text", "")
            chunks = simple_char_chunker(text, max_chars=max_chars)
            for ci, c in enumerate(chunks):
                doc_id = f"{slug}_p{page_idx}_c{ci}"
                rec = {"id": doc_id, "text": c, "metadata": {"slug": slug, "page": page_idx, "chunk_index": ci}}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="PDF URL to download")
    p.add_argument("--out-root", default="data", help="Output root dir")
    p.add_argument("--max-chars", type=int, default=2000, help="Max chars per chunk")
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

    # extract
    print("Extracting pages... trying pypdf first")
    pages = []
    try:
        pages = extract_pages_with_pypdf(pdf_path)
        print(f"Extracted {len(pages)} pages with pypdf")
    except Exception as e:
        print(f"pypdf extraction failed: {e}")
        print("Falling back to pdfplumber...")
        try:
            pages = extract_pages_with_pdfplumber(pdf_path)
            print(f"Extracted {len(pages)} pages with pdfplumber")
        except Exception as e2:
            print(f"pdfplumber extraction failed: {e2}")
            raise

    # write page JSONs
    write_page_jsons(slug, pages, pdf_dir)

    # write chunks JSONL
    chunks_dir = out_root / "pdf_chunks"
    write_chunks_jsonl(slug, pages, chunks_dir, max_chars=args.max_chars)

    # write metadata summary
    meta = {"url": url, "filename": str(pdf_path.name), "sha256": sha, "page_count": len(pages)}
    with (pdf_dir / "metadata.json").open("w", encoding="utf8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("Done. Outputs:")
    print(f"  raw PDF: {pdf_path}")
    print(f"  pages dir: {pdf_dir / 'pages'}")
    print(f"  chunks JSONL: {chunks_dir / (slug + '_chunks.jsonl')}")


if __name__ == "__main__":
    main()
