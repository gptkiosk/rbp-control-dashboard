import json
import tempfile
import unittest
import unittest.mock
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
            self.assertIn(f'action=verify cwd={root.resolve()}', result['output'])
            self.assertIsNone(result['proxy_url'])

    def test_dashboard_managed_persistent_preview_title_is_a_review_action(self):
        manifest = {'document': {'nodes': [{'title': 'Start dashboard-managed persistent preview for remote review'}]}}
        self.assertEqual(project_preview._kind(manifest['document']['nodes'][0]), 'preview-review')

    def test_preview_uses_the_story_workspace_inside_the_approved_project_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / 'site'; (nested / 'tools').mkdir(parents=True)
            (nested / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\nprintf "action=%s cwd=%s\\n" "$1" "$PWD"\n', encoding='utf-8')
            card = SimpleNamespace(working_dir=str(nested))
            result = project_preview.run(project(root, 'Start dashboard-managed persistent preview for remote review'), card, SimpleNamespace(node_key='preview'), 'serve', proxy_base='/api/preview')
            self.assertTrue(result['ok'])
            self.assertIn(f'action=serve cwd={nested.resolve()}', result['output'])

    def test_human_preview_finds_a_direct_child_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / 'site'; (nested / 'tools').mkdir(parents=True)
            (nested / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\nprintf "action=%s cwd=%s\\n" "$1" "$PWD"\n', encoding='utf-8')
            result = project_preview.run(project(root, 'Start dashboard-managed persistent preview for remote review'), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'serve', proxy_base='/api/preview')
            self.assertTrue(result['ok'])
            self.assertIn(f'action=serve cwd={nested.resolve()}', result['output'])

    def test_preview_story_does_not_accept_arbitrary_host_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / 'tools'; tools.mkdir()
            (tools / 'verify-preview.sh').write_text('#!/usr/bin/env bash\n', encoding='utf-8')
            with self.assertRaisesRegex(Exception, 'not approved'):
                project_preview.run(project(root, 'Start the persistent loopback preview for review'), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'verify', proxy_base='/api/preview')


class PreviewHostPathTest(unittest.TestCase):
    """Pilot 2026-10-29: the verifier's `node` call failed on a host that had Node.js from Agent tools, because the action ran on the service's bare PATH."""

    def test_the_verifier_gets_the_tool_folders_agents_get(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            managed = root / 'managed'; (managed / 'tools' / 'node' / 'current' / 'bin').mkdir(parents=True)
            fake = managed / 'tools' / 'node' / 'current' / 'bin' / 'node'
            fake.write_text('#!/bin/sh\necho managed-node\n'); fake.chmod(0o755)
            site = root / 'site'; (site / 'tools').mkdir(parents=True)
            (site / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\nnode\n', encoding='utf-8')
            with unittest.mock.patch.dict('os.environ', {'MAC_CONTROL_AGENT_TOOLS_ROOT': str(managed), 'PATH': '/usr/bin:/bin'}):
                result = project_preview.run(project(site), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'verify', proxy_base='/api/preview')
            self.assertTrue(result['ok'], result['output'])
            self.assertIn('managed-node', result['output'])

    def test_a_missing_node_is_named_with_where_to_get_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            (root / 'tools' / 'verify-preview.sh').write_text(
                "#!/usr/bin/env bash\necho \"FileNotFoundError: [Errno 2] No such file or directory: 'node'\" >&2\nexit 1\n", encoding='utf-8')
            result = project_preview.run(project(root), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'verify', proxy_base='/api/preview')
            self.assertFalse(result['ok'])
            self.assertIn('node is not installed where this host action can run it. Install Node.js from Agent tools', result['output'])
