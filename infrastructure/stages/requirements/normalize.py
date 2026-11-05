"""Normalize supported YAML shapes without a model call or changing requirement text."""

from copy import deepcopy


def normalize_requirements(root):
    root = deepcopy(root)

    def visit(node):
        rid = node['id']
        for number, scenario in enumerate(node.get('scenarios', []) or [], 1):
            sid = scenario.setdefault('id', f'SCN-{rid}-{number:02d}')
            steps = scenario.get('steps', []) or []
            normalized, grouped, previous = [], None, None
            for step in steps:
                if 'keyword' not in step:
                    grouped, previous = None, None
                    record = dict(step)
                    record.setdefault('id', f'STEP-{sid}-{len(normalized) + 1:02d}')
                    normalized.append(record)
                    continue
                keyword = str(step['keyword']).strip().lower()
                role = {'given': 'Given', 'when': 'When', 'then': 'Then'}.get(keyword)
                if keyword in ('and', 'but'):
                    role = previous
                if role is None:
                    raise ValueError(f'Unsupported scenario keyword {step["keyword"]!r} in {sid}')
                if grouped is None or (role in ('Given', 'When') and grouped.get('Then')):
                    grouped = {'id': step.get('id', f'STEP-{sid}-{len(normalized) + 1:02d}'),
                        'Given': '', 'When': '', 'Then': '', 'references': []}
                    normalized.append(grouped)
                content = step.get('content', '')
                if not isinstance(content, str):
                    raise ValueError(f'Scenario content must be text in {sid}')
                grouped[role] = '\n'.join(filter(None, (grouped[role], content)))
                grouped['references'].extend(step.get('references', []) or [])
                previous = role
            scenario['steps'] = normalized
        pages = node.get('pages', []) or []
        if pages:
            description = node.get('description', '')
            description = {'text': description} if isinstance(description, str) else dict(description)
            images = description.setdefault('image', [])
            references = {image['reference'] for image in images}
            for number, page in enumerate(pages, 1):
                reference = page.get('reference')
                if reference and reference not in references:
                    images.append({'id': f'IMG-{rid}-{number:02d}', 'reference': reference,
                        'page': page.get('name', '')})
                    references.add(reference)
            node['description'] = description
        for child in node.get('children', []) or []:
            visit(child)

    visit(root)
    return root
