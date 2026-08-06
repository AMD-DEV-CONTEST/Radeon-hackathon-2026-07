from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.episode_factory.radeon_cloud_execution import JOB_SCHEMA, RadeonCloudJob, build_cloud_package, execute_cloud_package
from tools.episode_factory.radeon_cloud_session import CommandProvider, DirectPythonProvider, ProviderRegistry, RadeonCloudSession, SharedDirectoryTransport, load_session, save_session
from tools.episode_factory.rendering_engine import ExecutionPlan


class RadeonCloudSessionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.session = RadeonCloudSession('direct-python', str(self.workspace), remote_reference='attached-radeon-cloud')

    def tearDown(self):
        self.temporary.cleanup()

    def test_session_identity_is_deterministic(self):
        same = RadeonCloudSession('direct-python', str(self.workspace), remote_reference='attached-radeon-cloud')
        self.assertEqual(self.session.session_id, same.session_id)

    def test_session_round_trip_is_verified(self):
        path = save_session(self.root / 'session.json', self.session)
        self.assertEqual(load_session(path), self.session)

    def test_invalid_transition_fails(self):
        with self.assertRaisesRegex(ValueError, 'invalid session transition'):
            self.session.transition('completed')

    def test_valid_lifecycle(self):
        value = self.session.transition('ready').transition('running').transition('completed').transition('closed')
        self.assertEqual(value.state, 'closed')

    def test_provider_registry_is_explicit(self):
        registry = ProviderRegistry.defaults()
        self.assertEqual(registry.resolve('direct-python').name, 'direct-python')
        with self.assertRaisesRegex(ValueError, 'unknown'):
            registry.resolve('missing')

    def test_direct_python_provider_builds_job(self):
        job = DirectPythonProvider().build_job({'script': 'render.py', 'arguments': ['--output', '../outputs']})
        self.assertEqual(job.argv[:2], ('python3', 'render.py'))

    def test_command_provider_is_shell_free(self):
        job = CommandProvider().build_job({'argv': ['python3', '-c', 'print(1)']})
        self.assertNotIn('shell', job.as_dict())

    def test_duplicate_provider_fails(self):
        registry = ProviderRegistry()
        registry.register(DirectPythonProvider())
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            registry.register(DirectPythonProvider())

    def package(self) -> Path:
        script = self.root / 'render.py'
        script.write_text("from pathlib import Path\no=Path('../outputs');o.mkdir();(o/'frame.txt').write_text('ok\\n')\n", encoding='utf-8')
        plan = ExecutionPlan(specification_id='b' * 64, backend='radeon-cloud', model={'id': 'test'}, resolved_request={'seed': 11}, output_contract={'formats': ['txt']})
        job = RadeonCloudJob.from_mapping({'schema_version': JOB_SCHEMA, 'argv': ['python3', 'render.py'], 'environment': {}, 'working_directory': 'payload', 'output_paths': ['outputs'], 'timeout_seconds': 10})
        return build_cloud_package(execution_plan=plan, job=job, payload_files={'payload/render.py': script}, destination=self.root / 'package.tar.gz')

    def test_stage_is_idempotent_and_resumable(self):
        transport = SharedDirectoryTransport()
        package = self.package()
        first = transport.stage_package(self.session, package)
        second = transport.stage_package(self.session, package)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(second.resumed_from_bytes, package.stat().st_size)

    def test_partial_stage_resumes(self):
        transport = SharedDirectoryTransport()
        package = self.package()
        from tools.episode_factory.radeon_cloud_execution import inspect_cloud_package
        package_id = inspect_cloud_package(package)['package_id']
        destination = self.workspace / 'aahj-inbox' / f'{package_id}.tar.gz'
        destination.parent.mkdir(parents=True)
        destination.write_bytes(package.read_bytes()[:31])
        receipt = transport.stage_package(self.session, package)
        self.assertEqual(receipt.resumed_from_bytes, 31)
        self.assertEqual(destination.read_bytes(), package.read_bytes())

    def test_result_collection_is_verified(self):
        package = self.package()
        cloud_result = self.workspace / 'cloud-result'
        execute_cloud_package(package, result_directory=cloud_result, require_radeon=False)
        destination = self.root / 'downloaded'
        transport = SharedDirectoryTransport()
        first = transport.collect_result(self.session, Path('cloud-result'), destination)
        second = transport.collect_result(self.session, Path('cloud-result'), destination)
        self.assertEqual(len(first), len(second))
        self.assertTrue(
            all(
                item.resumed_from_bytes == item.size_bytes
                for item in second
            )
        )


if __name__ == '__main__':
    unittest.main()
