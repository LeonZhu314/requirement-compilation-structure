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


PERMISSION = re.compile(r'\b(either|equivalent|alternatively|allowed|accepted|permitted)\b', re.IGNORECASE)
ROLE_WORD = re.compile(r'\b(link|button)s?\b', re.IGNORECASE)
INTERCHANGEABLE = {'button', 'link'}


def sentences(text):
    return [part for part in re.split(r'(?<=[.;!?])\s+', text or '') if part.strip()]


def extract(text):
    """(role, name) pairs, plus the roles the same sentence explicitly allows instead."""
    found = []
    for sentence in sentences(text):
        # The annotation itself ("(role=button)") is not an alternative: look at the rest of the sentence.
        rest = QUOTED.sub(' ', sentence)
        allowed = {word.lower() for word in ROLE_WORD.findall(rest)} if PERMISSION.search(rest) else set()
        pairs = [(role.lower(), name.strip()) for name, role in QUOTED.findall(sentence)]
        pairs += [(role.lower(), name.strip()) for name, role in BARE.findall(QUOTED.sub(' ', sentence))]
        for role, name in pairs:
            alternatives = tuple(sorted(({role} | allowed) & INTERCHANGEABLE)) if role in INTERCHANGEABLE else ()
            found.append((role, name, alternatives if len(alternatives) > 1 else ()))
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
            for role, name, alternatives in extract(text):
                entry = {'role': role, 'name': name}
                if alternatives:
                    entry['alternatives'] = list(alternatives)
                if '{' in name:
                    entry['pattern'] = True  # e.g. "{item name}": the name of each item, not literal text.
                if entry not in entries:
                    entries.append(entry)
        if entries:
            result[rid] = entries
    return result


# "Click Ask Question in Question feed", "Follow Questions in Main navigation": parts of the page
# the scenarios name without a role annotation. Hidden tests scope their locators inside them;
# a real application had no "Question feed" at all while every local test passed.
AREA = re.compile(r'\b(?:in|within|inside|from|on|In|Within)\s+(?:the\s+)?([A-Z][a-z]+\s+[a-z]+)\b')
LINKING = {'and', 'or', 'to', 'with', 'opens', 'are', 'before', 'into', 'the', 'click', 'choose', 'press',
    'description', 'within', 'is', 'for', 'of', 'after', 'then', 'by'}


def named_areas(catalog, found=None):
    """Two-word names of page parts the requirement texts refer to ("in Main navigation"),
    minus those the explicit contract already lists. Advisory: the role is not stated."""
    known = {entry['name'].lower() for entries in (found if found is not None else contract(catalog)).values()
        for entry in entries}
    texts = [' '.join(value.split()) for value in catalog._strings(catalog.root)]
    whole = ' '.join(texts)
    names = []
    for value in texts:
        for match in AREA.finditer(value):
            name = match.group(1)
            if name.split()[1] in LINKING or name.lower() in known or name in names:
                continue
            # "Fill Page title with ...": a field, not an area.
            field = re.search(r'\b(?:fill|enter|type|set|clear|select|choose)\s+(?:the\s+)?' + re.escape(name)
                + r'|' + re.escape(name) + r'\s+(?:textbox|field|input|combobox|dropdown)\b', whole, re.IGNORECASE)
            if not field:
                names.append(name)
    return names


# "Click Ask Question in Question feed", "Question feed exposes Ask Question": a control the tests
# look for inside that area (real run: the button sat just above the area and every test that
# created a question failed).
ACTION_IN = re.compile(r"\b(?:Click|Follow|Select|Open|Press|Activate|Choose|Tap|Use)\s+(?:the\s+)?"
    r"([A-Z][\w.?'-]*(?:\s+[A-Za-z][\w.?'-]*){0,4}?)\s+(?:in|within|inside|on)\s+(?:the\s+)?"
    r"([A-Z][\w.'-]*(?:\s+[A-Za-z][\w.'-]*){0,3})")
EXPOSES = re.compile(r"\b([A-Z][a-z]+(?:\s+[a-z]+){1,2})\s+(?:exposes|offers|contains|provides)\s+(?:an?\s+|the\s+)?"
    r"([A-Z][\w.?'-]*(?:\s+[A-Z][\w.?'-]*){0,3})")
CONTAINERS = {'region', 'navigation', 'dialog', 'list', 'form', 'table', 'grid', 'menu', 'tablist', 'complementary',
    'search', 'listbox', 'group', 'radiogroup'}


def contained_controls(catalog, found=None):
    """(control, area) pairs the requirement texts place inside a known area."""
    found = found if found is not None else contract(catalog)
    areas = set(named_areas(catalog, found)) | {entry['name'] for entries in found.values() for entry in entries
        if entry['role'] in CONTAINERS and not entry.get('pattern')}
    whole = ' '.join(' '.join(value.split()) for value in catalog._strings(catalog.root))
    pairs = []

    def add(control, area):
        # The longest known area that starts the captured words ("Question feed, fill ..." -> "Question feed").
        area = re.split(r'[.,;:!?](?:\s|$)', area)[0]
        area = next((name for name in sorted(areas, key=len, reverse=True)
            if area == name or area.startswith(name + ' ')), None)
        if area and control != area and (control, area) not in pairs:
            pairs.append((control, area))
    for match in ACTION_IN.finditer(whole):
        add(match.group(1).strip(), match.group(2).strip())
    for match in EXPOSES.finditer(whole):
        add(match.group(2).strip(), match.group(1).strip())
    return pairs


def area_locator(name):
    role = 'navigation' if name.lower().endswith('navigation') else 'region'
    return f"getByRole('{role}', {{ name: {name!r}, exact: true }})"


def locator(entry):
    name = "<the item's own name>" if entry.get('pattern') else repr(entry['name'])
    roles = entry.get('alternatives') or [entry['role']]
    # Either role satisfies the requirement: a test must accept both, and the application
    # uses the one native element that fits (a link to navigate, a button to act).
    return '.or('.join(f"getByRole('{role}', {{ name: {name}, exact: true }})" for role in roles) + ')' * (len(roles) - 1)
