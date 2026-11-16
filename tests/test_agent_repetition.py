
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from infrastructure.shared.agent.loop import run_file_agent
from infrastructure.shared.agent.tools import FileTools
from infrastructure.shared.agent.discovery import ContextIndex


class AgentRepetitionTests(unittest.TestCase):

    @patch("infrastructure.shared.agent.loop.checkpoint")
    def test_forbidden_reads_are_remembered(self, checkpoint):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            (root / "forbidden_a.ts").write_text("private A")
            (root / "forbidden_b.ts").write_text("private B")

            files = FileTools(
                root,
                writable=["fix.ts"],
                readable=["fix.ts"],
            )

            model = Mock()
            model.generate_json.side_effect = [
                {"tool_calls": [
                    {"tool": "read_file", "path": "forbidden_a.ts"}
                ]},
                {"tool_calls": [
                    {"tool": "read_file", "path": "forbidden_b.ts"}
                ]},
                {"tool_calls": [
                    {"tool": "read_file", "path": "forbidden_a.ts"}
                ]},
                {"tool_calls": [
                    {
                        "tool": "edit_file",
                        "path": "fix.ts",
                        "operation": "create",
                        "new_content": "export const fixed = true;",
                    }
                ]},
            ]

            gate = Mock(return_value={"green": True})

            run_file_agent(
                model, "", {}, files, gate,
                5, Mock(), "forbidden-read-test"
            )

            first_request = (
                model.generate_json.call_args_list[0].args[1]
            )
            last_request = (
                model.generate_json.call_args_list[-1].args[1]
            )

            self.assertEqual(
                first_request["read_scope"]["allowed_paths"],
                ["fix.ts"]
            )

            self.assertEqual(
                last_request["read_scope"]["denied_attempts"],
                {"forbidden_a.ts": 2, "forbidden_b.ts": 1}
            )

            self.assertTrue((root / "fix.ts").is_file())
            gate.assert_called_once()

    @patch("infrastructure.shared.agent.loop.checkpoint")
    def test_repeated_query_is_detected(self, checkpoint):
        with tempfile.TemporaryDirectory() as directory:
            query = {
                "kind": "file",
                "query": "set-cookie",
            }

            index = ContextIndex({
                "file": {
                    "backend/session.ts": {
                        "description": "set-cookie session"
                    }
                }
            })

            model = Mock()
            model.generate_json.side_effect = [
                {"context_request": query},
                {"context_request": query},
                {"tool_calls": []},
            ]

            gate = Mock(return_value={"green": True})

            run_file_agent(
                model, "", {},
                FileTools(Path(directory)),
                gate, 3, Mock(), "duplicate-query-test",
                context_index=index,
            )

            last_request = (
                model.generate_json.call_args_list[-1].args[1]
            )

            result = last_request["context_result"]

            self.assertEqual(
                result["repeated_query_count"], 2
            )
            self.assertEqual(
                result["repeated_query"], query
            )
            gate.assert_called_once()

    @patch("infrastructure.shared.agent.loop.checkpoint")
    def test_changed_evidence_is_not_a_repetition(self, checkpoint):
        with tempfile.TemporaryDirectory() as directory:
            records = {
                "file": {
                    "backend/session.ts": {
                        "description": "set-cookie session"
                    }
                }
            }

            query = {
                "kind": "file",
                "query": "set-cookie",
            }

            def updated_query(*args):
                records["file"]["backend/login.ts"] = {
                    "description": "set-cookie login"
                }
                return {"context_request": query}

            responses = iter([
                lambda *args: {"context_request": query},
                updated_query,
                lambda *args: {"tool_calls": []},
            ])

            model = Mock()
            model.generate_json.side_effect = (
                lambda *args: next(responses)(*args)
            )

            gate = Mock(return_value={"green": True})

            run_file_agent(
                model, "", {},
                FileTools(Path(directory)),
                gate, 3, Mock(), "new-evidence-test",
                context_index=ContextIndex(records),
            )

            last_request = (
                model.generate_json.call_args_list[-1].args[1]
            )

            self.assertNotIn(
                "repeated_query_count",
                last_request["context_result"]
            )

            gate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
