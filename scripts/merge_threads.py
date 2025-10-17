#!/usr/bin/env python3
"""Merge per-message JSON into per-thread JSON files and link replies.

Heuristics used:
- Normalize subjects by removing leading "Re:", "Fwd:", mailing list tags like "[AMBER]", and extra whitespace.
- Group messages by normalized subject.
- Sort messages in each group by parsed date (fallback to file order).
- For messages whose subject begins with a reply prefix but are alone in their group,
  search for an earlier message with the same normalized subject across the dataset
  and attach it as the parent (in_reply_to).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def normalize_subject(s: str) -> str:
    if not s:
        return ''
    s = s.strip()
    # remove mailing list tag like [AMBER]
    s = re.sub(r'^\[.*?\]\s*', '', s)
    # remove leading Re:, Fwd:, etc (multiple times)
    s = re.sub(r'^(re|fw|fwd)[:\s]+', '', s, flags=re.I)
    # collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def parse_date_iso(dt_iso: str) -> Optional[datetime]:
    if not dt_iso:
        return None
    try:
        return datetime.fromisoformat(dt_iso)
    except Exception:
        # try parsing common email date formats
        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(dt_iso)
        except Exception:
            return None


def load_messages(root: Path) -> List[dict]:
    msgs = []
    for p in root.rglob('*.json'):
        # skip thread files directories
        if 'threads' in p.parts:
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        data['_path'] = p
        msgs.append(data)
    return msgs


def build_groups(msgs: List[dict]) -> Dict[str, List[dict]]:
    groups: Dict[str, List[dict]] = {}
    for m in msgs:
        subj = m.get('subject', '')
        norm = normalize_subject(subj).lower()
        groups.setdefault(norm, []).append(m)
    return groups


def find_parent_for_reply(msg: dict, candidates: List[dict]) -> Optional[str]:
    """Find an earlier message id in candidates to be the parent of msg."""
    # use date ordering: pick the latest message with date < msg.date
    msg_dt = parse_date_iso(msg.get('date_iso') or msg.get('date_utc') or msg.get('date_raw') or '')
    candidates_sorted = []
    for c in candidates:
        if c.get('message_id') == msg.get('message_id'):
            continue
        cdt = parse_date_iso(c.get('date_iso') or c.get('date_utc') or c.get('date_raw') or '')
        candidates_sorted.append((cdt, c))
    # filter only those with earlier date
    earlier = [(cdt, c) for cdt, c in candidates_sorted if cdt and msg_dt and cdt < msg_dt]
    if earlier:
        # pick the most recent earlier
        earlier.sort(key=lambda x: x[0], reverse=True)
        return earlier[0][1].get('message_id')
    # fallback: if no dates, pick first candidate that is not itself
    for _, c in candidates_sorted:
        if c.get('message_id') != msg.get('message_id'):
            return c.get('message_id')
    return None


def merge_and_write(groups: Dict[str, List[dict]], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for norm_subj, messages in groups.items():
        # sort messages by date
        messages.sort(key=lambda m: (parse_date_iso(m.get('date_iso') or m.get('date_utc') or m.get('date_raw') or '') or datetime.min.replace(tzinfo=timezone.utc)))

        # If a group has single message but original subject started with Re:, try to link
        if len(messages) == 1:
            m = messages[0]
            orig_subj = m.get('subject', '')
            if re.match(r'^(re|fw|fwd)[:\s]', orig_subj, flags=re.I):
                # Normalize the subject after stripping the leading Re/Fwd
                stripped = re.sub(r'^(re|fw|fwd)[:\s]+', '', orig_subj, flags=re.I)
                stripped_norm = normalize_subject(stripped).lower()
                # Collect candidates from groups whose normalized key matches stripped_norm
                candidates = []
                for gnorm, glist in groups.items():
                    if gnorm == stripped_norm:
                        candidates.extend([x for x in glist if x is not m])
                parent_id = find_parent_for_reply(m, candidates)
                if parent_id:
                    m['in_reply_to'] = parent_id

        # Determine thread root: earliest message by epoch (message_epoch) or by parsed date
        def msg_epoch_val(m):
            # prefer explicit message_epoch when present
            me = m.get('message_epoch')
            if isinstance(me, int):
                return me
            # fallback to parsing date_iso/date_utc/date_raw
            dt = parse_date_iso(m.get('date_iso') or m.get('date_utc') or m.get('date_raw') or '')
            if dt:
                return int(dt.replace(tzinfo=timezone.utc).timestamp())
            return None

        root_candidate = None
        root_epoch = None
        for m in messages:
            val = msg_epoch_val(m)
            if val is None:
                continue
            if root_epoch is None or val < root_epoch:
                root_epoch = val
                root_candidate = m

        # If no epoch could be determined, fallback to hashing normalized subject
        if root_epoch is None:
            thread_id = abs(hash(norm_subj)) % (10 ** 12)
        else:
            thread_id = int(root_epoch)

        out = {
            'thread_id': thread_id,
            'subject': messages[0].get('subject', ''),
            'messages': []
        }

        for m in messages:
            entry = {
                'message_id': m.get('message_epoch') if isinstance(m.get('message_epoch'), int) else m.get('message_id'),
                'author': m.get('author_name') or m.get('author') or '',
                'date_raw': m.get('date_raw') or m.get('date_iso') or '',
                'body': m.get('body_text') or m.get('body') or '',
                'url': m.get('url') or ''
            }
            # set in_reply_to to thread root for replies (any message that is not the root)
            mid_val = entry['message_id']
            try:
                mid_int = int(mid_val)
            except Exception:
                mid_int = None
            if root_epoch is not None and mid_int is not None and mid_int != thread_id:
                entry['in_reply_to'] = thread_id
            # preserve explicit in_reply_to if already set
            if m.get('in_reply_to'):
                entry['in_reply_to'] = m.get('in_reply_to')
            out['messages'].append(entry)

        safe = re.sub(r'[^A-Za-z0-9\-_. ]+', '_', out['subject'])[:200] or str(thread_id)
        out_path = out_dir / (safe + '.json')
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    root = Path('data') / 'json'
    msgs = load_messages(root)
    print(f'Loaded {len(msgs)} message JSON files')
    groups = build_groups(msgs)
    print(f'Built {len(groups)} subject groups')
    out_dir = Path('data') / 'threads_merged'
    merge_and_write(groups, out_dir)
    print(f'Wrote merged thread JSON files to {out_dir}')


if __name__ == '__main__':
    main()
