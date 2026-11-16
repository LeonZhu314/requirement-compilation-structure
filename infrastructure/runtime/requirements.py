"""Lossless local requirements catalogue. Loading never calls a model."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

import yaml

from infrastructure.requirements.contract import contract, locator
from infrastructure.requirements.normalize import normalize_requirements
from infrastructure.utils.paths import relative_path


class UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError(f'Duplicate or non-text YAML key: {key!r}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
REFERENCE = re.compile(r'\\ref\[([^\]]+)\]\(([^)]+)\)')


class RequirementCatalog:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        source = self.directory / 'requirements.yaml'
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 8_000_000:
            raise ValueError('Expected a regular requirements.yaml of at most 8 MB')
        self.source = source.read_text(encoding='utf-8-sig')
        self.source_sha256 = sha256(source.read_bytes()).hexdigest()
        self.original = yaml.load(self.source, Loader=UniqueLoader)
        self.nodes, self.parents, self.scenarios, self.steps, self.images = {}, {}, {}, {}, {}
        self.consulted, self.viewed = set(), set()
        self.image_owners, self.notices = {}, []
        self._validate_shape(self.original)
        self.root = normalize_requirements(self.original)
        # Normalization is useful for page resources and generated identifiers,
        # but the catalogue must retain each original keyword step and its id.
        def retain_steps(original, normalized):
            for number, (raw, scenario) in enumerate(zip(original.get('scenarios', []) or [], normalized.get('scenarios', []) or []), 1):
                sid = scenario['id']
                scenario['steps'] = [{**deepcopy(step), 'id': step.get('id', f'STEP-{sid}-{index:02d}')}
                    for index, step in enumerate(raw.get('steps', []) or [], 1)]
            for raw, child in zip(original.get('children', []) or [], normalized.get('children', []) or []):
                retain_steps(raw, child)
        retain_steps(self.original, self.root)
        ids = set()

        def register(record, kind, index, owner):
            identity = record.get('id')
            if not isinstance(identity, str) or not identity.strip() or identity in ids:
                raise ValueError(f'Missing or duplicate {kind} id: {identity!r}')
            ids.add(identity)
            index[identity] = (owner, record) if kind != 'requirement' else record
            return identity

        def register_image(image, rid):
            """Images have their own namespace: real inputs attach one reference image,
            under one id, to several requirements. That is one shared image, not an error."""
            identity = image.get('id')
            if not isinstance(identity, str) or not identity.strip():
                raise ValueError(f'Missing image id: {identity!r}')
            known = self.images.get(identity)
            if known is None:
                self.images[identity] = (rid, image)
            elif known[1].get('reference') != image.get('reference'):
                # Same id, another file: keep both reachable instead of refusing the task.
                renamed = f'{identity}@{rid}'
                if renamed in self.images:
                    raise ValueError(f'Duplicate image id: {identity!r}')
                self.notices.append(f'Image id {identity} names several files; the one of requirement {rid} '
                    f'({image.get("reference")}) is available as {renamed}.')
                image['id'] = identity = renamed
                self.images[identity] = (rid, image)
            self.image_owners.setdefault(identity, []).append(rid)

        def visit(node, parent=None):
            rid = register(node, 'requirement', self.nodes, None)
            self.parents[rid] = parent
            description = node.get('description', '')
            if isinstance(description, dict):
                for image in description.get('image', []) or []:
                    register_image(image, rid)
            for scenario in node.get('scenarios', []) or []:
                register(scenario, 'scenario', self.scenarios, rid)
                for step in scenario.get('steps', []) or []:
                    register(step, 'step', self.steps, rid)
            for child in node.get('children', []) or []:
                visit(child, rid)
        visit(self.root)
        self.resource_data = {}
        for identity, (_, image) in self.images.items():
            path = self.resource_path(image.get('reference'))
            if path.stat().st_size > 20_000_000:
                raise ValueError(f'Image resource exceeds 20 MB: {identity}')
            # Freeze originals in memory so later source edits cannot change the task.
            self.resource_data[identity] = path.read_bytes()
        indexes = {'requirement': self.nodes, 'scenario': self.scenarios, 'step': self.steps, 'image': self.images}
        for value in self._strings(self.root):
            for kind, identity in REFERENCE.findall(value):
                if kind not in indexes or identity not in indexes[kind]:
                    raise ValueError(f'Unknown reference: {kind}/{identity}')

    @classmethod
    def _validate_shape(cls, node, depth=0):
        if depth > 64:
            raise ValueError('Requirement tree is cyclic or exceeds 64 levels')
        if not isinstance(node, dict) or not isinstance(node.get('id'), str):
            raise ValueError('Each requirement must be an object with a text id')
        if not isinstance(node.get('name', ''), str):
            raise ValueError('Requirement name must be text')
        description = node.get('description', '')
        if not isinstance(description, (str, dict)):
            raise ValueError('Description must be text or an object')
        if isinstance(description, dict):
            if not isinstance(description.get('text', ''), str):
                raise ValueError('Description text must be a string')
            cls._objects(description, 'image')
        for key in ('children', 'scenarios', 'pages'):
            cls._objects(node, key)
        for scenario in node.get('scenarios', []) or []:
            cls._objects(scenario, 'steps')
            for step in scenario.get('steps', []) or []:
                for key in ('Given', 'When', 'Then', 'given', 'when', 'then', 'keyword', 'content'):
                    if key in step and not isinstance(step[key], str):
                        raise ValueError(f'{key} must be text')
                references = step.get('references', []) or []
                if not isinstance(references, list) or any(not isinstance(v, str) for v in references):
                    raise ValueError('Step references must be a list of strings')
                if any(v.startswith('\\ref') and not REFERENCE.fullmatch(v) for v in references):
                    raise ValueError('Malformed scenario reference')
        for child in node.get('children', []) or []:
            cls._validate_shape(child, depth + 1)

    @staticmethod
    def _objects(node, key):
        value = node.get(key, [])
        if value is not None and (not isinstance(value, list) or any(not isinstance(v, dict) for v in value)):
            raise ValueError(f'{key} must be a list of objects')

    @classmethod
    def _strings(cls, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from cls._strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from cls._strings(item)

    def resource_path(self, relative):
        parts = relative_path(relative).parts
        path = self.directory
        for part in parts:
            path = path / part
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('Resource links are not allowed')
        if not path.resolve().is_relative_to(self.directory) or not path.is_file():
            raise ValueError(f'Missing resource: {relative}')
        return path

    def catalog(self, offset=0, limit=50):
        rows = [{'id': rid, 'title': node.get('name', ''), 'parent': self.parents[rid],
            'source': 'requirements.yaml', 'scenarios': [s['id'] for s in node.get('scenarios', []) or []],
            'resources': [i for i, owners in self.image_owners.items() if rid in owners]}
            for rid, node in self.nodes.items()]
        return {'items': rows[offset:offset + limit], 'total': len(rows),
            'next_offset': offset + limit if offset + limit < len(rows) else None,
            'source_sha256': self.source_sha256}

    def read(self, identity, record=True):
        rid = identity if identity in self.nodes else (self.scenarios.get(identity) or self.steps.get(identity) or (None,))[0]
        if rid is None:
            raise ValueError(f'Unknown requirement/scenario/step: {identity}')
        chain, current = [], rid
        while current is not None:
            record = deepcopy(self.nodes[current])
            record.pop('children', None)
            chain.insert(0, record)
            current = self.parents[current]
        if record:  # Host reads for acceptance are not agent consultations.
            self.consulted.add(identity)
        # Own parent scenarios are deliberately retained, not just leaf descriptions.
        return {'requested': identity, 'ancestor_requirements': chain[:-1], 'requirement': chain[-1],
            'children': [c['id'] for c in self.nodes[rid].get('children', []) or []],
            'source': 'requirements.yaml', 'source_sha256': self.source_sha256}

    def interface_contract(self):
        if not hasattr(self, '_contract'):
            self._contract = contract(self)
        return self._contract

    def contract_for(self, identity):
        """Exact locators of a requirement and of its ancestors (their constraints bind it too)."""
        result, current = [], identity
        while current is not None:
            result = [{**entry, 'requirement': current} for entry in self.interface_contract().get(current, [])] + result
            current = self.parents.get(current)
        return result

    def initial_context(self, max_chars=24000):
        notices = {'input_notices': self.notices} if self.notices else {}
        found = self.interface_contract()
        if found:
            notices['interface_contract'] = {
                'notice': 'The requirements name these elements explicitly. The acceptance tests locate them exactly '
                    'like this (role and full accessible name, case-sensitive). Give each one that role and that '
                    'accessible name, e.g. a <section aria-label="..."> for a region, a <button> or <a> whose text is '
                    'the name. A {placeholder} name means the name of each item.',
                'locators': {rid: [locator(entry) for entry in entries] for rid, entries in found.items()}}
        if len(self.source) <= max_chars:
            self.consulted.update(self.nodes)
            return {'source_sha256': self.source_sha256, 'original_yaml': self.source, **notices}
        return {'source_sha256': self.source_sha256, 'catalog': self.catalog(), **notices,
            'notice': 'Read every applicable requirement and its parent constraints with read_requirement. Page the catalogue.'}

    def coverage(self, todos):
        claims = {rid: [] for rid in self.nodes}
        for item in todos:
            for rid in item.get('requirements', []):
                claims[rid].append({'task': item['id'], 'declared_status': item['status']})
        return {'requirements': [{'id': rid, 'consulted': rid in self.consulted,
            'agent_claims': claims[rid], 'verification': 'unverified'} for rid in self.nodes],
            'viewed_images': sorted(self.viewed), 'accepted': False}
