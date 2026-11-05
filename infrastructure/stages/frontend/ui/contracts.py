"""Read explicit role/name pairs from original prose, without inventing UI contracts."""

import re


EXPLICIT_CONTROL = re.compile(r'["“]([^"”\n]+)["”]\s*[（(]\s*role\s*=\s*([a-z][a-z0-9-]*)\s*[)）]')


def explicit_controls(requirements):
    controls = set()

    def visit(value):
        if isinstance(value, str):
            controls.update(EXPLICIT_CONTROL.findall(value))
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(requirements)
    return controls


def element_contract(node, controls):
    # A separate text label can share a control's name; it is not that control.
    if node.get('type') not in {'input', 'checkbox', 'select', 'button', 'link',
            'radio', 'radiogroup', 'heading', 'image'}:
        return None
    props = node.get('prop', {})
    names = {value.strip().lstrip('*').strip().rstrip(':').strip()
        for key, value in props.items() if key in ('label', 'text', 'name', 'aria-label', 'ariaLabel')
        and isinstance(value, str)}
    matches = {(name, role) for name, role in controls if name in names}
    return next(iter(matches)) if len(matches) == 1 else None
