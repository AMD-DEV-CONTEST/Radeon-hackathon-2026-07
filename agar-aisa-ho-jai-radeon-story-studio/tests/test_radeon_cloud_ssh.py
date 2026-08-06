from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.episode_factory.manage_radeon_cloud_session import parser
from tools.episode_factory.radeon_cloud_execution import (
    JOB_SCHEMA,
    RadeonCloudJob,
    build_cloud_package,
    execute_cloud_package,
    inspect_cloud_package,
)
from tools.episode_factory.radeon_cloud_session import load_session, save_session
from tools.episode_factory.radeon_cloud_ssh import (
    AttachedRadeonCloudProvider,
    SshArtifactTransport,
    SshCommandExecutor,
    SshTransferError,
    SshWorkspaceConnection,
    attached_session,
    quote_remote_argv,
)
from tools.episode_factory.rendering_engine import ExecutionPlan


class QueueRunner:
    def __init__(self, *values):
        self.values = list(values)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((tuple(argv), kwargs))
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class LocalSshRunner:
    """Treat SSH/scp calls as local operations inside a temporary workspace."""

    def __init__(self, *, corrupt_download: str | None = None):
        self.calls = []
        self.corrupt_download = corrupt_download

    @staticmethod
    def remote_path(spec: str) -> Path:
        return Path(spec.split(":", 1)[1])

    def __call__(self, argv, **kwargs):
        self.calls.append((tuple(argv), kwargs))
        executable = Path(argv[0]).name
        if executable == "ssh":
            remote = shlex.split(argv[-1])
            if remote[:2] == ["python3", str(Path.cwd() / "tools/episode_factory/radeon_cloud_runner.py")]:
                remote.append("--allow-non-radeon")
            return subprocess.run(remote, **kwargs)
        if executable == "scp":
            source, destination = argv[-2:]
            if ":" in source:
                source_path = self.remote_path(source)
                if source_path.name == ".":
                    source_path = source_path.parent
                destination_path = Path(destination)
                destination_path.mkdir(parents=True, exist_ok=True)
                for item in source_path.rglob("*"):
                    if item.is_file():
                        target = destination_path / item.relative_to(source_path)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
                if self.corrupt_download:
                    (destination_path / self.corrupt_download).write_text("corrupt\n", encoding="utf-8")
            else:
                target = self.remote_path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)


class ReadyExecutor(SshCommandExecutor):
    def probe(self, *, include_runtime=True):
        return {
            "schema_version": "aahj.radeon-cloud-ssh-probe/v1",
            "base_ready": True,
            "production_ready": True,
            "runtime": {"ready": True},
        }


class LocalRsyncRunner(LocalSshRunner):
    def __call__(self, argv, **kwargs):
        executable = Path(argv[0]).name
        if executable == "ssh" and shlex.split(argv[-1]) == ["rsync", "--version"]:
            self.calls.append((tuple(argv), kwargs))
            return subprocess.CompletedProcess(argv, 0, "rsync 3", "")
        if executable == "rsync":
            self.calls.append((tuple(argv), kwargs))
            source, destination = argv[-2:]
            if ":" in destination:
                target = self.remote_path(destination)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            else:
                source_path = self.remote_path(source)
                destination_path = Path(destination)
                destination_path.mkdir(parents=True, exist_ok=True)
                for item in source_path.rglob("*"):
                    if item.is_file():
                        target = destination_path / item.relative_to(source_path)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
            return subprocess.CompletedProcess(argv, 0, "", "")
        return super().__call__(argv, **kwargs)


class RadeonCloudSshTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.key = self.root / "id_radeon"
        self.key.write_text("TOP-SECRET-PRIVATE-KEY", encoding="utf-8")
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.connection = SshWorkspaceConnection(
            host="workspace.example",
            port=22022,
            username="cloud-user",
            identity_file=self.key,
            workspace_root=str(self.workspace),
            remote_repository=str(Path.cwd()),
        )

    def tearDown(self):
        self.temporary.cleanup()

    def package(self) -> Path:
        script = self.root / "render.py"
        script.write_text(
            "from pathlib import Path\n"
            "p=Path('../outputs');p.mkdir();(p/'frame.txt').write_text('ok\\n')\n",
            encoding="utf-8",
        )
        plan = ExecutionPlan(
            specification_id="a" * 64,
            backend="radeon-cloud",
            model={"id": "test"},
            resolved_request={"seed": 7},
            output_contract={"formats": ["txt"]},
        )
        job = RadeonCloudJob.from_mapping(
            {
                "schema_version": JOB_SCHEMA,
                "argv": ["python3", "render.py"],
                "environment": {},
                "working_directory": "payload",
                "output_paths": ["outputs"],
                "timeout_seconds": 10,
            }
        )
        return build_cloud_package(
            execution_plan=plan,
            job=job,
            payload_files={"payload/render.py": script},
            destination=self.root / "package.tar.gz",
        )

    def result(self) -> tuple[Path, dict]:
        package = self.package()
        summary = inspect_cloud_package(package)
        result_root = self.workspace / "aahj-results" / summary["plan_id"]
        execute_cloud_package(package, result_directory=result_root, require_radeon=False)
        return result_root, summary

    def test_connection_is_canonical_and_stable(self):
        same = SshWorkspaceConnection.from_mapping(self.connection.as_dict())
        self.assertEqual(self.connection, same)
        self.assertEqual(self.connection.connection_id, same.connection_id)
        self.assertEqual(str(self.key.resolve()), same.identity_file)

    def test_connection_round_trip(self):
        path = self.connection.save(self.root / "connection.json")
        self.assertEqual(SshWorkspaceConnection.load(path), self.connection)

    def test_invalid_host_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "host"):
            SshWorkspaceConnection("bad host", 22, "user", self.key, str(self.workspace), str(Path.cwd()))

    def test_invalid_ports_are_rejected(self):
        for port in (0, 65536, True):
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, "port"):
                SshWorkspaceConnection("host", port, "user", self.key, str(self.workspace), str(Path.cwd()))

    def test_missing_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity_file"):
            SshWorkspaceConnection("host", 22, "user", self.root / "missing", str(self.workspace), str(Path.cwd()))

    def test_unsafe_remote_paths_are_rejected(self):
        for path in ("relative", "/workspace/../etc", "/work space"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "safe|unsafe"):
                SshWorkspaceConnection("host", 22, "user", self.key, path, str(Path.cwd()))

    def test_strict_host_key_checking_is_default(self):
        self.assertIn("StrictHostKeyChecking=yes", self.connection.ssh_argv(("true",)))

    def test_remote_argument_quoting(self):
        argv = ("python3", "file with spaces.py", "$(touch nope)", "single'quote")
        self.assertEqual(shlex.split(quote_remote_argv(argv)), list(argv))

    def test_ssh_is_an_argument_array_and_never_shell_true(self):
        runner = QueueRunner(subprocess.CompletedProcess([], 0, "ok", ""))
        evidence = SshCommandExecutor(self.connection, runner).execute(("printf", "%s", "hello world"))
        self.assertIsInstance(runner.calls[0][0], tuple)
        self.assertNotIn("shell", runner.calls[0][1])
        self.assertEqual(evidence.remote_argv[-1], "hello world")

    def test_successful_command(self):
        runner = QueueRunner(subprocess.CompletedProcess([], 0, "ok", ""))
        self.assertEqual(SshCommandExecutor(self.connection, runner).execute(("true",)).outcome, "succeeded")

    def test_remote_nonzero(self):
        runner = QueueRunner(subprocess.CompletedProcess([], 7, "", "bad"))
        evidence = SshCommandExecutor(self.connection, runner).execute(("false",))
        self.assertEqual((evidence.outcome, evidence.return_code), ("remote-nonzero", 7))

    def test_local_ssh_failure(self):
        evidence = SshCommandExecutor(self.connection, QueueRunner(OSError("missing ssh"))).execute(("true",))
        self.assertEqual(evidence.outcome, "local-ssh-failure")

    def test_timeout(self):
        timeout = subprocess.TimeoutExpired(["ssh"], 1, output=b"partial")
        evidence = SshCommandExecutor(self.connection, QueueRunner(timeout)).execute(("sleep", "2"), timeout=1)
        self.assertEqual(evidence.outcome, "timeout")
        self.assertEqual(evidence.stdout, "partial")

    def test_connection_interruption(self):
        evidence = SshCommandExecutor(self.connection, QueueRunner(subprocess.CompletedProcess([], 255, "", "lost"))).execute(("true",))
        self.assertEqual(evidence.outcome, "connection-interrupted")

    def transport(self, runner=None) -> SshArtifactTransport:
        local = runner or LocalSshRunner()
        executor = SshCommandExecutor(self.connection, local)
        return SshArtifactTransport(self.connection, executor=executor, runner=local, which=lambda _: None)

    def test_verified_upload_and_idempotent_repeat(self):
        package = self.package()
        transport = self.transport()
        first = transport.stage_package(package)
        second = transport.stage_package(package)
        self.assertTrue(first.verified)
        self.assertTrue(second.idempotent)

    def test_rsync_is_preferred_when_available_on_both_ends(self):
        runner = LocalRsyncRunner()
        executor = SshCommandExecutor(self.connection, runner)
        transport = SshArtifactTransport(
            self.connection,
            executor=executor,
            runner=runner,
            which=lambda name: f"/usr/bin/{name}",
        )
        receipt = transport.stage_package(self.package())
        self.assertEqual(receipt.transport, "rsync")

    def test_partial_upload_recovery(self):
        package = self.package()
        package_id = inspect_cloud_package(package)["package_id"]
        partial = self.workspace / "aahj-inbox" / f"{package_id}.tar.gz.partial"
        partial.parent.mkdir()
        partial.write_bytes(package.read_bytes()[:19])
        receipt = self.transport().stage_package(package)
        self.assertTrue(receipt.verified)
        self.assertFalse(partial.exists())

    def test_remote_digest_mismatch_is_rejected(self):
        class CorruptUpload(LocalSshRunner):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if Path(argv[0]).name == "scp" and ":" in argv[-1]:
                    self.remote_path(argv[-1]).write_text("corrupt", encoding="utf-8")
                return result

        with self.assertRaisesRegex(SshTransferError, "digest"):
            self.transport(CorruptUpload()).stage_package(self.package())

    def test_conflicting_remote_package_is_rejected(self):
        package = self.package()
        package_id = inspect_cloud_package(package)["package_id"]
        target = self.workspace / "aahj-inbox" / f"{package_id}.tar.gz"
        target.parent.mkdir()
        target.write_text("different", encoding="utf-8")
        with self.assertRaisesRegex(SshTransferError, "conflicting"):
            self.transport().stage_package(package)

    def test_successful_result_download(self):
        result_root, summary = self.result()
        destination = self.root / "download"
        receipt = self.transport().download_result(
            str(result_root), destination,
            expected_plan_id=summary["plan_id"],
            expected_package_id=summary["package_id"],
            expected_job_id=summary["job_id"],
        )
        self.assertTrue(receipt.verified)
        self.assertTrue((destination / "result.json").is_file())

    def test_corrupt_downloaded_result_is_detected(self):
        result_root, summary = self.result()
        with self.assertRaisesRegex(SshTransferError, "verification"):
            self.transport(LocalSshRunner(corrupt_download="result.json")).download_result(
                str(result_root), self.root / "bad", expected_plan_id=summary["plan_id"]
            )

    def test_corrupt_output_artifact_is_detected(self):
        result_root, summary = self.result()
        output = json.loads((result_root / "result.json").read_text())["execution_result"]["outputs"][0]["path"]
        with self.assertRaisesRegex(SshTransferError, "verification"):
            self.transport(LocalSshRunner(corrupt_download=output)).download_result(
                str(result_root), self.root / "bad-artifact", expected_plan_id=summary["plan_id"]
            )

    def test_orchestration_success_and_lifecycle(self):
        package = self.package()
        session_path = save_session(self.root / "session.json", attached_session(self.connection).transition("ready"))
        runner = LocalSshRunner()
        executor = ReadyExecutor(self.connection, runner)
        transport = SshArtifactTransport(self.connection, executor=executor, runner=runner, which=lambda _: None)
        provider = AttachedRadeonCloudProvider(self.connection, executor=executor, transport=transport)
        value = provider.run_remote(session_path, package, self.root / "final")
        self.assertEqual(value["state"], "completed")
        self.assertEqual(load_session(session_path).state, "completed")

    def test_orchestration_failure_preserves_evidence(self):
        package = self.package()
        session_path = save_session(self.root / "failed-session.json", attached_session(self.connection).transition("ready"))

        class FailedProbe(ReadyExecutor):
            def probe(self, *, include_runtime=True):
                return {"base_ready": True, "production_ready": False, "runtime": {"ready": False}}

        executor = FailedProbe(self.connection, LocalSshRunner())
        provider = AttachedRadeonCloudProvider(self.connection, executor=executor, transport=self.transport())
        with self.assertRaisesRegex(RuntimeError, "evidence"):
            provider.run_remote(session_path, package, self.root / "never")
        self.assertEqual(load_session(session_path).state, "failed")
        self.assertTrue((self.root / "never-ssh-evidence" / "failure.json").is_file())

    def test_private_key_contents_never_serialize(self):
        runner = QueueRunner(subprocess.CompletedProcess([], 0, "", ""))
        evidence = SshCommandExecutor(self.connection, runner).execute(("true",)).as_dict()
        receipt = self.transport().stage_package(self.package()).as_dict()
        serialized = json.dumps({"connection": self.connection.as_dict(), "evidence": evidence, "receipt": receipt})
        self.assertNotIn(self.key.read_text(), serialized)

    def test_cli_parses_all_ssh_commands(self):
        attach = parser().parse_args([
            "attach-ssh", "--host", "host", "--user", "user", "--identity-file", str(self.key),
            "--remote-repository", "/workspace/repo", "--output", "session.json",
        ])
        probe = parser().parse_args(["probe-ssh", "session.json"])
        run = parser().parse_args(["run-remote", "session.json", "package.tar.gz", "--destination", "result"])
        self.assertEqual((attach.command, probe.command, run.command), ("attach-ssh", "probe-ssh", "run-remote"))


if __name__ == "__main__":
    unittest.main()
