"""Light coverage registry per requirement/scenario; no exhaustive IR.

Agent declarations (todo list) and host verification are separate columns. Each
host result carries its evidence and the source revision it was obtained on; a
later source change turns it `stale` instead of leaving an outdated `passed`.
Functional and visual conformance are tracked independently.
"""

import re

from .results import FAILED, PASSED

UNVERIFIED, STALE, MISSING, UNAVAILABLE = 'unverified', 'stale', 'missing', 'unavailable'
# A generated test that still fails after its reviews judged it wrong: no verdict either way.
DISPUTED = 'disputed'
SIMILAR, DIVERGENT, MISSING_INTERFACE = 'similar', 'divergent', 'missing_interface'
# Outcomes a scenario explicitly asks for; they must not be dropped by a happy-path check.
ASPECTS = {
    'rejection': r'\b(reject\w*|invalid|incorrect|wrong|den(y|ied)|fail\w*|error|without creating|must not|not allowed|unrecogni[sz]ed|existing|already|duplicate)\b',
    'empty_state': r'\b(empty|no \w+ (yet|exist\w*)|none|missing|signed[- ]out|no session)\b',
    'distinct_data': r'\b(another|second|other (user|account)|distinct|different|two|own(er|s)?|isolat\w+)\b',
    'refresh': r'\b(refresh\w*|reload\w*|persist\w*|remain\w*|restor\w+|after a page)\b',
}


def token(identity):
    return re.compile(r'(?<![A-Za-z0-9_-])' + re.escape(identity) + r'(?![A-Za-z0-9_-])')


def aspects(scenario):
    text = ' '.join(str(value) for step in [scenario, *scenario.get('steps', [])]
        for key, value in step.items() if key not in {'id', 'steps', 'references'} and isinstance(value, str))
    return sorted(name for name, pattern in ASPECTS.items() if re.search(pattern, text, re.IGNORECASE))


class CoverageRegistry:
    def __init__(self, catalog):
        self.catalog = catalog
        self.entries, self.visual = {}, {}
        for sid, (rid, scenario) in catalog.scenarios.items():
            self.entries[sid] = self._entry(sid, rid, 'scenario', aspects(scenario))
        for rid, node in catalog.nodes.items():
            # A requirement without scenarios still needs its own evidence.
            if not (node.get('scenarios') or []) and not (node.get('children') or []):
                self.entries[rid] = self._entry(rid, rid, 'requirement', [])
        for image, (rid, _) in catalog.images.items():
            self.visual[image] = {'image': image, 'requirement': rid, 'status': UNVERIFIED, 'evidence': None,
                'source_revision': None, 'last_result': None}

    @staticmethod
    def _entry(identity, requirement, kind, required):
        return {'id': identity, 'requirement': requirement, 'kind': kind, 'required_aspects': required,
            'functional': UNVERIFIED, 'tests': [], 'evidence': None, 'source_revision': None, 'last_result': None}

    def covers(self, title, header='', filename=''):
        """Scenario/requirement ids a test verifies: title first, then file header or name."""
        found = [identity for identity in self.catalog.scenarios if token(identity).search(title)]
        if found:
            return found
        for text in (title, header, filename):
            requirements = [rid for rid in self.catalog.nodes if token(rid).search(text)]
            if requirements:
                return requirements
        return []

    def _targets(self, identity):
        if identity in self.entries:
            return [identity]
        # A requirement-level test is evidence for the requirement, not for each scenario.
        if identity in self.catalog.nodes:
            self.entries.setdefault('requirement:' + identity,
                self._entry('requirement:' + identity, identity, 'requirement_level', []))
            return ['requirement:' + identity]
        return []

    def record_functional(self, tests, revision, evidence, *, complete):
        """Record executed tests; with a complete suite, uncovered entries become `missing`."""
        touched = {}
        for test in tests:
            for identity in test.get('covers', []):
                for target in self._targets(identity):
                    touched.setdefault(target, []).append(test)
        for identity, results in touched.items():
            entry = self.entries[identity]
            statuses = {test['status'] for test in results}
            status = FAILED if FAILED in statuses else PASSED if statuses == {PASSED} else \
                DISPUTED if statuses <= {PASSED, DISPUTED} else UNVERIFIED
            entry.update(functional=status, evidence=evidence, source_revision=revision,
                tests=[{'title': test['title'], 'status': test['status'], 'origin': test.get('origin')} for test in results],
                last_result={'status': status, 'source_revision': revision})
        if complete:
            for identity, entry in self.entries.items():
                if identity not in touched and entry['kind'] != 'requirement_level':
                    entry.update(functional=MISSING, tests=[], evidence=None, source_revision=revision)

    def record_visual(self, image, status, revision, evidence=None, **details):
        self.visual[image].update(status=status, evidence=evidence, source_revision=revision, **details,
            last_result={'status': status, 'source_revision': revision})

    def invalidate(self, revision):
        """Without an IR there is no per-scenario dependency map: any source change
        conservatively invalidates every host proof obtained on another revision."""
        stale = []
        for entry in self.entries.values():
            if entry['functional'] in {PASSED, FAILED, DISPUTED} and entry['source_revision'] != revision:
                entry['functional'] = STALE
                stale.append(entry['id'])
        for entry in self.visual.values():
            if entry['status'] in {SIMILAR, DIVERGENT} and entry['source_revision'] != revision:
                entry['status'] = STALE
                stale.append(entry['image'])
        return stale

    def uncovered(self):
        """Scenarios no independent test has executed against."""
        return [identity for identity, entry in self.entries.items()
            if entry['kind'] == 'scenario' and not entry['tests']]

    def omissions(self):
        return sorted(identity for identity, entry in self.entries.items()
            if entry['kind'] != 'requirement_level' and entry['functional'] not in {PASSED, DISPUTED})

    def summary(self):
        counts, visual = {}, {}
        for entry in self.entries.values():
            if entry['kind'] != 'requirement_level':
                counts[entry['functional']] = counts.get(entry['functional'], 0) + 1
        for entry in self.visual.values():
            visual[entry['status']] = visual.get(entry['status'], 0) + 1
        return {'functional': counts, 'visual': visual, 'omissions': self.omissions()}

    def view(self, todos, revision=None):
        """Agent claims next to host verification, per requirement."""
        if revision is not None:
            self.invalidate(revision)
        claims = {rid: [] for rid in self.catalog.nodes}
        for item in todos:
            for rid in item.get('requirements', []):
                claims[rid].append({'task': item['id'], 'declared_status': item['status']})
        rows = []
        for rid in self.catalog.nodes:
            entries = [entry for entry in self.entries.values() if entry['requirement'] == rid]
            rows.append({'id': rid, 'consulted': rid in self.catalog.consulted, 'agent_claims': claims[rid],
                'host_verification': [{'id': entry['id'], 'functional': entry['functional'],
                    'required_aspects': entry['required_aspects'], 'evidence': entry['evidence'],
                    'source_revision': entry['source_revision']} for entry in entries],
                'visual': [{key: entry[key] for key in ('image', 'status', 'evidence')}
                    for entry in self.visual.values() if entry['requirement'] == rid]})
        return {'requirements': rows, 'summary': self.summary(), 'viewed_images': sorted(self.catalog.viewed),
            'accepted': False, 'notice': 'agent_claims are declarations; only host_verification is independent evidence.'}
