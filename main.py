"""Generate an application from a requirement directory with the application agent.

Exit codes: 0 = application accepted by the host verification, 130 = interrupted,
1 = any other outcome (functional failure, provider or environment problem, budget
exhausted, verification missing), 2 = invalid command line or configuration.
"""

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def parse_args(argv=None):
    """Read public options and validate everything that needs no model call."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('requirement_path', type=Path, nargs='?',
        help='Requirement directory containing requirements.yaml, reference assets and optional tests/')
    parser.add_argument('-o', '--output-dir', type=Path,
        help='Directory of the generated application (a run report is written to .arc/run.json)')
    parser.add_argument('--port', type=int, default=3000,
        help='Default port of the generated application (default: 3000)')
    parser.add_argument('--model-log', '--debug-model-io', dest='model_log', action='store_true',
        help='Print every session event (model text, tool calls and results) while running')
    parser.add_argument('--profile', type=Path, help='Generation profile (default: profiles/arcbench-app/config.yaml)')
    parser.add_argument('--env-file', type=Path,
        help='Settings file (default: .env beside main.py when present); process variables take priority')
    parser.add_argument('--resume', metavar='SESSION_ID', help='Continue a saved session of the same input and profile')
    parser.add_argument('--state-dir', type=Path,
        help='Where session state is kept (default: .agent-state beside the output directory)')
    parser.add_argument('--max-requests', type=int, help='Override the total model request limit of the profile')
    parser.add_argument('--max-seconds', type=int, help='Override the total wall-time limit of the profile')
    parser.add_argument('--sandbox', choices=('auto', 'docker', 'bubblewrap', 'host'),
        help='Execution backend; "host" runs commands without isolation and is only for a disposable machine')
    parser.add_argument('--check-config', action='store_true', help='Validate the profile offline and exit')
    parser.add_argument('--check-environment', action='store_true',
        help='Check host tools, browser and sandbox without a model call and exit')
    parser.add_argument('--probe', action='store_true',
        help='Make up to two paid model requests to verify native tool calls and exit')
    args = parser.parse_args(argv)
    diagnostics = args.check_config or args.check_environment or args.probe
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError('--port must be between 1 and 65535')
        for name in ('max_requests', 'max_seconds'):
            if getattr(args, name) is not None and getattr(args, name) < 1:
                raise ValueError(f'--{name.replace("_", "-")} must be positive')
        if not diagnostics:
            if args.requirement_path is None or args.output_dir is None:
                raise ValueError('A requirement directory and --output-dir are required')
            args.requirement_path = args.requirement_path.expanduser().resolve()
            args.output_dir = args.output_dir.expanduser().resolve()
            if not args.requirement_path.is_dir():
                raise ValueError(f'Input directory does not exist: {args.requirement_path}')
            if not (args.requirement_path / 'requirements.yaml').is_file():
                raise ValueError(f"Missing requirement document: {args.requirement_path / 'requirements.yaml'}")
            if args.output_dir.exists() and not args.output_dir.is_dir():
                raise ValueError(f'Output must be a directory: {args.output_dir}')
            if args.output_dir == args.requirement_path or args.requirement_path in args.output_dir.parents \
                    or args.output_dir in args.requirement_path.parents:
                raise ValueError('Output and input directories must be disjoint')
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.parser = parser
    return args


def deployment_settings(args):
    """Runner-level settings a benchmark cannot pass on the command line.

    AGENT_SANDBOX selects the execution backend; AGENT_DELIVERY_EXIT=0 makes a run
    that produced an unaccepted application exit 0 so that an external evaluator
    still scores it. Process variables take priority over the settings file.
    """
    import os
    from dotenv import dotenv_values
    env_file = args.env_file or (ROOT / '.env' if (ROOT / '.env').is_file() else None)
    values = dict(dotenv_values(env_file, encoding='utf-8-sig', interpolate=False)) if env_file else {}
    values.update(os.environ)
    sandbox = (values.get('AGENT_SANDBOX') or '').strip() or None
    if sandbox not in {None, 'auto', 'docker', 'bubblewrap', 'host'}:
        raise ValueError('AGENT_SANDBOX must be auto, docker, bubblewrap or host')
    lenient = (values.get('AGENT_DELIVERY_EXIT') or '').strip()
    if lenient not in {'', '0'}:
        raise ValueError('AGENT_DELIVERY_EXIT accepts only 0')
    return env_file, sandbox, lenient == '0'


def exit_code(outcome, lenient):
    """Lenient mode: an unaccepted application the agent actually worked on is still
    delivered (exit 0); the real status stays in the report."""
    worked = outcome.budget.get('tool_calls', {}).get('total', 0) > 0
    if lenient and worked and outcome.status != 'interrupted':
        return 0
    return outcome.exit_code


def build_profile(args):
    from infrastructure.runtime.config import DEFAULT_PROFILE, load_profile
    env_file, sandbox, args.lenient_exit = deployment_settings(args)
    args.sandbox = args.sandbox or sandbox
    profile = load_profile(args.profile or DEFAULT_PROFILE, env_file=env_file)
    if args.max_requests:
        profile = replace(profile, max_requests=args.max_requests)
    if args.max_seconds:
        if args.max_seconds <= profile.budget.verification_reserve_seconds:
            raise ValueError('--max-seconds must exceed the verification reserve '
                f'({profile.budget.verification_reserve_seconds}s) of the profile')
        profile = replace(profile, budget=replace(profile.budget, wall_seconds=args.max_seconds))
    if args.sandbox:
        profile = replace(profile, execution=replace(profile.execution, backend=args.sandbox))
    return profile


def progress(agent, detailed):
    """Short progress lines on stderr; persisted events are unaffected."""
    persist = agent.loop.on_event

    def show(kind, data):
        persist(kind, data)
        if detailed:
            print(f'[{kind}] ' + json.dumps(data, ensure_ascii=False, default=str)[:4000], file=sys.stderr, flush=True)
        elif kind == 'tool_started':
            print(f'  tool {data["name"]}', file=sys.stderr, flush=True)
        elif kind in {'error', 'compacted', 'pruned', 'stagnation', 'looking', 'final', 'resumed'}:
            print(f'[{kind}] ' + json.dumps(data, ensure_ascii=False, default=str)[:300], file=sys.stderr, flush=True)
    agent.loop.on_event = show
    persist_sub = agent.tools.event_sink

    def show_sub(kind, data):
        persist_sub(kind, data)
        if kind == 'verification':
            print(f'  [verification] {data.get("text")}', file=sys.stderr, flush=True)
        if data.get('kind') == 'tool_started':
            print(f'  [{data["task"]}] tool {data.get("name")}', file=sys.stderr, flush=True)
        elif data.get('kind') in {'final', 'error'}:
            print(f'  [{data["task"]}] {data["kind"]}', file=sys.stderr, flush=True)
    agent.tools.event_sink = show_sub


async def diagnose(args, profile):
    if args.check_config:
        return {'profile': profile.name, 'tools': profile.tools, 'model': profile.llm.model,
            'api_key': 'set' if profile.llm.api_key else 'missing', 'images': profile.image_mode,
            'execution_backend': profile.execution.backend, 'max_requests': profile.max_requests,
            'budget': vars(profile.budget), 'acceptance': vars(profile.acceptance),
            'provider_capabilities': 'unverified; use --probe'}
    if args.probe:
        from infrastructure.runtime.probe import probe
        return await probe(profile)
    import tempfile
    from infrastructure.application_agent import ApplicationAgent
    from infrastructure.runtime.dependencies import environment_report
    from infrastructure.runtime.model import ScriptedModel
    with tempfile.TemporaryDirectory() as temporary:
        async with ApplicationAgent(Path(temporary) / 'app', profile=profile, model=ScriptedModel([])) as agent:
            try:
                sandbox = await agent.tools.processes.sandbox.check()
            except Exception as error:
                sandbox = {'status': 'unavailable', 'diagnostic': str(error)[:1000]}
    # Playwright's synchronous API cannot run inside the event loop.
    return {**await asyncio.to_thread(environment_report), 'sandbox': sandbox}


async def generate(args, profile):
    from infrastructure.application_agent import ApplicationAgent
    from infrastructure.runtime.execution import EnvironmentUnavailable
    from infrastructure.runtime.persistence import RunStore
    from infrastructure.verification.driver import ENVIRONMENT_ERROR, Outcome
    async with ApplicationAgent(args.output_dir, profile=profile, input_dir=args.requirement_path, port=args.port,
            state_root=args.state_dir, resume=args.resume) as agent:
        progress(agent, args.model_log)
        print(f'Session {agent.state.id} | profile {profile.name} | model {profile.llm.model} | '
            f'state {agent.state.state_directory}', file=sys.stderr, flush=True)
        try:
            # Fail before any paid request when commands cannot run at all.
            await agent.tools.processes.sandbox.check()
        except EnvironmentUnavailable as error:
            outcome = Outcome(ENVIRONMENT_ERROR, f'execution backend unavailable: {error}'[:1500],
                budget=agent.loop.budget.report())
            agent.record_outcome(outcome)
        else:
            outcome = await agent.generate()
        report = {**outcome.to_dict(), 'session_id': agent.state.id, 'profile': profile.name,
            'model': profile.llm.model, 'checkpoints': agent.checkpoints,
            'verifications': agent.state.verifications,
            'state_directory': str(agent.state.state_directory),
            'resume': f'--resume {agent.state.id}' if outcome.status != 'accepted' else None}
        RunStore(args.output_dir / '.arc', (profile.llm.api_key, profile.vision.api_key)).write_json('run.json', report)
    return outcome, report


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    args = parse_args(argv)
    from infrastructure.runtime.persistence import ResumeError
    try:
        profile = build_profile(args)
        if args.check_config or args.check_environment or args.probe:
            print(json.dumps(asyncio.run(diagnose(args, profile)), ensure_ascii=False, default=str))
            return
        if not profile.llm.api_key:
            raise ValueError('OPENAI_API_KEY is not set (process environment or the settings file)')
        outcome, report = asyncio.run(generate(args, profile))
    except KeyboardInterrupt:
        print('Generation interrupted; completed file writes are retained.', file=sys.stderr)
        raise SystemExit(130)
    except (ResumeError, ValueError, OSError) as error:
        # Configuration problems are reported before any costly call.
        print(f'Cannot start generation: {error}', file=sys.stderr)
        raise SystemExit(2)
    verification = report.get('verification') or {}
    print(f'Application status: {outcome.status}'
        + (f' | cause: {outcome.cause}' if outcome.cause else '')
        + (f' | last verification: {verification.get("stage")} {verification.get("status")}' if verification else '')
        + f' | requests: {outcome.budget.get("requests", {}).get("total")}'
        + f' | report: {args.output_dir / ".arc" / "run.json"}', file=sys.stderr)
    # One line a benchmark log keeps even when the report file is not retrievable.
    try:
        from scripts.analyze_run import decompose, one_line
        print('Run breakdown: ' + one_line(decompose(report)), file=sys.stderr)
    except Exception as error:  # A reporting convenience never changes the outcome of a run.
        print(f'Run breakdown unavailable: {error}', file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, default=str))
    raise SystemExit(exit_code(outcome, args.lenient_exit))


if __name__ == '__main__':
    main()
