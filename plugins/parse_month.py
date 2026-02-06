# parse_month.py
import sys
import os
from pathlib import Path
from parser import parse

# ---- CRITICAL FIX: absolute data root ----
DATA_ROOT = Path(os.environ.get("AMBER_DATA_ROOT", "/opt/chromadb/data/data"))

HTML_ROOT = DATA_ROOT / "html"
JSON_ROOT = DATA_ROOT / "json"


def html_to_json_path(month: str, html_path: Path) -> Path:
    rel = html_path.relative_to(HTML_ROOT / month)
    return (JSON_ROOT / month / rel).with_suffix(".json")


def main(month: str):
    html_dir = HTML_ROOT / month
    json_dir = JSON_ROOT / month
    json_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(html_dir.glob("*.html"))
    print(f"[PARSE] Month {month}: found {len(html_files)} HTML files in {html_dir}")

    ok = skip = err = 0
    for html_path in html_files:
        json_path = html_to_json_path(month, html_path)

        if json_path.exists():
            skip += 1
            continue

        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            parse(html_path, json_path)
            ok += 1
        except Exception as e:
            err += 1
            print(f"[ERR] {html_path.name}: {e}")

    print(f"[PARSE DONE] ok={ok} skip={skip} err={err}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python parse_month.py YYYYMM")
        raise SystemExit(2)
    main(sys.argv[1])
