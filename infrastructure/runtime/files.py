"""File tools and versioned reads, without compiler ownership or whole-file gates."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from infrastructure.utils.paths import check_path_case, relative_path


PROTECTED = ('requirements', 'input', 'tests', 'backend/tests', 'frontend/tests', 'requirements.yaml')
EXCLUDED = {'node_modules', '.git', '.venv', '__pycache__', 'dist', 'build', 'coverage'}
PUBLIC_DOTFILES = {'.gitignore', '.gitattributes'}


def protected(relative, prefixes=PROTECTED):
    folded = relative.casefold()
    return any(folded == p.casefold() or folded.startswith(p.casefold() + '/') for p in prefixes)


def visible(relative):
    return not any(p in EXCLUDED or (p.startswith('.') and p not in PUBLIC_DOTFILES)
        for p in Path(relative).parts)


def safe_path(root, relative, *, directory=False):
    parts = relative_path(relative).parts
    if not visible(relative):
        raise ValueError('Private and generated paths are unavailable')
    check_path_case(root, relative)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
            raise ValueError('Links are not allowed in application paths')
    if not current.resolve().is_relative_to(root.resolve()) or (current.is_dir() and not directory):
        raise ValueError('Expected a file inside the assigned workspace')
    if current.is_file() and current.stat().st_nlink > 1:
        raise ValueError('Hard-linked application files are not allowed')
    return current


def source_files(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        dirs[:] = sorted(d for d in dirs if visible((parent / d).relative_to(root).as_posix())
            and not (parent / d).is_symlink() and not getattr(parent / d, 'is_junction', lambda: False)())
        for name in sorted(files):
            relative = (parent / name).relative_to(root).as_posix()
            if visible(relative):
                try:
                    yield relative, safe_path(root, relative)
                except ValueError:
                    continue


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.agent-write-', delete=False) as f:
        temporary = Path(f.name)
        f.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class WorkspaceFiles:
    def __init__(self, root, artifacts, prefixes=PROTECTED):
        self.root, self.artifacts, self.prefixes = root, artifacts, prefixes
        self.reads = {}

    def path(self, relative, write=False):
        target = safe_path(self.root, relative)
        if write and protected(relative, self.prefixes):
            raise ValueError('WRITE_NOT_ALLOWED: requirements and acceptance tests are protected')
        return target

    def text(self, relative):
        path = self.path(relative)
        if path.stat().st_size > 2_000_000:
            raise ValueError('Text file exceeds 2 MB; use a narrower source or an image tool')
        return path.read_text(encoding='utf-8-sig')

    def read(self, path, start_line=1, end_line=None):
        text = self.text(path)
        digest = sha256(text.encode()).hexdigest()
        lines = text.splitlines(keepends=True)
        end = min(end_line if end_line is not None else start_line + 199, len(lines))
        selected = ''.join(lines[start_line - 1:end])
        identity = self.artifacts.put(selected)
        key = (path, start_line, end)
        unchanged = self.reads.get(key) == digest
        self.reads[key] = digest
        result = {'path': path, 'sha256': digest, 'start_line': start_line, 'end_line': end,
            'total_lines': len(lines), 'artifact': identity, 'unchanged': unchanged,
            'writable': not protected(path, self.prefixes)}
        if not unchanged:
            result['content'] = selected
        return result

    def write(self, path, content, expected_sha256=None):
        target = self.path(path, write=True)
        if expected_sha256 is not None:
            current = sha256(target.read_bytes()).hexdigest() if target.exists() else None
            if current != expected_sha256:
                raise ValueError('Source changed; read it again before writing')
        data = content.replace('\r\n', '\n').encode('utf-8')
        if len(data) > 2_000_000:
            raise ValueError('A source write cannot exceed 2 MB')
        atomic_write(target, data)
        self.reads = {k: v for k, v in self.reads.items() if k[0] != path}
        return {'path': path, 'sha256': sha256(data).hexdigest(), 'bytes': len(data)}

    def write_many(self, files):
        """Several whole files at once; nothing is written unless every entry is permitted."""
        paths = [item['path'] for item in files]
        if not files or len({path.casefold() for path in paths}) != len(paths):
            raise ValueError('write_files needs at least one file and distinct paths')
        for item in files:
            self.path(item['path'], write=True)
            if len(item['content'].encode('utf-8')) > 2_000_000:
                raise ValueError(f'{item["path"]}: a source write cannot exceed 2 MB')
        return {'files': [self.write(item['path'], item['content']) for item in files]}

    def edit(self, path, operation, new_content, old_content=''):
        target = self.path(path, write=True)
        if operation == 'create':
            if target.exists() or old_content:
                raise ValueError('create requires a missing file and empty old_content')
            return self.write(path, new_content)
        current = self.text(path)
        if operation == 'replace':
            if not old_content or current.count(old_content) != 1:
                raise ValueError('replace requires exactly one nonempty old_content match')
            updated = current.replace(old_content, new_content, 1)
        elif operation in {'append', 'prepend'} and not old_content:
            updated = current + new_content if operation == 'append' else new_content + current
        else:
            raise ValueError('Use create, replace, append or prepend')
        return self.write(path, updated)

    def patch(self, changes):
        # Validate every patch and permission before committing any effect.
        staged = {}
        for change in changes:
            path = change['path']
            self.path(path, write=True)
            current = staged[path] if path in staged else self.text(path)
            old = change['old_content']
            if not old or current.count(old) != 1:
                raise ValueError(f'Patch for {path} requires one exact old_content match')
            staged[path] = current.replace(old, change['new_content'], 1)
            if len(staged[path].encode()) > 2_000_000:
                raise ValueError('Patched file exceeds 2 MB')
        return {'files': [self.write(path, text) for path, text in staged.items()]}

    def symbol(self, name, prefix=''):
        """Definitions and uses of an identifier, table or route across application layers."""
        word = re.compile(r'(?<![\w$])' + re.escape(name) + r'(?![\w$])')
        definition = re.compile(r'\b(?:function|class|interface|type|enum|const|let|var)\s+' + re.escape(name) + r'(?![\w$])'
            r'|\bCREATE\s+(?:TABLE|INDEX|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?["`]?' + re.escape(name) + r'["`]?(?![\w$])'
            r'|\.(?:get|post|put|patch|delete|use)\(\s*["\'`]' + re.escape(name) + r'["\'`]', re.IGNORECASE)
        definitions, uses = [], []
        for relative, path in source_files(self.root):
            if not relative.startswith(prefix) or path.stat().st_size > 2_000_000:
                continue
            try:
                lines = path.read_text(encoding='utf-8').splitlines()
            except UnicodeError:
                continue
            for number, line in enumerate(lines, 1):
                if definition.search(line):
                    definitions.append({'path': relative, 'line': number, 'text': line.strip()[:300]})
                elif word.search(line):
                    uses.append({'path': relative, 'line': number, 'text': line.strip()[:300]})
        return {'definitions': definitions[:40], 'uses': uses[:80], 'total_uses': len(uses),
            'notice': 'Textual match; read the file before editing.'}

    def listing(self, prefix='', offset=0, limit=100):
        items = [p for p, _ in source_files(self.root) if p.startswith(prefix)]
        return {'paths': items[offset:offset + limit], 'total': len(items),
            'next_offset': offset + limit if offset + limit < len(items) else None}

    def search(self, query, prefix='', offset=0, limit=50):
        matches = []
        for relative, path in source_files(self.root):
            if not relative.startswith(prefix) or path.stat().st_size > 2_000_000:
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if query in line:
                    matches.append({'path': relative, 'line': number, 'text': line[:1000]})
        return {'matches': matches[offset:offset + limit], 'total': len(matches),
            'next_offset': offset + limit if offset + limit < len(matches) else None}
