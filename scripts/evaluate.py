"""Reproducible paired comparisons of generation variants (migration step 23).

    python scripts/evaluate.py plan     --variants benchmarks/variants.json --cases input --repeats 2
    python scripts/evaluate.py run      --variants benchmarks/variants.json --cases input --repeats 2 --records runs.jsonl --work outputs/eval
    python scripts/evaluate.py external --records runs.jsonl --run-id ID --passed true --score 0.8
    python scripts/evaluate.py report   --records runs.jsonl --criteria benchmarks/criteria.json --baseline baseline --candidate agent

`run` makes real, paid model requests: one generation per variant, case and repeat.
Every run gets a new workspace, state directory and database; failed, interrupted
and timed-out runs are recorded like successful ones. A local acceptance is never an
external success: `external_passed` stays null until an external result is attached.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.summarize import summarize  # noqa: E402
from scripts.analyze_run import decompose  # noqa: E402
from infrastructure.utils.processes import process_options, stop_process  # noqa: E402

STATUS = {'accepted': 'completed', 'failed': 'failed', 'interrupted': 'interrupted', 'budget_exceeded': 'budget_exceeded',
    'provider_error': 'provider_error', 'environment_error': 'environment_error',
    'verification_missing': 'verification_missing'}


def tree_sha256(directory, suffixes=None):
    entries = {}
    for path in sorted(Path(directory).rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and 'node_modules' not in path.parts \
                and (suffixes is None or path.suffix in suffixes):
            entries[path.relative_to(directory).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def source_sha256(root):
    """The sources that produce a result: entry point, engine and profiles."""
    root = Path(root)
    parts = [sha256((root / 'main.py').read_bytes()).hexdigest() if (root / 'main.py').is_file() else '']
    parts += [tree_sha256(root / name) for name in ('infrastructure', 'profiles') if (root / name).is_dir()]
    return sha256(''.join(parts).encode()).hexdigest()


def load_variants(path):
    variants = json.loads(Path(path).read_text(encoding='utf-8'))
    seen = set()
    for variant in variants:
        if set(variant) - {'id', 'root', 'profile', 'args', 'description'} or not variant.get('id') or variant['id'] in seen:
            raise ValueError('A variant has a unique id and optional root, profile, args, description')
        seen.add(variant['id'])
    return variants


def load_cases(paths):
    """A case is a directory holding requirements.yaml; a directory of cases (such as
    benchmarks/cases or one of its splits) stands for every case below it."""
    cases = []
    for path in paths:
        path = Path(path).resolve()
        found = [path] if (path / 'requirements.yaml').is_file() else \
            sorted(item.parent for item in path.rglob('requirements.yaml')) if path.is_dir() else []
        if not found:
            raise ValueError(f'Not a case directory (requirements.yaml missing): {path}')
        cases += [{'id': item.name, 'path': item, 'sha256': tree_sha256(item)} for item in found]
    if len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Case directory names must be distinct')
    return cases


def schedule(variants, cases, repeats):
    """Same cases for every variant; the variant order alternates between repeats."""
    plan = []
    for repeat in range(1, repeats + 1):
        ordered = variants if repeat % 2 else list(reversed(variants))
        for case in cases:
            for variant in ordered:
                plan.append((variant, case, repeat))
    return plan


def command(variant, case, output, state, port):
    root = Path(variant.get('root') or ROOT).resolve()
    argv = [sys.executable, str(root / 'main.py'), str(case['path']), '--output-dir', str(output), '--port', str(port)]
    if variant.get('profile'):
        argv += ['--profile', str((root / variant['profile']).resolve()), '--state-dir', str(state)]
    elif (root / 'infrastructure/application_agent.py').is_file():
        argv += ['--state-dir', str(state)]
    return root, argv + list(variant.get('args', []))


def usage_totals(state_directory):
    """Input and output totals only: cached tokens are part of the input and reasoning
    may be part of the output, so the subtotals are reported but never added again."""
    try:
        session = json.loads((Path(state_directory) / 'session.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    usage = session.get('usage', [])
    reported = [u for u in usage if u.get('input_tokens') is not None or u.get('output_tokens') is not None]
    total = lambda key: sum(u.get(key) or 0 for u in reported)
    return {'input_tokens': total('input_tokens') if reported else None,
        'output_tokens': total('output_tokens') if reported else None,
        'cached_input_tokens': total('cached_input_tokens'), 'reasoning_tokens': total('reasoning_tokens'),
        'requests': len(usage), 'requests_without_usage': len(usage) - len(reported),
        'known_retries': total('retries'), 'verifications': session.get('verifications', []),
        'first_event': None}


def timings(verifications, events_path):
    """Seconds to the first usable application and from its first failure to acceptance."""
    try:
        first = json.loads(Path(events_path).read_text(encoding='utf-8').splitlines()[0])['time']
    except (OSError, ValueError, IndexError, KeyError):
        return None, None
    # Older saved states have no timestamps: those timings stay unknown.
    verifications = [v for v in verifications if v.get('finished_at') is not None]
    usable = next((v['finished_at'] - first for v in verifications if v.get('usable')), None)
    failed = next((v['finished_at'] for v in verifications if v['status'] not in {'passed', 'candidate'}), None)
    accepted = next((v['finished_at'] for v in verifications if v['status'] == 'passed' and v['clean_state']), None)
    repair = accepted - failed if failed is not None and accepted is not None and accepted > failed else None
    return (round(usable, 1) if usable is not None else None), (round(repair, 1) if repair is not None else None)


def record(variant, case, repeat, output, root, wall, returncode, timed_out, prices):
    """One complete run sheet; unknown values stay null."""
    sheet = {'run_id': uuid4().hex, 'variant': variant['id'], 'case_id': case['id'], 'repeat': repeat,
        'source_sha256': source_sha256(root), 'input_sha256': case['sha256'], 'profile_sha256': None,
        'model': None, 'reasoning': None, 'budget': None,
        'environment': {'platform': sys.platform, 'python': sys.version.split()[0]},
        'status': 'timed_out' if timed_out else 'interrupted' if returncode == 130 else 'failed',
        'returncode': returncode, 'local_accepted': False, 'external_passed': None, 'external_score': None,
        'wall_seconds': round(wall, 1), 'input_tokens': None, 'output_tokens': None, 'cached_input_tokens': None,
        'reasoning_tokens': None, 'requests': None, 'requests_without_usage': None, 'known_retries': None,
        'seconds_to_first_usable': None, 'repair_seconds_after_first_failure': None, 'verification_rounds': None,
        'failed_verification_rounds': None, 'model_seconds': None, 'tools_seconds': None,
        'verification_seconds': None, 'tool_calls': None,
        'cost': None, 'cause': None, 'artifacts': [{'kind': 'application', 'path': str(output)}]}
    report_path = Path(output) / '.arc/run.json'
    legacy_path = Path(output) / '.arc/compilation.json'
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if not timed_out:
            sheet['status'] = STATUS.get(report['status'], 'failed')
        sheet.update(local_accepted=report['status'] == 'accepted', model=report.get('model'), cause=report.get('cause'),
            verification_rounds=report.get('verification_rounds'), budget=report.get('budget'))
        facts = decompose(report)                               # Where the time of this run went.
        sheet.update({key: facts[key] for key in ('failed_verification_rounds', 'model_seconds', 'tools_seconds',
            'verification_seconds', 'tool_calls')})
        try:
            summary = json.loads((Path(report['state_directory']) / 'run-summary.json').read_text(encoding='utf-8'))
            sheet.update(profile_sha256=summary['fingerprints']['profile'], reasoning=summary.get('reasoning'))
        except (OSError, ValueError, KeyError):
            pass
        sheet['artifacts'].append({'kind': 'report', 'path': str(report_path), 'sha256': sha256(report_path.read_bytes()).hexdigest()})
        totals = usage_totals(report.get('state_directory', ''))
        if totals:
            verifications = totals.pop('verifications')
            totals.pop('first_event')
            sheet.update(totals)
            sheet['seconds_to_first_usable'], sheet['repair_seconds_after_first_failure'] = timings(
                verifications, Path(report['state_directory']) / 'events.jsonl')
            sheet['artifacts'].append({'kind': 'state', 'path': report['state_directory']})
    elif legacy_path.is_file():
        # The frozen pipeline reports its own status; its token usage is not in this file.
        legacy = json.loads(legacy_path.read_text(encoding='utf-8'))
        if not timed_out:
            sheet['status'] = 'completed' if returncode == 0 else 'failed'
        sheet.update(local_accepted=returncode == 0, cause=str(legacy.get('status')))
        sheet['artifacts'].append({'kind': 'report', 'path': str(legacy_path), 'sha256': sha256(legacy_path.read_bytes()).hexdigest()})
    if prices and sheet['input_tokens'] is not None and sheet['output_tokens'] is not None \
            and not sheet['requests_without_usage']:
        sheet['cost'] = round((sheet['input_tokens'] * prices[0] + sheet['output_tokens'] * prices[1]) / 1e6, 4)
    return sheet


def execute(plan, work, records, timeout, prices, port, runner=subprocess.Popen, stop=stop_process):
    work, records = Path(work).resolve(), Path(records)
    records.parent.mkdir(parents=True, exist_ok=True)
    sheets = []
    for variant, case, repeat in plan:
        identity = f'{variant["id"]}-{case["id"]}-r{repeat}-{uuid4().hex[:8]}'
        output, state = work / identity / 'app', work / identity / 'state'
        output.parent.mkdir(parents=True)                      # New workspace, state and database per run.
        root, argv = command(variant, case, output, state, port)
        print(f'[run] {identity}', file=sys.stderr, flush=True)
        started, timed_out, returncode = time.monotonic(), False, None
        with (output.parent / 'console.log').open('wb') as log:
            process = runner(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ), **process_options())
            try:
                returncode = process.wait(timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop(process)            # The whole tree: servers, containers and browsers too.
            except KeyboardInterrupt:
                stop(process)
                returncode = 130
        sheet = record(variant, case, repeat, output, root, time.monotonic() - started, returncode, timed_out, prices)
        sheet['artifacts'].append({'kind': 'console', 'path': str(output.parent / 'console.log')})
        with records.open('a', encoding='utf-8') as stream:      # Written at once: failures are kept too.
            stream.write(json.dumps(sheet, ensure_ascii=False) + '\n')
        sheets.append(sheet)
        if returncode == 130:
            break
    return sheets


def read_records(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def attach_external(path, run_id, passed, score):
    sheets = read_records(path)
    matches = [sheet for sheet in sheets if sheet['run_id'] == run_id]
    if len(matches) != 1:
        raise ValueError(f'Unknown run_id {run_id}')
    if passed and matches[0]['status'] != 'completed':
        raise ValueError('Only a completed run can be an external success')
    matches[0].update(external_passed=passed, external_score=score)
    temporary = Path(str(path) + '.tmp')
    temporary.write_text(''.join(json.dumps(sheet, ensure_ascii=False) + '\n' for sheet in sheets), encoding='utf-8')
    os.replace(temporary, path)


def mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 2) if values else None


def report(sheets, baseline=None, candidate=None, criteria=None):
    """Per-variant totals over ALL runs, paired differences, and a decision against
    criteria fixed before the runs. Unknown values are counted, never assumed."""
    result = {'variants': summarize(sheets)}
    for variant, entry in result['variants'].items():
        runs = [sheet for sheet in sheets if sheet['variant'] == variant]
        entry.update(
            false_local_successes=sum(r['local_accepted'] and r['external_passed'] is False for r in runs),
            locally_accepted=sum(bool(r['local_accepted']) for r in runs),
            mean_external_score=mean([r['external_score'] for r in runs]),
            mean_wall_seconds=mean([r['wall_seconds'] for r in runs]),
            mean_input_tokens=mean([r['input_tokens'] for r in runs]),
            mean_output_tokens=mean([r['output_tokens'] for r in runs]),
            mean_cached_input_tokens=mean([r.get('cached_input_tokens') for r in runs]),
            mean_requests=mean([r.get('requests') for r in runs]),
            mean_tool_calls=mean([r.get('tool_calls') for r in runs]),
            mean_model_seconds=mean([r.get('model_seconds') for r in runs]),
            mean_tools_seconds=mean([r.get('tools_seconds') for r in runs]),
            mean_verification_seconds=mean([r.get('verification_seconds') for r in runs]),
            mean_verification_rounds=mean([r.get('verification_rounds') for r in runs]),
            mean_failed_verification_rounds=mean([r.get('failed_verification_rounds') for r in runs]),
            cases=len({r['case_id'] for r in runs}),
            min_repeats_per_case=min(len({r['repeat'] for r in runs if r['case_id'] == case})
                for case in {r['case_id'] for r in runs}),
            mean_seconds_to_first_usable=mean([r['seconds_to_first_usable'] for r in runs]),
            mean_repair_seconds=mean([r['repair_seconds_after_first_failure'] for r in runs]),
            runs_with_unknown_usage=sum(r['input_tokens'] is None or bool(r['requests_without_usage']) for r in runs),
            known_retries=sum(r['known_retries'] or 0 for r in runs))
    if not (baseline and candidate):
        return result
    index = {(s['variant'], s['case_id'], s['repeat']): s for s in sheets}
    pairs, costlier = [], []
    for (variant, case, repeat), sheet in sorted(index.items()):
        other = index.get((baseline, case, repeat))
        if variant != candidate or other is None:
            continue
        tokens = lambda s: None if s['input_tokens'] is None or s['output_tokens'] is None else s['input_tokens'] + s['output_tokens']
        pair = {'case_id': case, 'repeat': repeat,
            'external': [other['external_passed'], sheet['external_passed']],
            'score': [other['external_score'], sheet['external_score']],
            'status': [other['status'], sheet['status']],
            'wall_seconds': [other['wall_seconds'], sheet['wall_seconds']], 'tokens': [tokens(other), tokens(sheet)]}
        pairs.append(pair)
        if (None not in pair['tokens'] and pair['tokens'][1] > pair['tokens'][0]) or pair['wall_seconds'][1] > pair['wall_seconds'][0]:
            costlier.append(pair)                              # Kept for analysis, not hidden.
    evaluated = [p for p in pairs if None not in p['external']]
    repeats = {}
    for pair in pairs:
        repeats.setdefault(pair['case_id'], set()).add(pair['repeat'])
    comparison = {'baseline': baseline, 'candidate': candidate, 'pairs': pairs, 'evaluated_pairs': len(evaluated),
        'paired_cases': len(repeats), 'min_repeats_per_case': min(map(len, repeats.values())) if repeats else 0,
        'unevaluated_pairs': len(pairs) - len(evaluated), 'candidate_costlier': costlier}
    if evaluated:
        comparison['external_success_delta'] = round(
            (sum(p['external'][1] for p in evaluated) - sum(p['external'][0] for p in evaluated)) / len(evaluated), 3)
    def ratio(key):
        known = [p[key] for p in pairs if None not in p[key] and p[key][0]]
        return round(sum(b for _, b in known) / sum(a for a, _ in known), 3) if known else None
    comparison['token_ratio'], comparison['wall_ratio'] = ratio('tokens'), ratio('wall_seconds')
    if criteria:
        comparison['decision'] = decide(comparison, criteria)
    result['comparison'] = comparison
    return result


def decide(comparison, criteria):
    """`insufficient_evidence` unless the criteria are confirmed and enough pairs were evaluated externally."""
    reasons = []
    if not criteria.get('confirmed'):
        reasons.append('criteria are not confirmed; they must be fixed before the runs')
    if comparison['evaluated_pairs'] < criteria['min_evaluated_pairs']:
        reasons.append(f'{comparison["evaluated_pairs"]} externally evaluated pairs < {criteria["min_evaluated_pairs"]}')
    # One run per case cannot separate a change from the model's own variance, and one
    # case cannot show a change of the success rate.
    if comparison['min_repeats_per_case'] < criteria.get('min_repeats', 2):
        reasons.append(f'{comparison["min_repeats_per_case"]} repeat(s) per case < {criteria.get("min_repeats", 2)}')
    if comparison['paired_cases'] < criteria.get('min_cases', 1):
        reasons.append(f'{comparison["paired_cases"]} paired case(s) < {criteria["min_cases"]}')
    if reasons:
        return {'verdict': 'insufficient_evidence', 'reasons': reasons}
    delta = comparison['external_success_delta']
    if delta < -criteria['max_external_success_loss']:
        return {'verdict': 'reject', 'reasons': [f'external success changed by {delta}']}
    gains = [name for name, key, limit in (('tokens', 'token_ratio', 1 - criteria['min_token_gain']),
        ('time', 'wall_ratio', 1 - criteria['min_time_gain'])) if comparison[key] is not None and comparison[key] <= limit]
    if delta >= criteria['min_external_success_gain'] and delta > 0:
        gains.append('quality')
    return {'verdict': 'adopt' if gains else 'no_useful_gain', 'reasons': gains or ['no gain reached its minimum'],
        'limits': 'Paired local runs; a removed pipeline is not itself evidence of a gain.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='action', required=True)
    for name in ('plan', 'run'):
        sub = commands.add_parser(name)
        sub.add_argument('--variants', type=Path, required=True)
        sub.add_argument('--cases', type=Path, nargs='+', required=True)
        sub.add_argument('--repeats', type=int, default=2,
            help='Runs per variant and case (default 2: the model is not deterministic)')
        sub.add_argument('--port', type=int, default=3000)
    run = commands.choices['run']
    run.add_argument('--records', type=Path, required=True)
    run.add_argument('--work', type=Path, required=True)
    run.add_argument('--timeout', type=int, default=7200, help='Seconds per run before it is recorded as timed_out')
    run.add_argument('--price', type=float, nargs=2, metavar=('INPUT', 'OUTPUT'), help='Price per million tokens')
    run.add_argument('--yes', action='store_true', help='Confirm that paid model requests may be made')
    external = commands.add_parser('external')
    external.add_argument('--records', type=Path, required=True)
    external.add_argument('--run-id', required=True)
    external.add_argument('--passed', choices=('true', 'false'), required=True)
    external.add_argument('--score', type=float)
    rep = commands.add_parser('report')
    rep.add_argument('--records', type=Path, required=True)
    rep.add_argument('--criteria', type=Path)
    rep.add_argument('--baseline')
    rep.add_argument('--candidate')
    args = parser.parse_args(argv)
    try:
        if args.action in {'plan', 'run'}:
            if args.repeats < 1:
                raise ValueError('--repeats must be positive')
            plan = schedule(load_variants(args.variants), load_cases(args.cases), args.repeats)
            if args.action == 'plan' or not args.yes:
                for variant, case, repeat in plan:
                    print(f'{variant["id"]:<24} {case["id"]:<16} repeat {repeat}')
                if args.repeats < 2:
                    print('Warning: one repeat per case cannot separate a change from the variance of the model; '
                        'the report will answer insufficient_evidence.', file=sys.stderr)
                print(f'{len(plan)} generations; each makes paid model requests. '
                    + ('Add --yes to start.' if args.action == 'run' else ''), file=sys.stderr)
                return 0 if args.action == 'plan' else 2
            sheets = execute(plan, args.work, args.records, args.timeout, args.price, args.port)
            print(json.dumps(report(sheets), indent=2))
        elif args.action == 'external':
            attach_external(args.records, args.run_id, args.passed == 'true', args.score)
        else:
            criteria = json.loads(args.criteria.read_text(encoding='utf-8')) if args.criteria else None
            print(json.dumps(report(read_records(args.records), args.baseline, args.candidate, criteria), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(2, f'evaluate: {error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
