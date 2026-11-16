"""The interface contract stated in requirement text, extracted without a model call.

Benchmark requirements name the elements their tests locate, in forms such as
`"Book list"(role=region)`, `"Delete"(role=button)` or `Page list (region)`. Hidden tests
use exactly those roles and names; an application that shows the right text under
another role, or a region without its name, fails them while looking correct. Real run
(2026-11-17): 12/12 local tests passed, 6/12 external ones. The contract is given to the
agent and to the host's test generator as a checklist of exact locators.
"""

import re

ROLES = ('alert', 'article', 'banner', 'button', 'cell', 'checkbox', 'columnheader', 'combobox', 'complementary',
    'dialog', 'form', 'grid', 'heading', 'img', 'link', 'list', 'listbox', 'listitem', 'main', 'menu', 'menuitem',
    'navigation', 'option', 'radio', 'radiogroup', 'region', 'row', 'rowheader', 'search', 'searchbox', 'status',
    'switch', 'tab', 'table', 'tablist', 'tabpanel', 'textbox')
ROLE = '|'.join(ROLES)
QUOTED = re.compile(r'["“]([^"”\n]{1,80})["”]\s*\(\s*role\s*=\s*(' + ROLE + r')\s*\)', re.IGNORECASE)
# `Page list (region)`: a capitalized name of one to five words directly before a role in parentheses.
BARE = re.compile(r'\b([A-Z][\w.\'-]*(?: [\w.\'-]+){0,4}) \((' + ROLE + r')\)')


def extract(text):
    found = []
    for name, role in QUOTED.findall(text or ''):
        found.append((role.lower(), name.strip()))
    for name, role in BARE.findall(QUOTED.sub(' ', text or '')):
        found.append((role.lower(), name.strip()))
    return found


def contract(catalog):
    """Exact locators per requirement id, in document order, without duplicates."""
    result = {}
    for rid, node in catalog.nodes.items():
        description = node.get('description', '')
        texts = [description.get('text', '') if isinstance(description, dict) else description]
        for scenario in node.get('scenarios', []) or []:
            for step in scenario.get('steps', []) or []:
                texts += [value for key, value in step.items() if key in {'Given', 'When', 'Then'} and isinstance(value, str)]
        entries = []
        for text in texts:
            for role, name in extract(text):
                entry = {'role': role, 'name': name}
                if '{' in name:
                    entry['pattern'] = True  # e.g. "{item name}": the name of each item, not literal text.
                if entry not in entries:
                    entries.append(entry)
        if entries:
            result[rid] = entries
    return result


def locator(entry):
    if entry.get('pattern'):
        return f"getByRole('{entry['role']}', {{ name: <the item's own name>, exact: true }})"
    return f"getByRole('{entry['role']}', {{ name: {entry['name']!r}, exact: true }})"
