import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from demo import build_demo
from app_settings import save, status
from storage import save_document


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = build_demo(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_normal_launch_cannot_enable_local_experiment(self):
        with self.assertRaisesRegex(ValueError, '--local-ai-test'):
            save(self.workspace, {'ai_mode': 'local_test', 'simple_navigation': True})

    def test_local_setting_requires_explicit_launch_even_after_restart(self):
        self.workspace.local_ai_test_enabled = True
        with patch('local_ai.installed', return_value=True):
            value = save(self.workspace, {'ai_mode': 'local_test', 'simple_navigation': True})
            self.assertTrue(value['ai_available'])
            self.workspace.local_ai_test_enabled = False
            self.assertFalse(status(self.workspace)['ai_available'])
            with patch('local_ai.generate') as model:
                answer = self.workspace.answer_question({'question': 'legal', 'use_ai': True})
                model.assert_not_called()
                self.assertTrue(answer['results'])
                self.assertIn('unavailable', answer['ai_error'])

    def test_off_does_not_call_cloud_and_settings_do_not_expose_keys(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'private', 'VICALL_AI_MODEL': 'test'}):
            value = save(self.workspace, {'ai_mode': 'off', 'simple_navigation': False})
            self.assertNotIn('private', str(value))
            with patch('intelligence.generate_answer') as model:
                answer = self.workspace.answer_question({'question': 'legal', 'use_ai': True})
                model.assert_not_called()
                self.assertIn('turned off', answer['ai_error'])

    def test_local_uses_existing_citation_validation_and_never_cloud_planning(self):
        self.workspace.local_ai_test_enabled = True
        save(self.workspace, {'ai_mode': 'local_test', 'simple_navigation': True})
        with patch('intelligence.plan_query') as planner:
            answer = self.workspace.answer_question({'question': 'legal', 'use_ai_plan': True})
            planner.assert_not_called()
            self.assertIn('requires cloud', answer['query_plan_error'])
        with patch('local_ai.generate', return_value=({'recommendations': [{'business_id': 'invented', 'evidence_ids': ['bad'], 'interpretation': 'Unsupported'}], 'unknowns': []}, {})):
            answer = self.workspace.answer_question({'question': 'legal', 'use_ai': True})
            self.assertIsNone(answer['ai'])
            self.assertTrue(answer['results'])

    def test_invalid_settings_do_not_save(self):
        for payload in ({'ai_mode': 'arbitrary', 'simple_navigation': True}, {'ai_mode': 'off', 'simple_navigation': 'yes'}):
            with self.assertRaises(ValueError):
                save(self.workspace, payload)
