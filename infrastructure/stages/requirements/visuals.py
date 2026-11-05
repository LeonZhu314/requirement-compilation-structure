"""Keep optional visual evidence available without blocking functional compilation."""

import json

from infrastructure.utils.files import save_json
from infrastructure.shared.project.git import checkpoint


def unavailable_analysis(error):
    return {
        "status": "UNAVAILABLE",
        "layout": "",
        "elements": [],
        "style": "",
        "error": str(error),
        "error_type": type(error).__name__,
        "notice": "Visual analysis is unavailable. Use the original textual requirements, "
            "explicit UI names/roles and page references. Do not invent observations from this image.",
    }


def analyze_references(input_dir, arc_dir, references, model_factory, console):
    """Publish every image result, including explicit unavailable evidence, incrementally."""
    analysis = {}
    report = {"status": "RUNNING", "analyzed": [], "failures": {}}

    def publish():
        save_json(arc_dir / "visual_analysis.json", analysis)
        save_json(arc_dir / "visual_analysis_report.json", report)

    # Publish before initializing a provider: an optional service failure must
    # never leave a missing artifact that blocks all four frontend passes.
    publish()
    model, initialization_error = None, None
    if references:
        try:
            model = model_factory()
        except (RuntimeError, ValueError, OSError) as error:
            initialization_error = error
    for reference in references:
        print(f"Analyzing image: {reference}", flush=True)
        try:
            if initialization_error is not None:
                raise initialization_error
            result = model.analyze(input_dir / reference)
            if not isinstance(result, dict):
                raise ValueError("Visual analysis must return an object")
            analysis[reference] = result
            report["analyzed"].append(reference)
        except (RuntimeError, ValueError, OSError) as error:
            analysis[reference] = unavailable_analysis(error)
            report["failures"][reference] = {"error": str(error), "error_type": type(error).__name__}
            console.show(f"Visual analysis unavailable | {reference}",
                f"{error}\nContinue from the original textual requirements. Visual fidelity is unverified.")
        publish()
        checkpoint(arc_dir.parent, stage="01", task=reference,
            action="Publish visual reference evidence",
            status="DEGRADED" if reference in report["failures"] else "GREEN",
            details={"reference": reference, "analysis": analysis[reference]})
        console.show(f"3. Visual analysis | {reference}", json.dumps(analysis[reference], ensure_ascii=False, indent=2))
    report["status"] = "DEGRADED" if report["failures"] else "GREEN"
    publish()
    return analysis, report
