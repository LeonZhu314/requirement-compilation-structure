from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import yaml

from infrastructure.runtime.config import DEFAULT_PROFILE, load_profile


class ProfileTests(unittest.TestCase):
    def test_env_precedence_and_secrets_not_in_repr_or_process(self):
        before = dict(os.environ)
        with TemporaryDirectory() as tmp:
            env = Path(tmp) / '.env'
            env.write_text('MODEL=file-model\nOPENAI_API_KEY=file-secret\nVISUAL_MODEL=vision\n')
            profile = load_profile(env_file=env, environment={'MODEL': 'env-model', 'OPENAI_API_KEY': 'env-secret'},
                overrides={'model': 'explicit-model'})
            self.assertEqual(profile.llm.model, 'explicit-model')
            self.assertEqual(profile.llm.api_key, 'env-secret')
            self.assertEqual(profile.vision.model, 'vision')
            self.assertNotIn('env-secret', repr(profile))
            self.assertEqual(load_profile(env_file=env, environment={'OPENAI_API_KEY': ''}).llm.api_key, '')
        self.assertEqual(dict(os.environ), before)

    def test_unknown_keys_unsupported_capabilities_and_tools_fail(self):
        mutations = [lambda d: d.update(typo=True), lambda d: d['llm'].update(modle='wrong'),
            lambda d: d['loop'].update(max_requests=-1), lambda d: d['loop'].update(max_requests=True),
            lambda d: d['capabilities'].update(images=False), lambda d: d['capabilities'].update(streaming='false'),
            lambda d: d.update(tools=['run_shell']), lambda d: d.update(tools=['read_file', 'read_file']),
            lambda d: d['instructions'].update(role='../outside.md')]
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.yaml'
            for source in ('role.md', 'workflow.md'):
                (p.parent / source).write_text('instructions')
            for mutate in mutations:
                data = yaml.safe_load(DEFAULT_PROFILE.read_text())
                mutate(data)
                p.write_text(yaml.safe_dump(data))
                with self.assertRaises(ValueError):
                    load_profile(p, environment={})

    def test_profile_loads_without_cwd_env_discovery(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / '.env').write_text('MODEL=should-not-be-loaded\n')
            original = Path.cwd()
            try:
                os.chdir(p)
                profile = load_profile(environment={})
            finally:
                os.chdir(original)
            self.assertEqual(profile.llm.model, 'deepseek-flash')
            self.assertIn('read_file', profile.tools)
            self.assertIn('browser', profile.tools)
            self.assertEqual(profile.execution.backend, 'host')

    def test_visual_settings_and_legacy_names_are_scoped(self):
        profile = load_profile(environment={'MODEL': 'main', 'MODEL_REASONING': 'high',
            'OPENAI_API_KEY': 'main-key', 'MAX_OUTPUT_TOKENS': '1234', 'VISUAL_MODEL': 'vision',
            'VISUAL_API_KEY': 'vision-key', 'VISUAL_REASONING': 'low', 'VISUAL_BASE_URL': 'https://vision.invalid/v1'})
        self.assertEqual(profile.llm.max_output_tokens, 1234)
        self.assertEqual(profile.vision.reasoning, 'low')
        self.assertEqual(profile.llm.reasoning, 'high')
        self.assertEqual(profile.vision.api_key, 'vision-key')
