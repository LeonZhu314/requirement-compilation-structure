"""Host-owned immutable, paginated observations outside the editable application."""

from hashlib import sha256
import json
from pathlib import Path
import re


class ArtifactStore:
    def __init__(self, directory):
        self.directory = Path(directory) / 'artifacts'

    def put(self, value, suffix='.txt'):
        data = value if isinstance(value, bytes) else value.encode('utf-8')
        identity = sha256(data).hexdigest() + suffix
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / identity
        if not path.exists():
            path.write_bytes(data)
        return identity

    def path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-f]{64}\.(txt|json|png|jpg)', identity):
            raise ValueError('Invalid artifact id')
        path = self.directory / identity
        if not path.is_file() or path.is_symlink() or sha256(path.read_bytes()).hexdigest() != identity.split('.')[0]:
            raise ValueError('Missing or altered artifact')
        return path

    def read(self, identity, offset=0, limit=12000):
        text = self.path(identity).read_text(encoding='utf-8')
        return {'artifact': identity, 'content': text[offset:offset + limit], 'offset': offset,
            'total_chars': len(text), 'next_offset': offset + limit if offset + limit < len(text) else None}

    def bound(self, result, limit=12000):
        text = json.dumps(result, ensure_ascii=False)
        if len(text) <= limit:
            return result
        identity = self.put(text, '.json')
        return {'artifact': identity, 'preview': text[:limit], 'total_chars': len(text),
            'notice': 'Observation truncated; use read_artifact to retrieve exact remaining content.'}
