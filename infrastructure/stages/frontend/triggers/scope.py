"""Small model contexts without reducing the compiler's implementation or test scope.

Requirement implementation and repair see the current behavioral references together.
Source dependencies and generated tests named by failed checks are added as needed;
test corrections remain grounded in the supplied requirement contexts.
"""

import json

from infrastructure.stages.frontend.triggers.design import api_ids

class TriggerCheckFailure(ValueError):
    """Keep full reports for logs while exposing structured, compact repair feedback."""

    def __init__(self, message, report):
        """Attach check results so the model need not parse a duplicated report string."""
        self.feedback = {"error": message, "checks": report}
        super().__init__(f"{message}: {report}")


def model_context(context, *, implementation=False):
    """Supply selected triggers, complete page data, API contracts and derived DB effects."""
    selected = set(context["triggers"])
    triggers = {tid: context["triggers"][tid] for tid in sorted(selected)}
    called = {aid for trigger in triggers.values() for aid in api_ids(trigger)}
    result = {"page_subtrees": context["page_subtrees"], "triggers": triggers,
        "obligations": {tid: context["obligations"][tid] for tid in sorted(selected)},
        "target_trigger_ids": context["target_trigger_ids"],
        "backend_apis": {aid: context["backend_apis"][aid] for aid in sorted(called)}}
    if implementation:
        # Actual components and original requirements are already supplied. Repeating
        # every decorative node/data declaration is expensive and not an implementation ABI.
        relevant = {trigger['source'] for trigger in triggers.values()}
        relevant.update(action['ui'] for trigger in triggers.values() for action in trigger['action']
            if action['kind'] == 'ui')
        result['page_subtrees'] = {pid: {**{key: page[key] for key in ('name', 'route', 'root') if key in page},
            'elements': {uid: {key: node[key] for key in ('type', 'parent', 'prop') if key in node}
                for uid, node in page['elements'].items() if uid in relevant}}
            for pid, page in context['page_subtrees'].items()}
    if "requirement" in context:
        result["requirement"] = context["requirement"]
    if "regression_requirements" in context:
        result["regression_requirements"] = context["regression_requirements"]
    return result
