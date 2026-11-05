"""Summarize Arcbench/compiler log costs without printing model prompts or keys."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re


def analyze(text):
    stages = {}
    current = None
    fields = {'Input': 'input_tokens', 'Cached input': 'cached_input_tokens',
        'Output': 'output_tokens', 'Reasoning': 'reasoning_tokens', 'Round-trip latency': 'model_seconds'}
    usage = re.compile(r'\|\s*(Input|Cached input|Output|Reasoning|Round-trip latency)\s*\|\s*([\d,.]+)')
    for raw in text.splitlines():
        line = re.sub(r'\x1b\[[0-9;]*m', '', raw).replace('│', '|')
        marker = re.search(r'\[(START|DONE)\] Stage (\d+)', line)
        timestamp = re.search(r'\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]', line)
        if marker:
            current = marker[2]
            entry = stages.setdefault(current, dict(calls=0, **{key: 0 for key in fields.values()}))
            if timestamp:
                entry[marker[1].lower()] = timestamp[1]
        if current is None:
            continue
        entry = stages[current]
        if timestamp:
            entry['observed_until'] = timestamp[1]
        match = usage.search(line)
        if match:
            value = match[2].replace(',', '')
            entry[fields[match[1]]] += float(value) if match[1] == 'Round-trip latency' else int(value)
            if match[1] == 'Input':
                entry['calls'] += 1
    for entry in stages.values():
        entry['complete'] = 'done' in entry
        if 'start' in entry and 'observed_until' in entry:
            entry['wall_seconds'] = (datetime.fromisoformat(entry.get('done', entry['observed_until'])) -
                datetime.fromisoformat(entry['start'])).total_seconds()
    totals = {key: round(sum(entry.get(key, 0) for entry in stages.values()), 2)
        for key in ('calls', *fields.values(), 'wall_seconds')}
    return {'totals': totals, 'stages': stages,
        'note': 'Cached input is part of input; reasoning is part of output. No model prices assumed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = analyze(args.log.read_text(encoding='utf-8-sig'))
    result = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding='utf-8')
    print(json.dumps(report['totals'], indent=2))


if __name__ == '__main__':
    main()
