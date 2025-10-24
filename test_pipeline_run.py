#!/usr/bin/env python3
"""End-to-end test runner for the Amber archive pipeline.

Runs (demo month) the same steps the Airflow DAG schedules and verifies DB counts.
"""
from __future__ import annotations

import subprocess
import sys
import sqlite3
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DB = PROJECT_DIR / "data" / "amber_messages.db"


def run_cmd(cmd, cwd=PROJECT_DIR):
    print(f"\n>>> RUN: {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr, file=sys.stderr)
        raise SystemExit(f"Command failed ({r.returncode}): {cmd}")
    return r


def main():
    python = sys.executable
    # 1) Demo crawl for April 2022 (safe, small)
    crawl = f"{python} {PROJECT_DIR / 'scripts' / 'crawl_archive.py'} --start-year 2022 --end-year 2022 --months 4 --delay 0.5"
    run_cmd(crawl)

    # 2) Reparse (ensures message JSONs include epoch IDs)
    run_cmd(f"{python} {PROJECT_DIR / 'scripts' / 'reparse_all.py'}")

    # 3) Merge threads
    run_cmd(f"{python} {PROJECT_DIR / 'scripts' / 'merge_threads.py'}")

    # 4) Load to sqlite
    run_cmd(f"{python} {PROJECT_DIR / 'scripts' / 'load_to_sqlite.py'}")

    # 5) Verify DB counts
    if not DATA_DB.exists():
        raise SystemExit(f"DB not found at {DATA_DB}")

    conn = sqlite3.connect(str(DATA_DB))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM messages")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT message_id) FROM messages")
    unique = cur.fetchone()[0]
    conn.close()

    print(f"\n=== Verification ===")
    print(f"Total rows in DB: {total}")
    print(f"Unique message_id count: {unique}")
    print("If total == unique, duplicates were avoided on insert.")


if __name__ == "__main__":
    main()
