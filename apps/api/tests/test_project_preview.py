import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import project_preview


def project(root: Path, title='Run the preview verifier once'):
    return SimpleNamespace(approved_manifest=json.dumps({'document': {'working_dir': str(root), 'nodes': [{'key': 'preview', 'title': title}]}}))


class PreviewActionsTest(unittest.TestCase):
    def test_dashboard_runs_only_the_fixed_preview_verifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'tools'; tools.mkdir()
            (tools / 'verify-preview.sh').write_text('#!/usr/bin/env bash\nprintf "action=%s cwd=%s\\n" "$1" "$PWD"\n', encoding='utf-8')
            result = project_preview.run(project(root), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'verify', proxy_base='/api/preview')
            self.assertTrue(result['ok'])
            self.assertEqual(result['exit_code'], 0)
            self.assertIn(f'action=verify cwd={root}', result['output'])
            self.assertIsNone(result['proxy_url'])

    def test_preview_story_does_not_accept_arbitrary_host_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'tools'; tools.mkdir()
            (tools / 'verify-preview.sh').write_text('#!/usr/bin/env bash\n', encoding='utf-8')
            with self.assertRaisesRegex(Exception, 'not approved'):
                project_preview.run(project(root, 'Start the persistent loopback preview for review'), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'verify', proxy_base='/api/preview')
