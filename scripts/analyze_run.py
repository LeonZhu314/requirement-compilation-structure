"""Decompose one or several runs: where the requests, tokens and time went.

    python scripts/analyze_run.py outputs/demo                 # a generated application (reads .arc/run.json)
    python scripts/analyze_run.py run-a.json run-b.json        # several reports, side by side
    python scripts/analyze_run.py outputs/demo --json

Reads the report written by main.py. For a report produced before timings were
recorded, tool and model seconds are rebuilt from `events.jsonl` when the session
state directory is still on this machine; otherwise those values stay unknown.
No model request is made.
"""

import argparse
import json
from pathlib import Path
import sys


def load(path):
    path = Path(path)
    if path.is_dir():
        path = path / '.arc/run.json'
    return json.loads(path.read_text(encoding='utf-8'))


def timing_from_events(state_directory):
    """Model wait and tool seconds rebuilt from event timestamps (older reports)."""
    try:
        lines = (Path(state_directory) / 'events.jsonl').read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue  # An interrupted write leaves at most one incomplete line.
    started, tools, model, previous = {}, {}, 0.0, None
    for event in events:
        kind, data, moment = event.get('kind'), event.get('data') or {}, event.get('time')
        if moment is None:
            continue
        if kind == 'tool_started':
            started[data.get('call_id')] = (data.get('name'), moment)
        elif kind == 'tool_finished' and data.get('call_id') in started:
            name, begin = started.pop(data['call_id'])
            entry = tools.setdefault(name, {'calls': 0, 'seconds': 0.0})
            entry['calls'] += 1
            entry['seconds'] = round(entry['seconds'] + moment - begin, 1)
        elif kind == 'usage' and not data.get('source') and previous is not None:
            model += moment - previous      # A main request ends with its usage event.
        previous = moment
    return {'model_seconds': round(model, 1), 'tools_seconds': round(sum(t['seconds'] for t in tools.values()), 1),
        'verification_seconds': None, 'other_seconds': None, 'verification': {}, 'tools': tools,
        'source': 'events.jsonl'}


def decompose(report):
    """The facts of one run, unknown values left as None."""
    budget = report.get('budget') or {}
    tokens, requests = budget.get('reported_tokens') or {}, budget.get('requests') or {}
    timing = budget.get('timing') or timing_from_events(report.get('state_directory') or '') or {}
    rounds = report.get('verifications') or []
    failed = [r for r in rounds if r.get('status') not in {'passed', 'candidate'}]
    return {'status': report.get('status'), 'cause': report.get('cause'), 'model': report.get('model'),
        'wall_seconds': budget.get('elapsed_seconds'),
        'requests': requests.get('total'),
        'requests_by_kind': {kind: count for kind, count in requests.items() if kind not in {'total', 'limit'} and count},
        'tool_calls': (budget.get('tool_calls') or {}).get('total'),
        'tool_calls_per_request': round(budget['tool_calls']['total'] / requests['main'], 2)
            if requests.get('main') and budget.get('tool_calls') else None,
        'input_tokens': tokens.get('input'), 'output_tokens': tokens.get('output'),
        'cached_input_tokens': tokens.get('cached_input'), 'cached_input_ratio': tokens.get('cached_input_ratio'),
        'reasoning_tokens': tokens.get('reasoning_output'),
        'output_tokens_per_model_second': round(tokens['output'] / timing['model_seconds'], 1)
            if tokens.get('output') and timing.get('model_seconds') else None,
        'total_tokens': tokens.get('total'), 'requests_without_usage': tokens.get('requests_without_usage'),
        'model_seconds': timing.get('model_seconds'), 'tools_seconds': timing.get('tools_seconds'),
        'verification_seconds': timing.get('verification_seconds'), 'other_seconds': timing.get('other_seconds'),
        'verification_stages': timing.get('verification') or {}, 'tools': timing.get('tools') or {},
        'timing_source': timing.get('source', 'report' if timing else None),
        'verification_rounds': report.get('verification_rounds', len(rounds) or None),
        'failed_verification_rounds': len(failed) if rounds else None,
        'rounds': [{'round': r.get('round'), 'clean': r.get('clean_state'), 'status': r.get('status'),
            'stage': r.get('stage'), 'seconds': r.get('seconds'), 'at': r.get('elapsed_seconds')} for r in rounds],
        'compactions': budget.get('compactions'), 'context_pruning': budget.get('context_pruning'),
        'stagnation_notices': budget.get('stagnation_notices')}


def show(value, unit=''):
    if value is None:
        return 'unknown'
    return (f'{value:,}'.replace(',', ' ') if type(value) in (int, float) else str(value)) + unit


def one_line(facts):
    cached = f' ({round(facts["cached_input_ratio"] * 100)}% cached)' if facts['cached_input_ratio'] is not None else ''
    stages = ', '.join(f'{name} {seconds:.0f}' for name, seconds in facts['verification_stages'].items() if seconds >= 1)
    return (f'requests {show(facts["requests"])} | tool calls {show(facts["tool_calls"])} | '
        f'tokens in {show(facts["input_tokens"])}{cached} out {show(facts["output_tokens"])}'
        + (f' (reasoning {show(facts["reasoning_tokens"])})' if facts['reasoning_tokens'] is not None else '')
        + (f', {facts["output_tokens_per_model_second"]} tok/s' if facts['output_tokens_per_model_second'] else '') + ' | '
        f'wall {show(facts["wall_seconds"], "s")} = model {show(facts["model_seconds"], "s")} + tools '
        f'{show(facts["tools_seconds"], "s")} + verification {show(facts["verification_seconds"], "s")}'
        + (f' ({stages})' if stages else '') + f' + other {show(facts["other_seconds"], "s")} | '
        f'verification rounds {show(facts["verification_rounds"])}, failed {show(facts["failed_verification_rounds"])}')


def share(part, whole):
    return f' ({part / whole:.0%})' if part is not None and whole else ''


def render(name, facts):
    wall = facts['wall_seconds']
    lines = [f'== {name}', f'status              {facts["status"]}' + (f' ({facts["cause"]})' if facts['cause'] else ''),
        f'model               {facts["model"]}', f'wall time           {show(wall, " s")}',
        f'  model wait        {show(facts["model_seconds"], " s")}{share(facts["model_seconds"], wall)}',
        f'  tools             {show(facts["tools_seconds"], " s")}{share(facts["tools_seconds"], wall)}',
        f'  verification      {show(facts["verification_seconds"], " s")}{share(facts["verification_seconds"], wall)}']
    lines += [f'    {stage:<16}{show(seconds, " s")}' for stage, seconds in facts['verification_stages'].items()]
    lines += [f'  other             {show(facts["other_seconds"], " s")}{share(facts["other_seconds"], wall)}',
        f'requests            {show(facts["requests"])}  {facts["requests_by_kind"] or ""}',
        f'tool calls          {show(facts["tool_calls"])}  (per main request: {show(facts["tool_calls_per_request"])})',
        f'input tokens        {show(facts["input_tokens"])}  cached: {show(facts["cached_input_tokens"])}'
            + (f' ({facts["cached_input_ratio"]:.0%})' if facts['cached_input_ratio'] is not None else ''),
        f'output tokens       {show(facts["output_tokens"])}',
        f'verification rounds {show(facts["verification_rounds"])}  failed: {show(facts["failed_verification_rounds"])}']
    lines += [f'  round {r["round"]} {"clean" if r["clean"] else "incremental":<11} {r["status"]:<18} last stage {r["stage"]}'
        f'  {show(r["seconds"], " s")}  at {show(r["at"], " s")}' for r in facts['rounds']]
    if facts['tools']:
        lines.append('tools by time' + (' (from events.jsonl)' if facts['timing_source'] == 'events.jsonl' else ''))
        lines += [f'  {tool:<22}{entry["calls"]:>4} calls {entry["seconds"]:>8.1f} s'
            for tool, entry in sorted(facts['tools'].items(), key=lambda item: -item[1]['seconds'])[:12]]
    pruning = facts['context_pruning'] or {}
    lines.append(f'context             compactions {show(facts["compactions"])}, pruned observations '
        f'{show(pruning.get("observations"))} ({show(pruning.get("bytes"))} bytes)')
    return '\n'.join(lines)


COMPARED = ('status', 'wall_seconds', 'model_seconds', 'tools_seconds', 'verification_seconds', 'requests', 'tool_calls',
    'tool_calls_per_request', 'input_tokens', 'cached_input_ratio', 'output_tokens', 'verification_rounds',
    'failed_verification_rounds')


def compare(named):
    width = max(len(name) for name, _ in named) + 2
    lines = ['== comparison', f'{"":<28}' + ''.join(f'{name:>{max(width, 14)}}' for name, _ in named)]
    for key in COMPARED:
        lines.append(f'{key:<28}' + ''.join(f'{show(facts[key]):>{max(width, 14)}}' for _, facts in named))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('runs', nargs='+', type=Path, help='run.json files or generated application directories')
    parser.add_argument('--json', action='store_true', help='Print the facts as JSON')
    args = parser.parse_args(argv)
    try:
        named = [(path.parent.parent.name if path.name == 'run.json' else path.name, decompose(load(path)))
            for path in args.runs]
    except (OSError, ValueError) as error:
        parser.exit(2, f'analyze_run: {error}\n')
    if args.json:
        print(json.dumps({name: facts for name, facts in named}, indent=2, ensure_ascii=False))
        return 0
    print('\n\n'.join(render(name, facts) for name, facts in named))
    if len(named) > 1:
        print('\n' + compare(named))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
