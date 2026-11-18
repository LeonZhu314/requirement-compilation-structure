"""Lossless local requirements catalogue. Loading never calls a model."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

import yaml

from infrastructure.requirements.contract import area_locator, contained_controls, contract, locator, named_areas
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

    def _node(self, rid):
        node = deepcopy(self.nodes[rid])
        node.pop('children', None)
        return node

    def read(self, identity, record=True, shown=None, descendants=False):
        """`shown`: requirement ids whose text the reader already holds; an ancestor in it is
        named, not repeated (reading 17 leaves of one section repeated its parents 17 times).
        `descendants`: the whole section below the requirement, in one answer."""
        rid = identity if identity in self.nodes else (self.scenarios.get(identity) or self.steps.get(identity) or (None,))[0]
        if rid is None:
            raise ValueError(f'Unknown requirement/scenario/step: {identity}')
        chain, current = [], rid
        while current is not None:
            chain.insert(0, current)
            current = self.parents[current]
        if record:  # Host reads for acceptance are not agent consultations.
            self.consulted.add(identity)
        held = shown if shown is not None else set()
        # Own parent scenarios are deliberately retained, not just leaf descriptions.
        ancestors = [{'id': item, 'name': self.nodes[item].get('name', ''), 'already_shown': True} if item in held
            else self._node(item) for item in chain[:-1]]
        result = {'requested': identity, 'ancestor_requirements': ancestors, 'requirement': self._node(rid),
            'children': [c['id'] for c in self.nodes[rid].get('children', []) or []],
            'source': 'requirements.yaml', 'source_sha256': self.source_sha256}
        seen = set(chain)
        if descendants:
            below, stack = [], [c['id'] for c in reversed(self.nodes[rid].get('children', []) or [])]
            while stack:
                item = stack.pop()
                below.append(self._node(item))
                stack.extend(c['id'] for c in reversed(self.nodes[item].get('children', []) or []))
            result['descendant_requirements'] = below
            seen.update(node['id'] for node in below)
            if record:
                self.consulted.update(node['id'] for node in below)
        if shown is not None:
            shown.update(seen)
        return result

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

    def _direct(self, requirement, scenarios):
        found = list(self.nodes.get(requirement, {}).get('dependencies', []) or [])
        for sid in scenarios:
            for step in (self.scenarios.get(sid, (None, {}))[1].get('steps', []) or []):
                for value in [*(step.get('references', []) or []), *(v for v in step.values() if isinstance(v, str))]:
                    found += [identity for kind, identity in REFERENCE.findall(value) if kind == 'requirement']
        return [rid for rid in dict.fromkeys(found) if rid in self.nodes]

    def referenced(self, requirement, scenarios=(), limit=10):
        """Requirements a requirement or its scenarios rely on (`dependencies`, `\\ref[requirement]`
        in steps), transitively and nearest first, outside its own ancestor chain. A test of
        "vote on an answer" first logs in, publishes a question and answers it: it must follow the
        rules of those requirements too (real run: 8 generated tests posted bodies shorter than
        the publishing requirement's minimum and failed for that reason, 87 minutes of repair on
        a correct application)."""
        chain, current = set(), requirement
        while current is not None:
            chain.add(current)
            current = self.parents.get(current)
        result, queue = [], self._direct(requirement, scenarios)
        while queue and len(result) < limit:
            rid = queue.pop(0)
            if rid in chain or rid in result:
                continue
            result.append(rid)
            own = [s['id'] for s in self.nodes[rid].get('scenarios', []) or []]
            queue += [item for item in self._direct(rid, own) if item not in result]
        return result

    def referenced_context(self, requirement, scenarios=()):
        """Description and exact locators of each referenced requirement (no scenarios: their
        own Given data belongs to their own tests)."""
        result = []
        for rid in self.referenced(requirement, scenarios):
            description = self.nodes[rid].get('description', '')
            text = description.get('text', '') if isinstance(description, dict) else description
            result.append({'id': rid, 'name': self.nodes[rid].get('name', ''), 'description': text,
                'required_locators': [locator(entry) for entry in self.interface_contract().get(rid, [])]})
        return result

    def areas_for(self, requirement, scenarios=()):
        """Named areas a requirement's own texts and its scenarios mention, as locators."""
        texts = []
        node = self.nodes.get(requirement, {})
        description = node.get('description', '')
        texts.append(description.get('text', '') if isinstance(description, dict) else description)
        for sid in scenarios:
            for step in (self.scenarios.get(sid, (None, {}))[1].get('steps', []) or []):
                texts += [v for k, v in step.items() if k in {'Given', 'When', 'Then'} and isinstance(v, str)]
        joined = ' '.join(texts)
        joined = ' '.join(joined.split())
        return [area_locator(name) for name in named_areas(self, self.interface_contract()) if name in joined]

    def controls_inside_for(self, requirement, scenarios=()):
        """Controls the requirement's texts place inside an area, as 'control inside locator' notes."""
        texts = []
        node = self.nodes.get(requirement, {})
        description = node.get('description', '')
        texts.append(description.get('text', '') if isinstance(description, dict) else description)
        for sid in scenarios:
            for step in (self.scenarios.get(sid, (None, {}))[1].get('steps', []) or []):
                texts += [v for k, v in step.items() if k in {'Given', 'When', 'Then'} and isinstance(v, str)]
        joined = ' '.join(' '.join(texts).split())
        found = self.interface_contract()
        roles = {entry['name']: entry for entries in found.values() for entry in entries}
        return [f'{control!r} inside ' + (locator(roles[area]) if area in roles else area_locator(area))
            for control, area in contained_controls(self, found) if control in joined and area in joined]

    inline = False  # True once the whole source was given in the task message.

    def initial_context(self, max_chars=24000):
        notices = {'input_notices': self.notices} if self.notices else {}
        found = self.interface_contract()
        if found:
            notices['interface_contract'] = {
                'notice': 'The requirements name these elements explicitly. The acceptance tests locate them exactly '
                    'like this (role and full accessible name, case-sensitive). Give each one that role and that '
                    'accessible name, e.g. a <section aria-label="..."> for a region, a <button> or <a> whose text is '
                    'the name. A {placeholder} name means the name of each item. Where a locator offers two roles '
                    '(.or), either is correct: use one native element, never both, never nested. A control the '
                    'requirements name without a role is a <button> (also when it opens another page), unless they '
                    'call it a link or it is an entry of a navigation menu.',
                'locators': {rid: [locator(entry) for entry in entries] for rid, entries in found.items()}}
        areas = named_areas(self, found)
        inside = contained_controls(self, found)
        if inside:
            notices['controls_inside_areas'] = {
                'notice': 'The scenarios act on these controls inside these areas ("Click Checkout in Order summary", '
                    '"Order summary exposes Checkout"). Tests look for the control only inside the element of the area: put '
                    'it inside that element on every page where the area appears, not beside it or above it.',
                'pairs': [f'{control!r} inside {area!r}' for control, area in inside]}
        if areas:
            notices['named_areas'] = {
                'notice': 'The scenarios also name these parts of a page ("Click Checkout in Order summary"). '
                    'Tests look inside them by that exact accessible name. Give each one that is an area a wrapping '
                    'element with exactly this name: <nav aria-label="..."> for a navigation, <section aria-label='
                    '"..."> otherwise. A name that is a field keeps it as its label. Ignore a phrase that is not a '
                    'part of the page.',
                'names': areas}
        self.inline = len(self.source) <= max_chars
        if self.inline:
            self.consulted.update(self.nodes)
            return {'source_sha256': self.source_sha256, 'original_yaml': self.source, **notices,
                'notice': 'original_yaml is the complete requirements file and stays in this message for the whole '
                    'run: read requirements here, do not fetch them again with read_requirement.'}
        return {'source_sha256': self.source_sha256, 'catalog': self.catalog(), **notices,
            'notice': 'The requirements are too large to stay in the conversation: what you read leaves it after a '
                'while. Never read them all before writing. Work one top-level section at a time: read it in one call '
                '(read_requirement with descendants true), write its code at once, mark its task done with todo_write, '
                'then take the next section. Independent sections can be given to delegate_tasks. Page the catalogue.'}

    def coverage(self, todos):
        claims = {rid: [] for rid in self.nodes}
        for item in todos:
            for rid in item.get('requirements', []):
                claims[rid].append({'task': item['id'], 'declared_status': item['status']})
        return {'requirements': [{'id': rid, 'consulted': rid in self.consulted,
            'agent_claims': claims[rid], 'verification': 'unverified'} for rid in self.nodes],
            'viewed_images': sorted(self.viewed), 'accepted': False}
