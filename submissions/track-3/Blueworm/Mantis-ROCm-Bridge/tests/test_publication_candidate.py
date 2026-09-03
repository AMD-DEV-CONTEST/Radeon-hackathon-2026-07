from __future__ import annotations

import hashlib
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.publication import (
    PublicationGateError,
    build_publication_candidate,
)


def _config(root: Path) -> Path:
    path = root / "publication.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "package_name": "fixture",
                "include_files": ["README.md", "LICENSE"],
                "include_directories": ["src", "tests"],
                "exclude_globs": ["**/__pycache__/**", "**/*.pyc"],
                "exact_exclude_file_exceptions": [],
                "maximum_file_bytes": 1000,
                "forbidden_asset_extensions": [".urdf", ".stl"],
                "permitted_fixture_asset_globs": ["tests/fixtures/**"],
                "sensitive_filename_globs": ["**/.env", "**/id_rsa"],
                "required_release_files": ["LICENSE"],
                "permitted_provenance_path_globs": [],
                "machine_specific_path_prefixes": ["/" + "Users/", "/" + "data01/"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _repository(root: Path, *, with_license: bool = True) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "tests/fixtures").mkdir(parents=True)
    (root / "README.md").write_text("portable\n", encoding="utf-8")
    (root / "src/main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "tests/fixtures/minimal.urdf").write_text(
        "<robot name='synthetic'/>\n", encoding="utf-8"
    )
    if with_license:
        (root / "LICENSE").write_text("fixture license\n", encoding="utf-8")
    return root


class PublicationCandidateTests(unittest.TestCase):
    def test_release_candidate_is_deterministic_and_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            config = _config(repository)
            first = base / "first"
            second = base / "second"

            first_audit = build_publication_candidate(repository, config, first)
            second_audit = build_publication_candidate(repository, config, second)

            self.assertEqual(first_audit["status"], "COMPLETE_RELEASE")
            self.assertTrue(first_audit["content_gate_pass"])
            self.assertTrue(first_audit["promotion_gate_pass"])
            archive = first / "fixture-candidate.tar.gz"
            self.assertEqual(
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                hashlib.sha256((second / archive.name).read_bytes()).hexdigest(),
            )
            with tarfile.open(archive, "r:gz") as package:
                names = package.getnames()
            self.assertIn("fixture/README.md", names)
            self.assertIn("fixture/tests/fixtures/minimal.urdf", names)
            manifest = (first / "SOURCE_FILES.SHA256SUMS").read_text(encoding="utf-8")
            self.assertIn("tests/fixtures/minimal.urdf", manifest)
            self.assertTrue((first / "FINAL_EVIDENCE.SHA256SUMS").is_file())

    def test_missing_license_and_machine_path_block_only_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository", with_license=False)
            (repository / "README.md").write_text(
                "local example: /" + "Users/operator/project\n", encoding="utf-8"
            )
            config = _config(repository)
            output = base / "candidate"

            audit = build_publication_candidate(repository, config, output)

            self.assertEqual(audit["status"], "BLOCKED_PROMOTION")
            self.assertTrue(audit["content_gate_pass"])
            self.assertFalse(audit["promotion_gate_pass"])
            rules = {finding["rule"] for finding in audit["findings"]}
            self.assertIn("missing_required_release_file", rules)
            self.assertIn("machine_specific_absolute_path", rules)
            self.assertTrue((output / "fixture-candidate.tar.gz").is_file())

    def test_secret_blocks_archive_without_recording_secret_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            fake_token = "ghp_" + ("A" * 40)
            (repository / "src/main.py").write_text(
                f"TOKEN = '{fake_token}'\n", encoding="utf-8"
            )
            config = _config(repository)
            output = base / "blocked"

            audit = build_publication_candidate(repository, config, output)

            self.assertEqual(audit["status"], "FAILED_CONTENT_GATE")
            self.assertFalse(audit["content_gate_pass"])
            self.assertFalse((output / "fixture-candidate.tar.gz").exists())
            serialized = (output / "publication_audit.json").read_text(encoding="utf-8")
            self.assertNotIn(fake_token, serialized)
            self.assertIn("github_classic_token", serialized)

    def test_machine_path_in_explicit_provenance_file_is_counted_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            provenance = repository / "src/provenance.md"
            provenance.write_text(
                "historical root: /" + "data01/operator/run\n", encoding="utf-8"
            )
            config = _config(repository)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["permitted_provenance_path_globs"] = ["src/provenance.md"]
            config.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            audit = build_publication_candidate(repository, config, base / "candidate")

            self.assertEqual(audit["status"], "COMPLETE_RELEASE")
            self.assertEqual(audit["finding_counts"]["promotion"], 0)
            self.assertEqual(
                audit["inventory"]["permitted_provenance_path_occurrences"],
                [{"path": "src/provenance.md", "line": 1}],
            )

    def test_broken_local_markdown_link_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            (repository / "README.md").write_text(
                "See [missing](docs/missing.md).\n", encoding="utf-8"
            )
            config = _config(repository)

            audit = build_publication_candidate(repository, config, base / "candidate")

            self.assertTrue(audit["content_gate_pass"])
            self.assertFalse(audit["promotion_gate_pass"])
            self.assertIn(
                "broken_local_markdown_link",
                {finding["rule"] for finding in audit["findings"]},
            )

    def test_existing_local_markdown_link_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            (repository / "README.md").write_text(
                "See [implementation](src/main.py).\n", encoding="utf-8"
            )
            config = _config(repository)

            audit = build_publication_candidate(repository, config, base / "candidate")

            self.assertTrue(audit["promotion_gate_pass"])
            self.assertEqual(audit["inventory"]["checked_local_markdown_links"], 1)

    def test_non_fixture_robot_asset_blocks_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            (repository / "src/robot.urdf").write_text(
                "<robot name='not-vendored'/>\n", encoding="utf-8"
            )
            config = _config(repository)

            audit = build_publication_candidate(repository, config, base / "blocked")

            self.assertFalse(audit["content_gate_pass"])
            self.assertIn(
                "robot_or_scene_asset_forbidden",
                {finding["rule"] for finding in audit["findings"]},
            )

    def test_exact_exclude_file_exception_includes_only_named_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            receipts = repository / "receipts/example"
            receipts.mkdir(parents=True)
            included = receipts / "terminal.json"
            excluded = receipts / "other.json"
            included.write_text('{"terminal": "COMPLETE"}\n', encoding="utf-8")
            excluded.write_text('{"terminal": "OTHER"}\n', encoding="utf-8")
            config = _config(repository)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["include_files"].append("receipts/example/terminal.json")
            payload["include_directories"].append("receipts")
            payload["exclude_globs"].append("receipts/**")
            payload["exact_exclude_file_exceptions"] = [
                "receipts/example/terminal.json"
            ]
            config.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            output = base / "candidate"
            audit = build_publication_candidate(repository, config, output)

            manifest = (output / "SOURCE_FILES.SHA256SUMS").read_text(
                encoding="utf-8"
            )
            self.assertEqual(audit["status"], "COMPLETE_RELEASE")
            self.assertIn("receipts/example/terminal.json", manifest)
            self.assertNotIn("receipts/example/other.json", manifest)
            self.assertEqual(
                audit["inventory"]["exact_exclude_file_exceptions"],
                ["receipts/example/terminal.json"],
            )

    def test_invalid_exact_exclude_file_exceptions_are_rejected(self) -> None:
        cases = (
            ("glob", "receipts/example/*.json", True, False),
            ("absolute", "/tmp/terminal.json", True, False),
            ("parent", "../terminal.json", True, False),
            ("directory", "receipts/example", True, True),
            ("missing", "receipts/example/missing.json", True, False),
            ("not_included", "receipts/example/terminal.json", False, False),
            ("not_excluded", "src/main.py", True, False),
        )
        for name, exception, add_include, make_directory in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repository = _repository(base / "repository")
                receipts = repository / "receipts/example"
                receipts.mkdir(parents=True)
                (receipts / "terminal.json").write_text("{}\n", encoding="utf-8")
                config = _config(repository)
                payload = json.loads(config.read_text(encoding="utf-8"))
                payload["exclude_globs"].append("receipts/**")
                payload["exact_exclude_file_exceptions"] = [exception]
                if add_include:
                    payload["include_files"].append(exception)
                if make_directory:
                    self.assertTrue((repository / exception).is_dir())
                config.write_text(json.dumps(payload) + "\n", encoding="utf-8")

                with self.assertRaises(PublicationGateError):
                    build_publication_candidate(repository, config, base / "candidate")

    def test_exact_exception_rejects_symlinked_parent(self) -> None:
        for target_location in ("outside", "inside"):
            with (
                self.subTest(target_location=target_location),
                tempfile.TemporaryDirectory() as directory,
            ):
                base = Path(directory)
                repository = _repository(base / "repository")
                receipts = repository / "receipts"
                receipts.mkdir()
                if target_location == "outside":
                    target = base / "external"
                    target.mkdir()
                    link_target = target
                else:
                    target = receipts / "target"
                    target.mkdir()
                    link_target = Path("target")
                (target / "terminal.json").write_text("{}\n", encoding="utf-8")
                (receipts / "link").symlink_to(link_target, target_is_directory=True)

                config = _config(repository)
                payload = json.loads(config.read_text(encoding="utf-8"))
                payload["include_files"].append("receipts/link/terminal.json")
                payload["exclude_globs"].append("receipts/**")
                payload["exact_exclude_file_exceptions"] = [
                    "receipts/link/terminal.json"
                ]
                config.write_text(json.dumps(payload) + "\n", encoding="utf-8")

                with self.assertRaises(PublicationGateError):
                    build_publication_candidate(repository, config, base / "candidate")

    def test_media_selection_includes_only_accepted_v4_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            media_paths = (
                "submission/media/Mantis_ROCM_Bridge_demo_20260804.mp4",
                "submission/media/Mantis_ROCM_Bridge_demo_20260805_v2.mp4",
                "submission/media/Mantis_ROCM_Bridge_demo_20260805_v3.mp4",
                "submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4",
            )
            for index, relative in enumerate(media_paths, start=1):
                path = repository / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"video-v{index}\n".encode("ascii"))

            config = _config(repository)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["include_files"].append(media_paths[3])
            payload["include_directories"].append("submission")
            payload["exclude_globs"].extend(media_paths[:3])
            config.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            output = base / "candidate"

            audit = build_publication_candidate(repository, config, output)

            self.assertEqual(audit["status"], "COMPLETE_RELEASE")
            packaged_media = {
                relative
                for relative in media_paths
                if (output / "public_tree" / relative).is_file()
            }
            self.assertEqual(packaged_media, {media_paths[3]})
            self.assertEqual(
                (output / "public_tree" / media_paths[3]).read_bytes(),
                (repository / media_paths[3]).read_bytes(),
            )
            manifest_paths = {
                line.split(maxsplit=1)[1]
                for line in (output / "SOURCE_FILES.SHA256SUMS")
                .read_text(encoding="utf-8")
                .splitlines()
            }
            self.assertEqual(manifest_paths.intersection(media_paths), {media_paths[3]})
            archive = output / "fixture-candidate.tar.gz"
            with tarfile.open(archive, "r:gz") as package:
                archive_paths = set(package.getnames())
            expected_archive_paths = {f"fixture/{relative}" for relative in media_paths}
            self.assertEqual(
                archive_paths.intersection(expected_archive_paths),
                {f"fixture/{media_paths[3]}"},
            )

    def test_missing_accepted_v4_fails_content_gate_without_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            media_paths = (
                "submission/media/Mantis_ROCM_Bridge_demo_20260804.mp4",
                "submission/media/Mantis_ROCM_Bridge_demo_20260805_v2.mp4",
                "submission/media/Mantis_ROCM_Bridge_demo_20260805_v3.mp4",
                "submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4",
            )
            for index, relative in enumerate(media_paths[:3], start=1):
                path = repository / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"video-v{index}\n".encode("ascii"))

            config = _config(repository)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["include_files"].append(media_paths[3])
            payload["include_directories"].append("submission")
            payload["exclude_globs"].extend(media_paths[:3])
            config.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            output = base / "candidate"

            audit = build_publication_candidate(repository, config, output)

            self.assertEqual(audit["status"], "FAILED_CONTENT_GATE")
            self.assertFalse(audit["content_gate_pass"])
            self.assertIn(
                {
                    "gate": "allowlist",
                    "rule": "missing_include_file",
                    "path": media_paths[3],
                },
                audit["findings"],
            )
            self.assertFalse(audit["archive_created"])
            self.assertFalse((output / "fixture-candidate.tar.gz").exists())

    def test_refuses_to_overwrite_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            config = _config(repository)
            output = base / "candidate"
            output.mkdir()

            with self.assertRaises(PublicationGateError):
                build_publication_candidate(repository, config, output)

    def _repository_with_port_config(self, repository: Path, payload: dict) -> Path:
        config_file = repository / "configs/port.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return repository

    def _config_with_transform(
        self, repository: Path, transform: dict
    ) -> Path:
        config = _config(repository)
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["include_directories"].append("configs")
        payload["config_transforms"] = [transform]
        config.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return config

    def test_config_transform_removes_top_level_key_and_leaves_source_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            self._repository_with_port_config(
                repository,
                {"schema_version": 1, "current": {"control_plane": "secret"}, "product": "mantis"},
            )
            config = self._config_with_transform(
                repository,
                {"path": "configs/port.json", "remove_top_level_keys": ["current"]},
            )
            output = base / "candidate"

            audit = build_publication_candidate(repository, config, output)

            self.assertEqual(audit["status"], "COMPLETE_RELEASE")
            packaged = json.loads(
                (output / "public_tree/configs/port.json").read_text(encoding="utf-8")
            )
            source = json.loads(
                (repository / "configs/port.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("current", packaged)
            self.assertIn("current", source)
            manifest = {
                line.split("  ", 1)[1]: line.split("  ", 1)[0]
                for line in (output / "SOURCE_FILES.SHA256SUMS")
                .read_text(encoding="utf-8")
                .splitlines()
            }
            packaged_bytes = (output / "public_tree/configs/port.json").read_bytes()
            self.assertEqual(
                manifest["configs/port.json"],
                hashlib.sha256(packaged_bytes).hexdigest(),
            )
            self.assertNotEqual(
                manifest["configs/port.json"],
                hashlib.sha256((repository / "configs/port.json").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                audit["inventory"]["config_transforms"],
                [{"path": "configs/port.json", "remove_top_level_keys": ["current"]}],
            )

    def test_config_transform_manifest_matches_public_tree_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            self._repository_with_port_config(
                repository,
                {"schema_version": 1, "current": {"control_plane": "secret"}, "product": "mantis"},
            )
            config = self._config_with_transform(
                repository,
                {"path": "configs/port.json", "remove_top_level_keys": ["current"]},
            )
            output = base / "candidate"

            build_publication_candidate(repository, config, output)

            public_tree = output / "public_tree"
            mismatches = []
            for path in public_tree.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(public_tree).as_posix()
                    manifest = (output / "SOURCE_FILES.SHA256SUMS").read_text(
                        encoding="utf-8"
                    )
                    expected = next(
                        line.split("  ", 1)[0]
                        for line in manifest.splitlines()
                        if line.split("  ", 1)[1] == relative
                    )
                    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                        mismatches.append(relative)
            self.assertEqual(mismatches, [])
            with tarfile.open(output / "fixture-candidate.tar.gz", "r:gz") as package:
                member = package.extractfile("fixture/configs/port.json")
                assert member is not None
                archive_bytes = member.read()
            self.assertEqual(
                archive_bytes,
                (public_tree / "configs/port.json").read_bytes(),
            )

    def test_config_transform_removes_nested_paths_from_public_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            self._repository_with_port_config(
                repository,
                {
                    "schema_version": 1,
                    "current": {"control_plane": "private"},
                    "training": {
                        "public": {"steps": 50},
                        "internal_execution": {"executor": "private"},
                    },
                },
            )
            config = self._config_with_transform(
                repository,
                {
                    "path": "configs/port.json",
                    "remove_top_level_keys": ["current"],
                    "remove_paths": [["training", "internal_execution"]],
                },
            )

            output = base / "candidate"
            build_publication_candidate(repository, config, output)

            packaged = json.loads(
                (output / "public_tree/configs/port.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("current", packaged)
            self.assertNotIn("internal_execution", packaged["training"])
            self.assertEqual(packaged["training"]["public"], {"steps": 50})

    def test_config_transform_fails_closed_when_key_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            self._repository_with_port_config(
                repository, {"schema_version": 1, "product": "mantis"}
            )
            config = self._config_with_transform(
                repository,
                {"path": "configs/port.json", "remove_top_level_keys": ["current"]},
            )
            with self.assertRaises(PublicationGateError):
                build_publication_candidate(repository, config, base / "candidate")

    def test_config_transform_fails_closed_when_target_not_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = _repository(base / "repository")
            config = _config(repository)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["config_transforms"] = [
                {"path": "configs/never-packaged.json", "remove_top_level_keys": ["current"]}
            ]
            config.write_text(json.dumps(payload) + "\n", encoding="utf-8")
            with self.assertRaises(PublicationGateError):
                build_publication_candidate(repository, config, base / "candidate")

    def test_invalid_config_transform_declarations_are_rejected(self) -> None:
        cases = (
            ("not_list", {"config_transforms": {}}),
            ("entry_not_object", {"config_transforms": ["configs/port.json"]}),
            ("empty_path", {"config_transforms": [{"path": "", "remove_top_level_keys": ["current"]}]}),
            ("absolute_path", {"config_transforms": [{"path": "/port.json", "remove_top_level_keys": ["current"]}]}),
            ("parent_path", {"config_transforms": [{"path": "../port.json", "remove_top_level_keys": ["current"]}]}),
            ("empty_keys", {"config_transforms": [{"path": "configs/port.json", "remove_top_level_keys": []}]}),
            ("blank_key", {"config_transforms": [{"path": "configs/port.json", "remove_top_level_keys": [""]}]}),
            ("unknown_entry_key", {"config_transforms": [{"path": "configs/port.json", "remove_top_level_keys": ["current"], "mode": "rewrite"}]}),
            ("invalid_remove_paths", {"config_transforms": [{"path": "configs/port.json", "remove_top_level_keys": ["current"], "remove_paths": [""]}]}),
        )
        for name, override in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                repository = _repository(base / "repository")
                config = _config(repository)
                payload = json.loads(config.read_text(encoding="utf-8"))
                payload.update(override)
                config.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                with self.assertRaises(PublicationGateError):
                    build_publication_candidate(repository, config, base / "candidate")


if __name__ == "__main__":
    unittest.main()
