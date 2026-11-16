"""File editing with failure attribution and real acceptance checks."""

import json
from itertools import count
from urllib import request

from infrastructure.shared.agent.discovery import DISCOVERY_RULES, DiscoverySession
from infrastructure.shared.agent.conventions import task_conventions

from infrastructure.shared.agent.tools import FileTools, files
from infrastructure.shared.agent.tools.protocol import FILE_TOOL_RULES
from infrastructure.shared.agent.proposals import RESPONSE_ERRORS, response_feedback
from infrastructure.shared.project.git import checkpoint
from infrastructure.stages.database.obligations import records
from infrastructure.utils.files import read_source
from infrastructure.shared.models.errors import ModelServiceError


class AgentExhausted(ValueError):
    """A recoverable task failure with the last real repair feedback."""

    def __init__(self, label, turns, feedback):
        super().__init__(f"Agent exhausted {turns} rounds for {label}")
        self.turns = turns
        self.feedback = feedback


def run_file_agent(model, instructions: str, task: dict, files: FileTools, gate,
        max_turns: int | None, console, label: str, feedback=None, feedback_filter=None, context_index=None,
        allow_discovery=True, test_review=None) -> dict:
    """Refresh files and paths; optionally select failure-related files before repair.

    The stage-owned feedback filter may add writable sources/read-only references
    and condense check reports. It cannot change the acceptance gate or its result.
    """
    if max_turns is not None and max_turns < 1:
        raise ValueError("--max-turns must be positive")
    index = context_index if allow_discovery else None
    allow_discovery = index is not None
    discovery, context_result = DiscoverySession(index), None
    read_files = {}
    denied_reads = {}
    repair_history = {}
    repair_advice = None
    feedback = [] if feedback is None else [feedback_filter(feedback) if feedback_filter else feedback]
    check_feedback = list(feedback)
    for turn in count(1):
        if max_turns is not None and turn > max_turns:
            raise AgentExhausted(label, max_turns, feedback)
        progress = f"{turn}/{max_turns}" if max_turns is not None else str(turn)
        console.show(f"{label} | Edit round {progress}",
            "Generate file edits, then run the stage's compilation and test acceptance checks.")
        response, applied, checking = None, False, False
        query_history = {}
        try:
            def request_model():
                # Gates may regenerate wiring outside edit_file; discard stale excerpts too.
                for path, excerpts in list(read_files.items()):
                    target = files.path(path)
                    if not target.is_file():
                        read_files.pop(path)
                        continue
                    lines = read_source(target).splitlines(keepends=True)
                    for excerpt in excerpts:
                        content = "".join(lines[excerpt["start_line"] - 1:excerpt["end_line"]])
                        if len(lines) != excerpt["total_lines"] or content != excerpt["content"]:
                            read_files.pop(path)
                            break
                request = {"task": files.task_state(task), "files": files.state(), "feedback": feedback,
                    "context_kinds": list(index.records()) if index is not None else [], "tools": files.schemas()}
                retained = {path: excerpts for path, excerpts in read_files.items()
                    if path not in request["files"] or request["files"][path]["content"] is None}
                if files.readable is not None:
                    request["read_scope"] = {
                        "allowed_paths": sorted(files.readable),
                        "denied_attempts": {
                            path: attempts
                            for path, attempts in denied_reads.items()
                            if path not in files.readable
                        },
                    }                
                if retained:
                    request["read_files"] = retained
                if discovery.evidence:
                    request["context_records"] = discovery.evidence
                if any(discovery.candidates.values()):
                    request["context_candidates"] = discovery.candidates
                conventions = task_conventions(files.output, task)
                if conventions:
                    request["task"]["shared_conventions"] = conventions
                if context_result is not None:
                    compact_result = dict(context_result)
                    kind = compact_result.get("kind")
                    records = compact_result.get("records")
                    retained_records = discovery.evidence.get(kind, {})
                    if (
                        isinstance(records, dict)
                        and records
                        and all(
                            key in retained_records
                            and retained_records[key] == value
                            for key, value in records.items()
                        )
                    ):
                        compact_result.pop("records")
                        compact_result["retained_record_ids"] = list(records)
                        compact_result["records_location"] = "context_records"
                        console.show(
                            f"{label} | Context deduplicated",
                            f"{len(records)} duplicate records removed"
                        )
                    request["context_result"] = compact_result
                rules = instructions + "\n\n" + FILE_TOOL_RULES
                if allow_discovery:
                    rules += "\n\n" + DISCOVERY_RULES
                else:
                    rules += "\nSemantic discovery is disabled for this task. Use supplied evidence and read_file only."
                if files.readable is not None:
                    rules += (
                        "\n\nREAD ACCESS POLICY:"
                        "\nOnly read paths listed in read_scope.allowed_paths."
                        "\nNever retry paths listed in read_scope.denied_attempts."
                        "\nUse the supplied task evidence and permitted files instead."
                        "\nDo not bypass access restrictions."
                        "\nWhen enough evidence is available, produce the required edits."
                    )
                if (
                    context_result is not None
                    and context_result.get("repeated_query_count", 0) >= 2
                    ):
                        rules += (
                            "\n\nREPEATED QUERY DETECTED:"
                            "\nThe last context query provided no new evidence."
                            "\nChoose a different useful action."
                            "\nUse existing evidence whenever sufficient."
                    )
                if repair_advice is not None:
                    request["repair_advice"] = repair_advice
                    rules += (
                        "\n\nADAPTIVE REPAIR:"
                        "\nUse repair_advice to select a valid next action."
                        "\nAvoid repeating previously rejected approaches."
                        "\nPreserve all requirements and acceptance checks."
                    )
                return model.generate_json(rules, request)
            response = request_model()
            while isinstance(response, dict):
                if response.get("context_request") is not None:
                    if not allow_discovery:
                        raise ValueError("Semantic discovery is disabled for this task; use the supplied task evidence and read_file within its allowed scope")
                    query = response["context_request"]
                    console.show(label + " | Context query", json.dumps(query, ensure_ascii=False))
                    if isinstance(query, dict) and query.get("kind") == "file" and "ids" in query:
                        raise ValueError('Use read_file for file content, for example '
                            '{"tool_calls":[{"tool":"read_file","path":"backend/src/db/initialize.ts"}]}. '
                            'context_request discovers semantic records or file candidates.')
                    else:
                        context_result = discovery.resolve(query)
                        query_key = json.dumps(
                            query, sort_keys=True, ensure_ascii=False
                        )
                        result_key = json.dumps(
                            {
                                key: value
                                for key, value in context_result.items()
                                if key != "next_action"
                            },
                            sort_keys=True,
                             ensure_ascii=False,
                        )
                        previous_result, previous_count = query_history.get(
                            query_key, (None, 0)
                        )
                        if previous_result == result_key:
                            repeat_count = previous_count + 1
                        else:
                            repeat_count = 1
                        query_history[query_key] = (result_key, repeat_count)
                        if repeat_count >= 2:
                            context_result = {
                                **context_result,
                                "repeated_query": query,
                                "repeated_query_count": repeat_count,
                                "next_action": (
                                    "This exact query returned unchanged evidence. "
                                    "Do not repeat it. Read a relevant candidate "
                                    "using the permitted tool, search a different "
                                    "missing fact, or produce the required edits."
                                ),
                            }
                            console.show(
                                f"{label} | Redundant context query",
                                f"{query_key} | attempts: {repeat_count}"
                            )
                elif "tool_calls" in response and files.effect(response["tool_calls"]) == "read":
                    calls = response["tool_calls"]
                    console.show(label + " | Read files", str([call["path"] for call in calls]))
                    results = files.execute(calls)
                    observation = {"tool_results": results}
                    for item in results:
                        record = item["result"]
                        excerpts = read_files.setdefault(record["path"], [])
                        # Keep distinct ranges; a wider read replaces excerpts it covers.
                        excerpts[:] = [old for old in excerpts if not (
                            record["start_line"] <= old["start_line"] and record["end_line"] >= old["end_line"])]
                        excerpts.append(record)
                    context_result = {"read_paths": [item["result"]["path"] for item in results]}
                    observed = discovery.observe(observation)
                    if observed.get("next_action"):
                        context_result["next_action"] = observed["next_action"]
                else:
                    break
                response = request_model()
            if isinstance(response, dict) and response.get("diagnosis"):
                console.show(label + " | Failure diagnosis", json.dumps(response["diagnosis"], ensure_ascii=False, indent=2))
            calls = response["tool_calls"]
            results = files.execute(calls)
            for change in files.last_changes:
                read_files.pop(change["path"], None)
            context_result = {"tool_results": results}
            changes = [change for change in files.last_changes if "/tests/" in change["path"]
                and change["before"] is not None and change["before"] != change["after"]]
            if changes:
                audit = files.output / ".arc/test_repairs.jsonl"
                audit.parent.mkdir(parents=True, exist_ok=True)
                with audit.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"task": label, "turn": turn, "diagnosis": response.get("diagnosis"),
                        "feedback": feedback, "changes": changes}, ensure_ascii=False) + "\n")
            applied = True
            if files.pending_target:
                raise ValueError("Create task.file_target with edit_file before running acceptance checks")
            console.show(f"{label} | Edit round {progress}",
                str([change["path"] for change in files.last_changes]))
            checkpoint(files.output, task=label, action=f"Apply file edits in round {turn}", status="PROPOSED",
                details={"round": turn, "files": [change["path"] for change in files.last_changes],
                    "diagnosis": response.get("diagnosis")})
            checking = True
            checks = gate()
            checkpoint(files.output, task=label, action=f"Accept edit round {turn}",
                details={"round": turn, "checks": checks})
            return {"turns": turn, "checks": checks}
        except (*RESPONSE_ERRORS, RuntimeError, OSError) as error:
            if isinstance(error, ModelServiceError):
                raise
            if isinstance(error, RuntimeError) and not applied:
                # The model client already handles transport retries. Re-prompting
                # cannot repair an unavailable endpoint or exhausted provider quota.
                raise
            details = getattr(error, 'feedback', {})
            if (
                isinstance(details, dict)
                and details.get("code") == "READ_NOT_ALLOWED"
            ):
                path = details.get("path")

                if isinstance(path, str):
                    denied_reads[path] = denied_reads.get(path, 0) + 1

                console.show(
                    f"{label} | Forbidden read detected",
                    f"{path} | attempts: {denied_reads[path]}"
                )
            protected_test = details.get('path', '') if isinstance(details, dict) else ''
            if (isinstance(details, dict) and details.get('code') == 'WRITE_NOT_ALLOWED'
                    and protected_test.startswith('frontend/tests/e2e/acceptance/') and test_review is not None):
                changed = test_review(protected_test, check_feedback)
                if changed:
                    try:
                        checks = gate()
                    except (*RESPONSE_ERRORS, RuntimeError, OSError) as reviewed_error:
                        error, applied, checking = reviewed_error, True, True
                    else:
                        checkpoint(files.output, task=label, action='Accept after independent test review',
                            details={'round': turn, 'checks': checks})
                        return {'turns': turn, 'checks': checks}
                else:
                    error = ValueError('Independent review retained the required assertions. '
                        'Repair the application; this implementation task cannot edit acceptance tests.')
            message = str(error)
            console.show(f"{label} | Repair feedback", message)
            rejected = (getattr(error, "feedback", {"error": message}) if applied
                else response_feedback(error, response))
            if protected_test.startswith('frontend/tests/e2e/acceptance/') and isinstance(rejected, dict):
                # The denied patch is not useful repair context and may repeat a whole suite.
                rejected.pop('previous_response', None)
            if isinstance(response, dict) and response.get("diagnosis") and isinstance(rejected, dict):
                rejected = {**rejected, "previous_diagnosis": response["diagnosis"]}
            rejected = feedback_filter(rejected) if feedback_filter else rejected
            repair_advice = None
            if isinstance(rejected, dict):
                error_details = rejected.get("details", {})

                if isinstance(error_details, dict):
                    code = error_details.get("code")
                    path = error_details.get("path", "")

                    recommendations = {
                        "FILE_NOT_FOUND": (
                            "Verify the existing file path or discover "
                            "the correct file before retrying."
                        ),
                        "WRITE_NOT_ALLOWED": (
                            "Do not modify protected files. "
                            "Find a permitted correction or use "
                            "the independent test review mechanism."
                        ),
                        "WHOLE_FILE_REPLACEMENT_NOT_ALLOWED": (
                            "Use a smaller unique replacement span "
                            "and preserve all existing functionality."
                        ),
                    }
                    if code in recommendations:
                        signature = (code, path)
                        attempts = repair_history.get(signature, 0) + 1
                        repair_history[signature] = attempts

                        repair_advice = {
                            "error_code": code,
                            "path": path,
                            "occurrences": attempts,
                            "recommended_action": recommendations[code],
                        }

                        if attempts >= 2:
                            repair_advice["instruction"] = (
                                "This error has occurred before. "
                                "Reassess the previous approach and "
                                "choose a different valid action."
                            )
                        console.show(
                            f"{label} | Adaptive repair",
                            str(repair_advice)
                        )
            if checking:
                check_feedback = [rejected]
                feedback = list(check_feedback)
            else:
                feedback = [*check_feedback, rejected]
            checkpoint(files.output, task=label, action=f"Reject edit round {turn}", status="REJECTED",
                details={"round": turn, "applied": applied, "feedback": feedback})
