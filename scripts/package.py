"""Zip the current Git working directory, respecting Git ignore rules except for .env.

Windows:       python scripts/package.py
Linux / macOS: python3 scripts/package.py
Custom name:   python scripts/package.py --output release.zip

Requires Git on PATH and a working tree containing the current directory.
Include .env files, .gitignore files, modified files, and non-ignored untracked files.
Exclude .git metadata and this invocation's output and temporary archive.
Nested repositories such as arc-bench use their own Git ignore rules.
Symbolic links are stored as links without traversing their targets.
"""

import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import zipfile
import json
import re
import tomllib


def ignored_names(directory: Path, paths: list[Path]) -> set[str]:
    """Ask Git to apply ignore rules, including to already tracked files."""
    names = b"\0".join(os.fsencode(path.name) for path in paths) + b"\0"
    result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=directory, input=names, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in (0, 1):
        raise OSError(result.stderr.decode("utf-8", errors="replace").strip())
    return {os.fsdecode(name) for name in result.stdout.split(b"\0") if name}


def package_directory(root: Path, output: Path) -> int:
    """Archive non-ignored entries and .env, replacing the output only on success."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp",
            dir=output.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)

    excluded = {output, temporary_path}
    entries = 0
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED,
                compresslevel=6, allowZip64=True, strict_timestamps=False) as archive:
            pending = [root]
            while pending:
                directory = pending.pop()
                paths = [path for path in sorted(directory.iterdir())
                    if path.name != ".git" and path not in excluded]
                if not paths:
                    continue
                ignored = ignored_names(directory, paths)
                for path in paths:
                    if path.name in ignored and path.name != ".env":
                        continue
                    relative = path.relative_to(root).as_posix()
                    if path.is_symlink():
                        entry = zipfile.ZipInfo(relative)
                        entry.create_system = 3
                        entry.external_attr = path.lstat().st_mode << 16
                        archive.writestr(entry, os.readlink(path))
                    elif path.is_dir():
                        archive.write(path, relative)
                        pending.append(path)
                    elif path.is_file():
                        archive.write(path, relative)
                    else:
                        kind = stat.S_IFMT(path.lstat().st_mode)
                        raise OSError(f"Cannot archive special file {path} (type {kind:#o})")
                    entries += 1
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return entries


def package_arcbench(root: Path, output: Path) -> int:
    """Package current agent sources with checked dependencies and no local API keys."""
    from dotenv import dotenv_values

    root, output = root.resolve(), output.resolve()
    declared = set(tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8-sig'))['project']['dependencies'])
    installed = {line.strip() for line in (root / 'requirements.txt').read_text(encoding='utf-8-sig').splitlines()
        if line.strip() and not line.lstrip().startswith('#')}
    if declared != installed:
        raise ValueError('requirements.txt and pyproject.toml dependencies differ; '
            f'missing from pip manifest: {sorted(declared - installed)}; '
            f'extra in pip manifest: {sorted(installed - declared)}')

    paths = {root / name for name in ('main.py', 'README.md', 'pyproject.toml', 'requirements.txt',
        'uv.lock', '.env.example', '.gitignore', '.gitattributes', 'principle.md')}
    for directory in ('infrastructure', 'scripts', 'tests', 'assets', 'input', 'profiles'):
        paths.update((root / directory).rglob('*'))
    excluded = {'.git', '__pycache__', '.venv', 'node_modules', 'outputs', 'output', '.vscode'}
    files = {}
    for path in sorted(paths):
        if not path.is_file() or path.is_symlink() or path == output:
            continue
        if not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root)
        if any(part in excluded or (part.startswith('.env') and part != '.env.example') for part in relative.parts):
            continue
        if path.suffix in {'.pyc', '.pyo', '.zip', '.log', '.db'}:
            continue
        if relative.as_posix() == 'scripts/evaluate.py':
            continue  # Development tool; needs benchmarks/, which is not shipped.
        files[relative.as_posix()] = path.read_bytes()

    settings = {**dotenv_values(root / '.env.example'), **dotenv_values(root / '.env')}
    allowed = ('MODEL', 'OPENAI_BASE_URL', 'MODEL_REASONING', 'VISUAL_MODEL', 'VISUAL_BASE_URL',
        'VISUAL_REASONING', 'MAX_OUTPUT_TOKENS')
    # The benchmark runner is a disposable container without a nested sandbox, and it
    # discards the application when the generator exits non-zero.
    environment = ['# Credentials must be supplied through the benchmark environment.', 'OPENAI_API_KEY=',
        'AGENT_SANDBOX=host', 'AGENT_DELIVERY_EXIT=0']
    environment.extend(key + '=' + json.dumps(str(settings[key]), ensure_ascii=False)
        for key in allowed if settings.get(key) is not None)
    files['.env'] = ('\n'.join(environment) + '\n').encode('utf-8')

    # The engine, its profile and the application template: nothing of the removed pipeline.
    required = {'main.py', 'requirements.txt', 'pyproject.toml', 'uv.lock',
        'infrastructure/application_agent.py', 'infrastructure/runtime/loop.py',
        'infrastructure/runtime/config.py', 'infrastructure/verification/driver.py',
        'infrastructure/shared/project/templates/frontend/src/App.tsx',
        'profiles/arcbench-app/config.yaml', 'profiles/arcbench-app/role.md',
        'profiles/arcbench-app/workflow.md'}
    if not required <= files.keys():
        raise ValueError(f'Missing submission sources: {sorted(required - files.keys())}')
    keys = [value.encode() for name, value in dotenv_values(root / '.env').items()
        if name.endswith('API_KEY') and value and len(value) >= 8]
    for name, content in files.items():
        if name.endswith('.py'):
            compile(content, name, 'exec')
            # The engine is ours: the studied reference is never imported or shipped.
            if re.search(rb'^\s*(from|import)\s+lingcore\b', content, re.MULTILINE):
                raise ValueError(f'{name} imports LingCore; the delivered engine must not depend on it')
        if re.fullmatch(r'\d\d_\w+\.py', name):
            raise ValueError(f'{name} belongs to the removed numbered pipeline')
        if any(key in content for key in keys):
            raise ValueError(f'{name} contains an API key from .env; secrets are supplied by the runner')

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.' + output.name, suffix='.tmp', dir=output.parent,
            delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(name, content)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None or any(archive.read(name) != content for name, content in files.items()):
                raise ValueError('Submission archive verification failed')
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--output", type=Path, default=Path("compiler.zip"),
        help="Output archive path (default: compiler.zip)")
    parser.add_argument('--arcbench', action='store_true',
        help='Package agent sources, check pip dependencies, exclude local outputs and API keys')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = args.output.expanduser().resolve()
    print(f"Source: {root}")
    print(f"Archive: {output}")
    try:
        entries = (package_arcbench if args.arcbench else package_directory)(root, output)
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
        parser.exit(1, f"Packaging failed: {error}\n")
    print(f"Created {output} ({entries} entries, {output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
