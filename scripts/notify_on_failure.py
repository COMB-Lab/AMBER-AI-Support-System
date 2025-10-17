#!/usr/bin/env python3
"""Simple failure notifier used by Airflow DAG.

This is a placeholder that logs to a local failures file. You can extend
it to send email or Slack notifications, using secure credentials.
"""
import json
import os
from datetime import datetime


def notify_on_failure(context: dict):
    project = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    out = os.path.join(project, 'airflow_failure_notifications.log')
    msg = {
        'time': datetime.utcnow().isoformat(),
        'dag': context.get('dag').dag_id if context.get('dag') else None,
        'task': context.get('task_instance').task_id if context.get('task_instance') else None,
        'execution_date': str(context.get('execution_date')),
        'exception': str(context.get('exception')),
    }
    with open(out, 'a', encoding='utf-8') as f:
        f.write(json.dumps(msg, ensure_ascii=False) + '\n')
    print('Notified failure:', msg)


if __name__ == '__main__':
    # simple CLI test
    notify_on_failure({})
