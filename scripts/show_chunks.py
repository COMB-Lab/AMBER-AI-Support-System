#!/usr/bin/env python3
"""Display scraped tutorials."""

import json
from pathlib import Path

chunks_dir = Path('data/tutorials_chunks')
chunk_files = list(chunks_dir.glob('*.jsonl'))
print(f'Found {len(chunk_files)} tutorials\n')

# List first few
for f in sorted(chunk_files)[:5]:
    with open(f, encoding='utf-8', errors='replace') as file:
        for line in file:
            chunk = json.loads(line)
            print(f'{f.stem}:')
            print(f'  ID: {chunk["id"]}')
            print(f'  URL: {chunk["metadata"].get("url", "N/A")}')
            print(f'  Text: {chunk["text"][:100]}...\n')
            break
