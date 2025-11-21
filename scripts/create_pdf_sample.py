#!/usr/bin/env python3
"""Create a small sample JSONL from a larger PDF chunks JSONL for demos.

Usage:
  python scripts/create_pdf_sample.py --in data/pdf_chunks/amber25_chunks.jsonl --out data/pdf_chunks/sample_amber25_chunks.jsonl --count 5
"""
import argparse
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="infile", required=True)
    p.add_argument("--out", dest="outfile", required=True)
    p.add_argument("--count", type=int, default=5)
    args = p.parse_args()

    infile = Path(args.infile)
    outfile = Path(args.outfile)
    outfile.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with infile.open("r", encoding="utf8") as fin, outfile.open("w", encoding="utf8") as fout:
        for line in fin:
            if written >= args.count:
                break
            fout.write(line)
            written += 1

    print(f"Wrote {written} records to {outfile}")


if __name__ == "__main__":
    main()
