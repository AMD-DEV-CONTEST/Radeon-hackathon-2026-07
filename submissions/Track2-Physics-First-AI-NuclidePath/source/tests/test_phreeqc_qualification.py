import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import stat
import os
import signal
import time

import pytest
import nuclear_agent.phreeqc_qualification as qualification_module

from nuclear_agent.phreeqc_qualification import (
    BannerMatcher, QualificationClassification, QualificationConfig, QualificationError,
    SELECTED_OUTPUT_HEADER, SELECTED_OUTPUT_UNITS, normalize_selected_output,
    parse_selected_output, run_qualification, sha256_file, stage_qualification,
    validate_example2_structure,
    verify_output_files, verify_staged_artifacts, write_qualification_replay,
)
from nuclear_agent.replay import ReplayVerificationError, verify_bundle


FIXTURE = Path(__file__).parent / "fixtures/phreeqc/example2-selected-output.txt"


def _valid_body(extra=""):
    return ("import pathlib; print('PHREEQC synthetic-1'); "
            f"pathlib.Path('ex2.sel').write_bytes(pathlib.Path({str(FIXTURE)!r}).read_bytes()); "
            "pathlib.Path('phreeqc.out').write_text('report'); "
            "pathlib.Path('phreeqc.log').write_text('log'); " + extra)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _artifacts(tmp_path, body=None):
    source = tmp_path / "source"
    source.mkdir()
    executable = source / "solver"
    executable.write_text("#!/usr/bin/env python3\n" + (body or _valid_body()))
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    database = source / "database.dat"; database.write_text("synthetic database")
    input_path = source / "input.pqi"; input_path.write_text("synthetic input")
    work = tmp_path / "work"; work.mkdir()
    return executable, database, input_path, work


def _config(tmp_path, **changes):
    executable, database, input_path, work = _artifacts(tmp_path, changes.pop("body", None))
    values = dict(
        executable=executable, database=database, input_path=input_path, working_directory=work,
        expected_executable_sha256=_digest(executable), expected_database_sha256=_digest(database),
        expected_input_sha256=_digest(input_path), banner_matcher=BannerMatcher(r"PHREEQC synthetic-1"),
        timeout_seconds=1.0,
    )
    values.update(changes)
    return QualificationConfig(**values)


@pytest.mark.parametrize("field", ["executable", "database", "input_path"])
def test_configuration_rejects_relative_and_missing_source_paths(tmp_path, field):
    config = _config(tmp_path)
    values = {name: getattr(config, name) for name in config.__dataclass_fields__}
    values[field] = Path("relative")
    with pytest.raises(QualificationError, match="absolute"):
        QualificationConfig(**values)


@pytest.mark.parametrize("field", ["executable", "database", "input_path"])
def test_configuration_rejects_source_symlinks(tmp_path, field):
    config = _config(tmp_path)
    target = getattr(config, field)
    link = tmp_path / f"{field}-link"; link.symlink_to(target)
    values = {name: getattr(config, name) for name in config.__dataclass_fields__}; values[field] = link
    with pytest.raises(QualificationError, match="non-symlink"):
        QualificationConfig(**values)


def test_configuration_rejects_symlink_workdir_unknown_fields_timeout_and_hash(tmp_path):
    config = _config(tmp_path)
    link = tmp_path / "work-link"; link.symlink_to(config.working_directory, target_is_directory=True)
    with pytest.raises(QualificationError, match="working directory"):
        replace(config, working_directory=link)
    with pytest.raises(QualificationError, match="timeout"):
        replace(config, timeout_seconds=float("nan"))
    with pytest.raises(QualificationError, match="SHA-256"):
        replace(config, expected_input_sha256="A" * 64)
    data = {name: getattr(config, name) for name in config.__dataclass_fields__}; data["extra"] = True
    with pytest.raises(QualificationError, match="schema"):
        QualificationConfig.from_dict(data)
    with pytest.raises(FrozenInstanceError):
        config.timeout_seconds = 4


def test_configuration_rejects_missing_absolute_file(tmp_path):
    config = _config(tmp_path)
    with pytest.raises(QualificationError, match="regular"):
        replace(config, input_path=tmp_path / "missing.pqi")


@pytest.mark.parametrize("field", ["expected_executable_sha256", "expected_database_sha256", "expected_input_sha256"])
def test_preflight_rejects_each_source_hash_mismatch(tmp_path, field):
    config = _config(tmp_path)
    with pytest.raises(QualificationError, match="SHA-256 mismatch"):
        stage_qualification(replace(config, **{field: "0" * 64}))


def test_staging_verifies_hashes_and_direct_command_and_rejects_collision(tmp_path):
    config = _config(tmp_path)
    staged = stage_qualification(config)
    assert staged.source_hashes == staged.staged_hashes
    assert Path(staged.manifest.command[0]) == staged.manifest.executable
    assert staged.manifest.executable.is_absolute()
    assert all(sha256_file(path) == digest for path, digest in staged.manifest.input_files)
    with pytest.raises(QualificationError, match="already exists"):
        stage_qualification(config)


def test_staged_tampering_is_detected_before_process_execution(tmp_path):
    staged = stage_qualification(_config(tmp_path))
    staged.manifest.database.write_text("tampered")
    with pytest.raises(Exception, match="SHA-256 mismatch"):
        run_qualification(staged)


def test_process_success_output_hash_and_deterministic_payload_excludes_duration(tmp_path):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    assert result.process.exit_status == 0 and not result.process.timed_out
    assert result.banner == "PHREEQC synthetic-1"
    assert result.output_hashes["ex2.sel"] == _digest(FIXTURE)
    assert result.process.duration_seconds >= 0
    assert "duration" not in json.dumps(result.deterministic_payload())
    verify_output_files(staged, result)
    (result.working_directory / "ex2.sel").write_text("changed")
    with pytest.raises(QualificationError, match="changed"):
        verify_output_files(staged, result)


def test_process_nonzero_stdout_stderr_and_non_utf8_are_explicit(tmp_path):
    body = "import os,sys; print('PHREEQC synthetic-1', flush=True); os.write(1,b'out\\xff'); os.write(2,b'err\\xfe'); sys.exit(7)"
    with pytest.raises(QualificationError, match="status 7"):
        run_qualification(stage_qualification(_config(tmp_path, body=body)))


def test_timeout_is_explicit(tmp_path):
    body = "import time; print('PHREEQC synthetic-1', flush=True); time.sleep(2)"
    with pytest.raises(QualificationError, match="timed out"):
        run_qualification(stage_qualification(_config(tmp_path, body=body, timeout_seconds=.05)))


def test_output_limit_violation_cannot_produce_qualification_result(tmp_path):
    body = "import os,time; os.write(1, b'x'*4096); time.sleep(30)"
    staged = stage_qualification(_config(tmp_path, body=body, max_stdout_bytes=64))
    with pytest.raises(QualificationError, match="stdout exceeded"):
        run_qualification(staged)


@pytest.mark.skipif(os.name != "posix", reason="POSIX escaped-session pipe contract")
def test_qualification_rejects_incomplete_stream_drain(tmp_path):
    body = (
        "import pathlib,subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True); "
        "pathlib.Path('escaped.pid').write_text(str(p.pid)); " + _valid_body()
    )
    config = _config(tmp_path, body=body)
    config = replace(config, timeout_seconds=0.3)
    staged = stage_qualification(config)
    started = time.monotonic()
    try:
        with pytest.raises(QualificationError, match="stream drain"):
            run_qualification(staged)
        assert time.monotonic() - started < 1.3
        assert not (tmp_path / "bundle").exists()
    finally:
        pid_file = staged.run_directory / "escaped.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("mutation", [
    "pathlib.Path(sys.argv[3]).write_text('changed database')",
    "pathlib.Path(sys.argv[1]).write_text('changed input')",
    "pathlib.Path(sys.argv[0]).write_text('changed executable')",
    "pathlib.Path(sys.argv[3]).unlink()",
    "pathlib.Path(sys.argv[3]).unlink(); pathlib.Path(sys.argv[3]).symlink_to('/dev/null')",
])
def test_post_run_staged_artifact_mutation_fails_closed(tmp_path, mutation):
    body = f"import pathlib,sys; print('PHREEQC synthetic-1'); {mutation}"
    staged = stage_qualification(_config(tmp_path, body=body))
    with pytest.raises(QualificationError, match="staged"):
        run_qualification(staged)


@pytest.mark.parametrize("body", [
    "import pathlib; print('PHREEQC synthetic-1'); pathlib.Path('phreeqc.out').write_text('report'); pathlib.Path('phreeqc.log').write_text('log')",
    _valid_body("pathlib.Path('unexpected.bin').write_text('x')"),
    "import pathlib; print('PHREEQC synthetic-1'); pathlib.Path('ex2.sel').symlink_to('/dev/null'); pathlib.Path('phreeqc.out').write_text('report'); pathlib.Path('phreeqc.log').write_text('log')",
    "import pathlib,os; print('PHREEQC synthetic-1'); pathlib.Path('ex2.sel').write_bytes(pathlib.Path(" + repr(str(FIXTURE)) + ").read_bytes()); pathlib.Path('phreeqc.out').write_text('report'); os.link('phreeqc.out','phreeqc.log')",
    "import pathlib; print('PHREEQC synthetic-1'); pathlib.Path('ex2.sel').mkdir(); pathlib.Path('phreeqc.out').write_text('report'); pathlib.Path('phreeqc.log').write_text('log')",
])
def test_closed_output_policy_rejects_missing_unexpected_and_unsafe_entries(tmp_path, body):
    with pytest.raises(QualificationError):
        run_qualification(stage_qualification(_config(tmp_path, body=body)))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_closed_output_policy_rejects_fifo(tmp_path):
    body = ("import pathlib,os; print('PHREEQC synthetic-1'); os.mkfifo('ex2.sel'); "
            "pathlib.Path('phreeqc.out').write_text('report'); pathlib.Path('phreeqc.log').write_text('log')")
    with pytest.raises(QualificationError):
        run_qualification(stage_qualification(_config(tmp_path, body=body)))


@pytest.mark.parametrize("limits", [
    {"max_output_file_bytes": 100},
    {"max_output_total_bytes": 100},
])
def test_output_size_limits_fail_closed(tmp_path, limits):
    with pytest.raises(QualificationError, match="size limit|total size"):
        run_qualification(stage_qualification(_config(tmp_path, **limits)))


def test_stable_hash_rejects_file_modified_during_read(tmp_path, monkeypatch):
    path = tmp_path / "changing.bin"
    path.write_bytes(b"a" * 1024)
    original_read = qualification_module.os.read
    changed = False

    def mutating_read(descriptor, size):
        nonlocal changed
        chunk = original_read(descriptor, size)
        if chunk and not changed:
            changed = True
            path.write_bytes(path.read_bytes() + b"x")
        return chunk

    monkeypatch.setattr(qualification_module.os, "read", mutating_read)
    with pytest.raises(QualificationError, match="changed while hashing"):
        qualification_module.stable_file_snapshot(path)


@pytest.mark.parametrize("body", ["print('')", "print('PHREEQC synthetic-10')", "print('prefix PHREEQC synthetic-1')"])
def test_banner_matcher_is_required_and_unambiguous(tmp_path, body):
    with pytest.raises(QualificationError, match="banner"):
        run_qualification(stage_qualification(_config(tmp_path, body=body)))


def test_parser_schema_units_blank_lines_and_normalization_are_deterministic():
    parsed = parse_selected_output(FIXTURE.read_text())
    assert parsed.units == SELECTED_OUTPUT_UNITS and len(parsed.rows) == 52
    normalized = normalize_selected_output(parsed)
    assert [row["row_kind"] for row in normalized].count("initial") == 1
    assert [row["row_kind"] for row in normalized].count("reaction") == 51
    assert normalized == normalize_selected_output(parsed)
    validate_example2_structure(parsed)


@pytest.mark.parametrize("mutation", [
    lambda lines: ["wrong"] + lines[1:],
    lambda lines: [lines[0].replace("         sim", "        sim", 1)] + lines[1:],
    lambda lines: [lines[0].replace("sim\t       state", "state\t       sim")] + lines[1:],
    lambda lines: lines[:-1],
    lambda lines: lines + [lines[-1]],
    lambda lines: lines[:2] + lines[3:],
    lambda lines: lines[:2] + [lines[1]] + lines[2:],
    lambda lines: [lines[0]] + [line.replace("i_soln", "react") for line in lines[1:]],
    lambda lines: [lines[0], lines[1]] + [lines[2].replace("react", "i_soln")] + lines[3:],
    lambda lines: lines[:2] + [lines[2].replace("     7.06823", "         nan")] + lines[3:],
    lambda lines: lines[:2] + [lines[2].replace("     7.06823", "         inf")] + lines[3:],
    lambda lines: lines[:2] + [lines[2].replace("           1\t", "         1.5\t", 1)] + lines[3:],
])
def test_parser_rejects_malformed_schema_counts_states_and_numbers(mutation):
    text = "\n".join(mutation(FIXTURE.read_text().splitlines())) + "\n"
    with pytest.raises(QualificationError):
        parse_selected_output(text)


def test_same_shape_scientific_change_is_detected_exactly():
    original = FIXTURE.read_text()
    changed = original.replace("     7.06823", "     7.06824", 1)
    assert normalize_selected_output(parse_selected_output(original)) != normalize_selected_output(parse_selected_output(changed))


@pytest.mark.parametrize(("index", "changes"), [
    (0, {"state": "react"}),
    (1, {"simulation": 2}),
    (1, {"solution": 2}),
    (2, {"step": 1}),
    (1, {"temperature": 26.0}),
    (1, {"distance": 0.0}),
])
def test_example2_validator_rejects_control_structure_mutations(index, changes):
    parsed = parse_selected_output(FIXTURE.read_text())
    rows = list(parsed.rows)
    rows[index] = replace(rows[index], **changes)
    parsed = replace(parsed, rows=tuple(rows))
    with pytest.raises(QualificationError, match="Example 2"):
        validate_example2_structure(parsed)


def test_classification_never_promotes_scientific_result():
    with pytest.raises(QualificationError, match="must be derived"):
        QualificationClassification(True, True, False, "No independent numerical oracle")
    with pytest.raises(QualificationError, match="must be derived"):
        QualificationClassification(True, True, True, "claimed")


def test_replay_written_verified_tamper_detected_and_duration_not_deterministic(tmp_path):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    bundle = write_qualification_replay(
        tmp_path / "bundle", staged, result, "No independent numerical oracle",
    )
    assert verify_bundle(bundle.path).valid
    results = json.loads((bundle.path / "results.json").read_text())
    content = results["qualification_content"]
    assert content["classification"] == {
        "process_qualified": True, "scientific_input_qualified": True,
        "scientific_result_qualified": False,
        "scientific_result_reason": "No independent numerical oracle",
    }
    assert "duration" not in json.dumps(content)
    altered = replace(result.process, duration_seconds=result.process.duration_seconds + 10)
    assert replace(result, process=altered).deterministic_payload() == result.deterministic_payload()
    (bundle.path / "results.json").write_text("{}")
    with pytest.raises(ReplayVerificationError):
        verify_bundle(bundle.path)


def test_selected_output_is_parsed_from_same_stable_read(tmp_path, monkeypatch):
    staged = stage_qualification(_config(tmp_path))
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        if Path(path).name == "ex2.sel":
            raise AssertionError("selected output must not be reopened with read_text")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = run_qualification(staged)
    bundle = write_qualification_replay(tmp_path / "bundle", staged, result, "reason")
    assert result.parsed_selected_output.rows[1].pH == 7.06823
    assert verify_bundle(bundle.path, expected_manifest_sha256=bundle.manifest_sha256).valid


def test_trusted_root_detects_fully_rebuilt_internal_hashes(tmp_path):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    bundle = write_qualification_replay(tmp_path / "bundle", staged, result, "reason")
    trusted_root = bundle.manifest_sha256
    results_path = bundle.path / "results.json"
    results = json.loads(results_path.read_text())
    results["qualification_content"]["classification"]["process_qualified"] = False
    encoded = json.dumps(results["qualification_content"], allow_nan=False, sort_keys=True,
                         separators=(",", ":")).encode()
    results["qualification_content_sha256"] = hashlib.sha256(encoded).hexdigest()
    results_path.write_text(json.dumps(results, allow_nan=False, sort_keys=True, indent=2,
                                       separators=(",", ": ")) + "\n")
    manifest_path = bundle.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["results.json"] = _digest(results_path)
    manifest_path.write_text(json.dumps(manifest, allow_nan=False, sort_keys=True, indent=2,
                                        separators=(",", ": ")) + "\n")
    assert verify_bundle(bundle.path).valid
    with pytest.raises(ReplayVerificationError, match="trusted manifest root mismatch"):
        verify_bundle(bundle.path, expected_manifest_sha256=trusted_root)
    for invalid in ("0" * 63, "A" * 64):
        with pytest.raises(ReplayVerificationError, match="lowercase"):
            verify_bundle(bundle.path, expected_manifest_sha256=invalid)


def test_replay_rejects_result_from_another_staging(tmp_path):
    def completed(root):
        root.mkdir()
        staged = stage_qualification(_config(root))
        return staged, run_qualification(staged)

    staged_a, _ = completed(tmp_path / "a")
    _, result_b = completed(tmp_path / "b")
    with pytest.raises(QualificationError, match="identities"):
        write_qualification_replay(
            tmp_path / "bundle", staged_a, result_b, "reason",
        )


def test_replay_rechecks_staged_artifacts_immediately_before_write(tmp_path):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    staged.manifest.database.write_text("changed after run")
    with pytest.raises(QualificationError, match="staged database"):
        write_qualification_replay(
            tmp_path / "bundle", staged, result, "reason",
        )
    with pytest.raises(QualificationError, match="staged database"):
        verify_staged_artifacts(staged)


@pytest.mark.parametrize("mutation", ["remove", "add", "change"])
def test_replay_rechecks_closed_output_inventory(tmp_path, mutation):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    if mutation == "remove":
        (result.working_directory / "phreeqc.log").unlink()
    elif mutation == "add":
        (result.working_directory / "extra.bin").write_text("x")
    else:
        (result.working_directory / "phreeqc.out").write_text("changed")
    with pytest.raises(QualificationError):
        write_qualification_replay(
            tmp_path / "bundle", staged, result, "reason",
        )


@pytest.mark.parametrize("extra_kind", ["file", "symlink", "directory", "json"])
def test_replay_bundle_rejects_every_extra_directory_entry(tmp_path, extra_kind):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    bundle = write_qualification_replay(
        tmp_path / "bundle", staged, result, "reason",
    )
    extra = bundle.path / ("extra.json" if extra_kind == "json" else "extra")
    if extra_kind in {"file", "json"}:
        extra.write_text("{}")
    elif extra_kind == "symlink":
        extra.symlink_to(bundle.path / "results.json")
    else:
        extra.mkdir()
    with pytest.raises(ReplayVerificationError, match="file set"):
        verify_bundle(bundle.path)


def test_cross_directory_canonical_digest_is_equal_and_metadata_is_local(tmp_path):
    bundles = []
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        staged = stage_qualification(_config(root))
        result = run_qualification(staged)
        bundles.append(write_qualification_replay(
            root / "bundle", staged, result, "reason",
        ))
    results = [json.loads((bundle.path / "results.json").read_text()) for bundle in bundles]
    metadata = [json.loads((bundle.path / "metadata.json").read_text()) for bundle in bundles]
    assert results[0] == results[1]
    assert metadata[0]["paths"] != metadata[1]["paths"]


def test_canonical_payload_change_fails_even_with_updated_bundle_manifest(tmp_path):
    staged = stage_qualification(_config(tmp_path))
    result = run_qualification(staged)
    bundle = write_qualification_replay(
        tmp_path / "bundle", staged, result, "reason",
    )
    results_path = bundle.path / "results.json"
    results = json.loads(results_path.read_text())
    results["qualification_content"]["classification"]["process_qualified"] = False
    results_path.write_text(json.dumps(results, allow_nan=False, sort_keys=True, indent=2, separators=(",", ": ")) + "\n")
    manifest_path = bundle.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["results.json"] = _digest(results_path)
    manifest_path.write_text(json.dumps(manifest, allow_nan=False, sort_keys=True, indent=2,
                                        separators=(",", ": ")) + "\n")
    with pytest.raises(ReplayVerificationError, match="content digest"):
        verify_bundle(bundle.path)


def test_qualified_path_rejects_structurally_parseable_scientific_change_by_hash(tmp_path):
    changed = tmp_path / "changed.sel"
    changed.write_text(FIXTURE.read_text().replace("     7.06823", "     7.06824", 1))
    assert parse_selected_output(changed.read_text())
    body = _valid_body().replace(str(FIXTURE), str(changed))
    case = tmp_path / "case"
    case.mkdir()
    staged = stage_qualification(_config(case, body=body))
    with pytest.raises(QualificationError, match="selected output"):
        run_qualification(staged)
