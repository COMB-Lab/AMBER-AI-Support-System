#!/usr/bin/env python3
"""Re-parse all downloaded HTML files to update per-message JSONs.

This imports the `parse_single_email.py` module and runs parse_file on every
HTML under data/html, writing updated JSON under data/json.
"""
from importlib.machinery import SourceFileLoader
from pathlib import Path
import json

PARSER_PATH = Path(__file__).resolve().parent / 'parse_single_email.py'
parse_mod = SourceFileLoader('parse_single_email', str(PARSER_PATH)).load_module()


def main():
    root = Path('data') / 'html'
    files = list(root.rglob('*.html'))
    print(f'Found {len(files)} HTML files to parse')
    for p in files:
        try:
            parsed = parse_mod.parse_file(p)
        except Exception as e:
            print(f'Failed to parse {p}: {e}')
            continue
        # write JSON under data/json/html/<rel path>.json
        rel = p.relative_to('data')
        out = Path('data') / 'json' / rel
        out = out.with_suffix('.json')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Re-parse complete')


if __name__ == '__main__':
    main()
