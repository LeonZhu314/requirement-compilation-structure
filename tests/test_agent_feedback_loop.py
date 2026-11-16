"""Faster feedback from a real run (2026-11-17): the host's tests on demand, generated in parallel."""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from infrastructure.runtime.messages import ModelResponse
from infrastructure.runtime.model import ScriptedModel
from infrastructure.verification.acceptance import AUTHOR
from tests.verification_support import GENERATED, REQUIREMENTS, call, make_agent, tools, write_input


class FeedbackLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_the_agent_runs_the_host_acceptance_tests_itself_and_gets_precise_failures(self):
        model = ScriptedModel([tools(call('write_file', 'w', path='behaviors.txt', content='SCN-A-1\n')),
            tools(call('run_acceptance_tests', 'first')),
            tools(call('write_file', 'w2', path='behaviors.txt', content='SCN-A-1 SCN-A-2\n')),
            tools(call('run_acceptance_tests', 'second')), ModelResponse('Done.')])
        agent, tooling, _ = make_agent(self.root, model, generate=False)
        async with agent:
            outcome = await agent.generate(tooling=tooling)
            results = {m.tool_call_id: json.loads(m.content)['result'] for m in agent.state.messages if m.role == 'tool'}
            events = agent.store.events()
        first, second = results['first'], results['second']
        self.assertEqual(first['status'], 'failed')
        self.assertIn('SCN-A-2', first['report'])
        self.assertNotIn('page.goto', first['report'])                       # Symptoms, never the test source.
        self.assertEqual(second['status'], 'passed')
        self.assertIn('completion summary', second['report'])
        # Each verification step is reported while it runs, not only at the end.
        texts = [e['data']['text'] for e in events if e['kind'] == 'verification']
        for expected in ('round 1 started', 'running 1 test files', 'acceptance: failed', 'acceptance: passed'):
            self.assertTrue(any(expected in text for text in texts), (expected, texts))
        # The final acceptance is still the host's own clean round after the proposal.
        self.assertEqual(outcome.status, 'accepted')
        self.assertTrue(agent.state.verifications[-1]['clean_state'])

    async def test_manual_checks_after_a_passing_build_earn_one_reminder(self):
        agent, _, _ = make_agent(self.root, ScriptedModel([]))
        async with agent:
            async def runner():
                return {'status': 'passed'}
            registry = agent.tools
            registry.acceptance_runner = runner
            before = (await registry.execute(call('run_command', command=['node', '-e', '1']))).value
            self.assertNotIn('reminder', before)                              # The build has not passed yet.
            await registry.execute(call('verify_application', kind='all'))
            reminders = []
            for _ in range(8):
                result = (await registry.execute(call('run_command', command=['node', '-e', '1']))).value
                reminders.append('reminder' in result)
            self.assertEqual(reminders, [False] * 5 + [True] + [False] * 2)
            self.assertIn('run_acceptance_tests', [s['function']['name'] for s in registry.schemas()])

    async def test_generated_tests_are_written_concurrently(self):
        requirements = {**REQUIREMENTS, 'children': [*REQUIREMENTS['children'],
            *({'id': f'REQ-{index}', 'name': f'Part {index}', 'description': 'Part.', 'scenarios': [
                {'id': f'SCN-{index}-1', 'steps': [{'id': f'ST-{index}', 'Given': 'g', 'When': 'w', 'Then': 't'}]}]}
              for index in range(3))]}
        log = []

        class Slow(ScriptedModel):
            async def respond(self, messages, schemas):
                if messages[0].content.startswith('Write independent acceptance tests'):
                    scenarios = json.loads(messages[1].content)['scenarios_to_cover']
                    log.append(time.monotonic())
                    await asyncio.sleep(0.3)
                    body = ''.join(f"test('{sid}: generated', async ({{ page }}) => {{ await page.goto('/'); }});\n"
                        for sid in scenarios)
                    return ModelResponse(f"```ts\nimport {{ test, expect }} from '@playwright/test';\n{body}```")
                return await super().respond(messages, schemas)
        model = Slow([ModelResponse('Done.')])
        agent, tooling, _ = make_agent(self.root, model, requirements=requirements, generate=True)
        async with agent:
            await agent.generate(tooling=tooling)
        self.assertEqual(len(log), 4)                                         # REQ-B and three parts.
        self.assertLess(max(log) - min(log), 0.25)                            # Started together, not one by one.

    def test_generated_tests_do_not_invent_navigation(self):
        self.assertIn('Assert a URL, redirect target or route only when the requirement states it', AUTHOR)
        self.assertTrue(GENERATED and write_input)


if __name__ == '__main__':
    unittest.main()
