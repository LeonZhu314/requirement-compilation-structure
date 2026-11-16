"""Summarize complete run records, keeping failures and unknown costs visible."""

import argparse
import json
from pathlib import Path


def summarize(records):
    groups = {}
    seen = set()
    required = {'run_id', 'variant', 'case_id', 'repeat', 'source_sha256', 'input_sha256',
        'profile_sha256', 'model', 'reasoning', 'budget', 'environment', 'status',
        'external_passed', 'external_score', 'wall_seconds', 'input_tokens', 'output_tokens', 'cost', 'artifacts'}
    statuses = {'completed', 'failed', 'interrupted', 'timed_out', 'budget_exceeded', 'provider_error',
        'environment_error', 'verification_missing'}
    for record in records:
        if required - record.keys():
            raise ValueError(f'Missing run fields: {sorted(required - record.keys())}')
        if record['run_id'] in seen:
            raise ValueError('Duplicate run_id')
        seen.add(record['run_id'])
        if record['status'] not in statuses or record['external_passed'] not in (True, False, None):
            raise ValueError('Invalid run outcome')
        if record['external_passed'] is True and record['status'] != 'completed':
            raise ValueError('Only completed evaluated runs may count as successes')
        for key in ('wall_seconds', 'input_tokens', 'output_tokens', 'cost'):
            v = record[key]
            if v is not None and (type(v) not in (int, float) or v < 0):
                raise ValueError(f'Invalid {key}')
        groups.setdefault(record['variant'], []).append(record)
    results = {}
    for variant, runs in groups.items():
        successes = sum(r['external_passed'] is True for r in runs)
        known_costs = [r['cost'] for r in runs if r['cost'] is not None]
        results[variant] = {'runs': len(runs), 'external_successes': successes,
            'unevaluated': sum(r['external_passed'] is None for r in runs),
            'success_fraction_all_runs': successes / len(runs),
            'statuses': {status: sum(r['status'] == status for r in runs) for status in sorted(statuses)},
            'known_cost_total': sum(known_costs), 'runs_with_unknown_cost': len(runs) - len(known_costs),
            'cost_per_success': sum(known_costs) / successes if successes and len(known_costs) == len(runs) else None}
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize([json.loads(line) for line in args.records.read_text(encoding='utf-8').splitlines()
        if line.strip()]), indent=2))
