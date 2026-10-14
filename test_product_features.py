import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from demo import build_demo
from storage import stamp, save_document
from matching import DEFAULT_WEIGHTS, save_weights, load_weights, rank, service_match
from staff_research import extract_staff
from extended_audits import audit_links, parse_performance, audit_crux, load_reports, report_path, get_report
from app import Workspace, CollectionCancelled


class ProductFeatures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = build_demo(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_staff_suggestions_require_explicit_names_roles_and_sources(self):
        page = {'url': 'https://example.com/team', 'text': '<h2>Our Team</h2><p>Partner with us</p><div class="staff-card"><h3>Jane Smith</h3><p>Operations Manager</p><a href="mailto:jane@example.com">Email</a></div><script>John Jones CEO</script>'}
        people = extract_staff(page, stamp())
        self.assertEqual([(p['name'], p['role']) for p in people], [('Jane Smith', 'Operations Manager')])
        self.assertEqual(people[0]['email'], 'jane@example.com')
        self.assertEqual(people[0]['verification'], 'observed_staff_text_unreviewed')
        self.assertEqual(people[0]['source_url'], page['url'])

    def test_weights_persist_and_normalize_only_applicable_factors(self):
        weights = {k: 0 for k in DEFAULT_WEIGHTS}
        weights.update(relevance=20, observed_need=80)
        save_weights(self.workspace.directory, {'weights': weights})
        self.assertEqual(load_weights(self.workspace.directory), weights)
        self.assertEqual(rank({'relevance': 1}, weights, 'providers')[0], 100)
        self.assertEqual(rank({'relevance': 1}, weights, 'prospects')[0], 20)
        with self.assertRaises(ValueError):
            save_weights(self.workspace.directory, {'weights': {k: False for k in weights}})
        self.assertEqual(service_match('accounting payroll', 'Accounting tax'), (0.5, ['accounting']))

    def test_stale_organization_revision_cannot_overwrite_review(self):
        payload = {'id': 'demo:legal', 'organization_type': 'business', 'source_url': 'https://example.com', 'observed_at': stamp(), 'excerpt': 'Public services'}
        first = self.workspace.save_organization(payload)
        self.workspace.save_organization({**payload, 'expected_revision': first['revision'], 'services': 'Tax'})
        with self.assertRaises(ValueError):
            self.workspace.save_organization({**payload, 'expected_revision': first['revision'], 'services': 'Stale'})
        self.assertEqual(self.workspace.intelligence_detail('demo:legal')['review']['services'], 'Tax')

    def test_edit_contact_keeps_identity_and_rejects_stale_or_wrong_business(self):
        payload = {'business_id': 'demo:legal', 'name': 'Jane Smith', 'role': 'Partner', 'source_url': 'https://example.com/team', 'observed_at': stamp(), 'excerpt': 'Jane Smith, Partner'}
        first = self.workspace.save_person(payload)
        edit = {**payload, 'id': first['id'], 'expected_revision': first['revision'], 'role': 'Managing Partner'}
        saved = self.workspace.save_person(edit)
        self.assertEqual(saved['id'], first['id'])
        with self.assertRaises(ValueError):
            self.workspace.save_person(edit)
        with self.assertRaises(KeyError):
            self.workspace.save_person({**edit, 'business_id': 'demo:school'})

    def test_query_planner_explicit_filters_override_and_failure_falls_back(self):
        with patch('intelligence.plan_query', return_value=({'intent': 'partners', 'segment': 'legal'}, {'input_tokens': 10})):
            result = self.workspace.answer_question({'question': 'legal', 'use_ai_plan': True, 'intent': 'providers'})
            self.assertEqual(result['query']['intent'], 'providers')
            self.assertEqual(result['query']['segment'], 'legal')
            self.assertEqual(result['metrics']['model_requests'], 1)
        with patch('intelligence.plan_query', side_effect=ValueError('Unavailable')):
            result = self.workspace.answer_question({'question': 'legal', 'use_ai_plan': True})
            self.assertEqual(result['query_plan_error'], 'Unavailable')
            self.assertTrue(result['results'])
        with patch('intelligence.plan_query') as planner:
            with self.assertRaises(ValueError):
                self.workspace.answer_question({'question': 'legal', 'use_ai_plan': True, 'use_ai': 'yes'})
            planner.assert_not_called()

    def test_link_sample_distinguishes_missing_from_temporary_failure(self):
        crawler = Mock()
        crawler.page.return_value = {'url': 'https://example.com/', 'status': 200, 'headers': {'content-type': 'text/html'}, 'truncated': False, 'text': '<a href="/missing">A</a><a href="/busy">B</a><a href="https://other.example/">C</a>'}
        crawler.fetcher.get.side_effect = [{'status': 404}, {'status': 503}]
        report = audit_links('https://example.com/', crawler)
        self.assertEqual(report['missing_count'], 1)
        self.assertEqual([r['outcome'] for r in report['links']], ['missing', 'inconclusive'])
        self.assertEqual(crawler.fetcher.get.call_count, 2)

    def test_lab_scores_and_field_data_remain_distinct(self):
        value = {'lighthouseResult': {'categories': {'performance': {'score': .74}}, 'audits': {'largest-contentful-paint': {'numericValue': 2600, 'displayValue': '2.6 s', 'score': .5}}, 'finalUrl': 'https://example.com/'}, 'loadingExperience': {'metrics': {'LARGEST_CONTENTFUL_PAINT_MS': {'percentile': 1800}}}}
        report = parse_performance(value, 'https://example.com/', 'mobile')
        self.assertEqual(report['categories']['performance'], 74)
        self.assertEqual(report['lab_metrics'][0]['numeric_value'], 2600)
        self.assertEqual(report['field_data']['page']['metrics']['LARGEST_CONTENTFUL_PAINT_MS']['percentile'], 1800)
        with self.assertRaises(ValueError):
            parse_performance({'lighthouseResult': {'runtimeError': {'code': 'FAILED'}}}, 'https://example.com/', 'mobile')

    def test_field_requires_credentials_and_checks_public_target_first(self):
        with patch('extended_audits.public_address', side_effect=ValueError('Private target')), patch('extended_audits.urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'Private target'):
                audit_crux('https://example.com/')
            network.assert_not_called()
        with patch('extended_audits.public_address'), patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'CRUX_API_KEY'):
                audit_crux('https://example.com/')

    def test_extra_reports_persist_and_interrupted_worker_is_visible(self):
        identity = 'demo:legal'
        save_document(report_path(self.workspace, 'links', identity), {'status': 'complete', 'missing_count': 2})
        self.assertEqual(load_reports(self.workspace.directory, [identity])[identity]['links']['missing_count'], 2)
        save_document(report_path(self.workspace, 'field', identity), {'status': 'running'})
        self.assertEqual(get_report(self.workspace, 'field', identity)['status'], 'interrupted')

    def test_collection_restart_preserves_directory_and_marks_interrupted(self):
        save_document(self.workspace.collection_job_file, {'status': 'running', 'mode': 'collect', 'log': 'Saved progress'})
        restarted = Workspace(self.workspace.directory)
        self.assertEqual(restarted.job_status()['status'], 'interrupted')
        self.assertEqual(len(restarted.rows), len(self.workspace.rows))
        with patch.object(restarted, 'start_job', return_value={'status': 'running'}) as start:
            restarted.resume_collection()
            start.assert_called_once_with('collect')

    def test_cancel_collector_terminates_only_its_child(self):
        process = Mock()
        process.poll.return_value = None
        self.workspace.collection_cancel.set()
        with patch('app.subprocess.Popen', return_value=process):
            with self.assertRaises(CollectionCancelled):
                self.workspace._execute_collector(['collector'], Mock())
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    def test_query_planner_rejects_invented_neighborhood(self):
        from intelligence import plan_query
        value = {'intent': 'providers', 'segment': '', 'organization_type': '', 'category': '', 'neighborhood': 'Invented', 'desired_services': '', 'partner_services': '', 'require_contact': False, 'require_decision_maker': False, 'require_website_issue': False}
        with patch('intelligence.model_json', return_value=(value, {})):
            with self.assertRaisesRegex(ValueError, 'unsupported filter'):
                plan_query('Find services', {'categories': [], 'neighborhoods': ['North Shore']})


if __name__ == '__main__':
    unittest.main()
