import json
import os
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
            self.assertIn(f'action=serve cwd={nested.resolve()}', result['output'])

    def test_human_preview_finds_a_direct_child_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / 'site'; (nested / 'tools').mkdir(parents=True)
            (nested / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\nprintf "action=%s cwd=%s\\n" "$1" "$PWD"\n', encoding='utf-8')
            result = project_preview.run(project(root, 'Start dashboard-managed persistent preview for remote review'), SimpleNamespace(), SimpleNamespace(node_key='preview'), 'serve', proxy_base='/api/preview')
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


LOOPBACK_SERVER = """from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer resolves a cosmetic server_name through reverse DNS.
        # A loopback-only fixture must not depend on the runner's DNS service.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


with LoopbackHTTPServer(('127.0.0.1', 41390), SimpleHTTPRequestHandler) as server:
    server.serve_forever()
"""


SERVE_SCRIPT = r"""#!/usr/bin/env bash
set -eu
mkdir -p .preview
case "$1" in
  verify) echo verified ;;
  serve)
    nohup python3 tools/fixture_http_server.py > .preview/server.log 2>&1 < /dev/null &
    pid=$!
    for _ in $(seq 50); do python3 -c "import socket;socket.create_connection(('127.0.0.1',41390),1)" 2>/dev/null && break; sleep 0.1; done
    printf '{"pid": %s, "port": 41390, "source_sha": "%s", "status": "running"}' "$pid" "$(printf x | shasum -a 256 | cut -c1-64)" > .preview/preview.state ;;
  stop)
    kill "$(python3 -c "import json;print(json.load(open('.preview/preview.state'))['pid'])")"
    rm -f .preview/preview.state ;;
esac
"""


def review_project(root: Path):
    return SimpleNamespace(approved_manifest=json.dumps({'document': {'working_dir': str(root), 'nodes': [
        {'key': 'verify', 'host_action': 'preview-verify', 'title': 'Verify'},
        {'key': 'review', 'host_action': 'preview-review', 'title': 'Review'}]}}))


class PreviewServeContractTest(unittest.TestCase):
    """Pilot 2026-10-29: Start ran the verifier (which stops its server) and the script wrote JSON state, so Open remote preview never appeared."""

    def test_a_json_state_file_with_a_sha256_is_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / '.preview').mkdir()
            (root / '.preview' / 'preview.state').write_text(json.dumps({'pid': os.getpid(), 'port': 41352, 'source_sha': 'a' * 64, 'status': 'running'}))
            self.assertEqual(project_preview._state(root)['sha'], 'a' * 64)
            (root / '.preview' / 'preview.state').write_text(json.dumps({'pid': os.getpid(), 'port': 41352, 'source_sha': 'a' * 64, 'status': 'stopped'}))
            self.assertIsNone(project_preview._state(root))
            (root / '.preview' / 'preview.state').write_text(f'pid={os.getpid()}\nport=41352\nsha={"b" * 40}\n')
            self.assertEqual(project_preview._state(root)['port'], 41352)

    def test_serve_that_leaves_nothing_running_fails_and_names_the_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            (root / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\necho "ran verify whatever was asked"\n')
            result = project_preview.run(review_project(root), SimpleNamespace(), SimpleNamespace(node_key='review'), 'serve', proxy_base='/p')
            self.assertFalse(result['ok'])
            self.assertIsNone(result['proxy_url'])
            self.assertIn('nothing to open', result['output'])
            self.assertIn('stop: stop only the PID', result['output'])

    def test_verify_fails_when_the_plan_has_a_review_and_serve_does_not_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            (root / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\necho "verify only"\n')
            result = project_preview.run(review_project(root), SimpleNamespace(), SimpleNamespace(node_key='verify'), 'verify', proxy_base='/p')
            self.assertFalse(result['ok'])
            self.assertEqual(result['exit_code'], 0)
            self.assertIn('Start/Stop check failed', result['output'])

    def test_a_contract_script_passes_verify_and_serves_through_the_proxy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            (root / 'tools' / 'verify-preview.sh').write_text(SERVE_SCRIPT)
            (root / 'tools' / 'fixture_http_server.py').write_text(LOOPBACK_SERVER)
            (root / 'index.html').write_text('<h1>hi</h1>')
            result = project_preview.run(review_project(root), SimpleNamespace(), SimpleNamespace(node_key='verify'), 'verify', proxy_base='/p')
            server_log = root / '.preview' / 'server.log'
            diagnostics = server_log.read_text(errors='replace') if server_log.exists() else '(no synthetic server log)'
            self.assertTrue(result['ok'], result['output'] + '\nSynthetic server log:\n' + diagnostics)
            self.assertIn('Start/Stop check passed', result['output'])
            self.assertIsNone(project_preview._state(root))
            started = project_preview.run(review_project(root), SimpleNamespace(), SimpleNamespace(node_key='review'), 'serve', proxy_base='/p')
            try:
                self.assertTrue(started['ok'], started['output'])
                self.assertEqual(started['proxy_url'], '/p/index.html')
                status, body, _ = project_preview.proxy(root, 'index.html')
                self.assertEqual((status, body), (200, b'<h1>hi</h1>'))
            finally:
                stopped = project_preview.run(review_project(root), SimpleNamespace(), SimpleNamespace(node_key='review'), 'stop', proxy_base='/p')
            self.assertTrue(stopped['ok'], stopped['output'])
            self.assertIsNone(stopped['proxy_url'])

    def test_a_serve_that_never_returns_is_stopped_at_the_check_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            (root / 'tools' / 'verify-preview.sh').write_text('#!/usr/bin/env bash\n[ "$1" = serve ] && exec sleep 60\necho ok\n')
            with unittest.mock.patch.object(project_preview, 'SMOKE_TIMEOUT', 1):
                result = project_preview.run(review_project(root), SimpleNamespace(), SimpleNamespace(node_key='verify'), 'verify', proxy_base='/p')
            self.assertFalse(result['ok'])
            self.assertIn('did not return within 1 seconds', result['output'])
