# html_to_json_month.py
from __future__ import annotations

import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback

from parser import parse

WORKERS = 6
CHUNK_PRINT = 500

def target_json_path(month: str, html_path: Path) -> Path:
    # html_path is like data/html/YYYYMM/0000.html
    rel = html_path.relative_to(Path("data/html") / month)
    return (Path("data/json") / month / rel).with_suffix(".json")

def parse_one(month: str, html_path_str: str) -> str:
    html_path = Path(html_path_str)
    json_path = target_json_path(month, html_path)

    if json_path.exists():
        return "skip"

    json_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        parse(html_path, json_path)
        return "ok"
    except Exception as e:
        err_path = json_path.with_suffix(".error.txt")
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(
            f"HTML: {html_path}\nJSON: {json_path}\n\n"
            f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        )
        return "error"

def main(month: str):
    input_dir = Path("data/html") / month
    output_dir = Path("data/json") / month
    output_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(input_dir.rglob("*.html"))
    print(f"Found {len(html_files)} HTML files in {input_dir}")

    ok = skip = err = 0
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(parse_one, month, str(p)) for p in html_files]
        for i, f in enumerate(as_completed(futures), start=1):
            status = f.result()
            if status == "ok": ok += 1
            elif status == "skip": skip += 1
            else: err += 1

            if i % CHUNK_PRINT == 0:
                print(f"Progress: {i}/{len(html_files)} | ok={ok} skip={skip} err={err}")

    print(f"Done. ok={ok} skip={skip} err={err}")
    if err:
        print("Check data/json/**.error.txt for failures.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python html_to_json_month.py YYYYMM")
        raise SystemExit(2)
    main(sys.argv[1])
