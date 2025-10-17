#!/usr/bin/env python3
"""Load merged thread JSON files into a local SQLite database.

This script reads `data/threads_merged/*.json` and inserts messages into a
simple SQLite schema. It avoids duplicates by using message_id as PRIMARY KEY.
"""
import json
import sqlite3
from pathlib import Path


DB_PATH = Path('data') / 'amber_messages.db'


def ensure_schema(conn: sqlite3.Connection):
    conn.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        message_id TEXT PRIMARY KEY,
        thread_id TEXT,
        subject TEXT,
        author TEXT,
        date_raw TEXT,
        body TEXT,
        url TEXT
    )
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_thread ON messages(thread_id)')
    conn.commit()


def load_threads(root: Path):
    files = list(root.glob('*.json'))
    print(f'Found {len(files)} thread files to load')
    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)
    inserted = 0
    skipped = 0
    for p in files:
        data = json.loads(p.read_text(encoding='utf-8'))
        thread_id = str(data.get('thread_id'))
        subject = data.get('subject')
        for m in data.get('messages', []):
            mid = str(m.get('message_id'))
            author = m.get('author')
            date_raw = m.get('date_raw')
            body = m.get('body')
            url = m.get('url')
            try:
                conn.execute('INSERT INTO messages (message_id, thread_id, subject, author, date_raw, body, url) VALUES (?,?,?,?,?,?,?)',
                             (mid, thread_id, subject, author, date_raw, body, url))
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
    conn.commit()
    conn.close()
    print(f'Inserted {inserted}, skipped {skipped}')


def main():
    root = Path('data') / 'threads_merged'
    load_threads(root)


if __name__ == '__main__':
    main()
