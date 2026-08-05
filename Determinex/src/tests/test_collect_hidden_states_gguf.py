"""Tests for rosetta/collect_hidden_states_gguf.py -- the GGUF-based Rosetta hidden-state
collector. Built 2026-07-27 per Ryan's direct instruction: a collector that works from local
GGUF files "for all models, not just the ones we have," so training data doesn't depend on a
HuggingFace download (gemma-2-2b-it is gated, confirmed live: GatedRepoError 403 for
darthceltic85, which motivated this module in the first place).

llama-cpp-python is not installed in this environment (a genuine, flagged dependency gap --
see the module's own LlamaCppUnavailable). Every test here either exercises the parts that
don't need it (Ollama discovery, output-format contract) or mocks `llama_cpp` so the collection
LOGIC is verified without the native library being present.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# `rosetta.collect_hidden_states_gguf` pulls torch in transitively. torch is multi-GB and is
# deliberately not installed in the fast CI lane, where these failed as
# "ModuleNotFoundError: No module named 'torch'" and as assertions about a collector that
# had never run. State the dependency instead of letting the import error stand in for it.
pytest.importorskip("torch", reason="hidden-state collection needs torch; not in the fast lane")

from rosetta.collect_hidden_states_gguf import (  # noqa: E402
    LlamaCppUnavailable,
    collect_states_gguf,
    discover_ollama_models,
    run_collection_gguf,
)
from rosetta.shared_prompts import SHARED_PROMPTS  # noqa: E402


def _fake_run(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_discover_returns_empty_when_ollama_not_on_path():
    with patch("subprocess.run", side_effect=OSError("not found")):
        assert discover_ollama_models() == {}


def test_discover_returns_empty_when_ollama_list_fails():
    with patch("subprocess.run", return_value=_fake_run(returncode=1)):
        assert discover_ollama_models() == {}


def test_discover_survives_a_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ollama", timeout=15)):
        assert discover_ollama_models() == {}


def test_discover_parses_list_and_resolves_from_line(tmp_path):
    blob = tmp_path / "sha256-abc123"
    blob.write_bytes(b"fake gguf bytes")

    list_output = (
        "NAME               ID              SIZE\nmy-model:latest    abc123          1.0 GB\n"
    )
    modelfile_output = f"# comment\nFROM {blob}\nTEMPLATE {{{{ .Prompt }}}}\n"

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "list"]:
            return _fake_run(stdout=list_output)
        if cmd[:2] == ["ollama", "show"]:
            return _fake_run(stdout=modelfile_output)
        raise AssertionError(f"unexpected command {cmd}")

    with patch("subprocess.run", side_effect=fake_run):
        result = discover_ollama_models()

    assert result == {"my-model:latest": blob}


def test_discover_skips_a_model_whose_blob_does_not_resolve():
    """A FROM line pointing at a path that doesn't exist on disk must not be reported as
    discoverable -- collect_states_gguf would just fail to load it."""
    list_output = (
        "NAME               ID              SIZE\nghost-model:latest abc123          1.0 GB\n"
    )
    modelfile_output = "FROM /this/path/does/not/exist\n"

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "list"]:
            return _fake_run(stdout=list_output)
        return _fake_run(stdout=modelfile_output)

    with patch("subprocess.run", side_effect=fake_run):
        assert discover_ollama_models() == {}


def test_discover_one_bad_model_does_not_break_the_rest(tmp_path):
    """Real shape found live 2026-07-27: one model's Modelfile can fail to fetch/decode (the
    actual live failure was a UnicodeDecodeError on the console codepage, now fixed by passing
    encoding="utf-8", errors="replace" explicitly -- so the surviving failure mode for a single
    bad entry is an OSError-shaped subprocess failure). That single model must be skipped, not
    abort discovery of every other model."""
    good_blob = tmp_path / "sha256-good"
    good_blob.write_bytes(b"fake gguf")

    list_output = (
        "NAME             ID     SIZE\n"
        "bad-model:latest a1     1.0 GB\n"
        "good-model:latest b2    1.0 GB\n"
    )

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["ollama", "list"]:
            return _fake_run(stdout=list_output)
        if "bad-model:latest" in cmd:
            raise OSError("simulated failure for this one model")
        return _fake_run(stdout=f"FROM {good_blob}\n")

    with patch("subprocess.run", side_effect=fake_run):
        result = discover_ollama_models()

    assert result == {"good-model:latest": good_blob}


def _mock_llama_cpp(dim: int = 8):
    """A fake llama_cpp module whose Llama.create_embedding returns a fixed-size vector,
    without ever touching the real native library."""
    fake_module = MagicMock()

    class FakeLlama:
        def __init__(self, model_path, embedding, n_ctx, n_gpu_layers, verbose):
            self.model_path = model_path

        def create_embedding(self, prompt):
            return {"data": [{"embedding": [float(len(prompt) % 7)] * dim}]}

    fake_module.Llama = FakeLlama
    return fake_module


def test_collect_states_gguf_writes_one_file_per_prompt(tmp_path):
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"not a real gguf, just needs to exist for the path")
    out_dir = tmp_path / "out"
    prompts = SHARED_PROMPTS[:5]

    with patch(
        "rosetta.collect_hidden_states_gguf._import_llama_cpp",
        return_value=_mock_llama_cpp(),
    ):
        saved = collect_states_gguf(gguf, prompts, "testfamily", out_dir)

    assert saved == 5
    files = sorted(out_dir.glob("prompt_*.pt"))
    assert len(files) == 5
    assert files[0].name == "prompt_0000.pt"


def test_collect_states_gguf_output_is_loadable_correct_shape(tmp_path):
    """The saved format must be exactly what train_rosetta.py expects from either collector:
    a torch tensor, not a list or dict."""
    import torch

    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"placeholder")
    out_dir = tmp_path / "out"

    with patch(
        "rosetta.collect_hidden_states_gguf._import_llama_cpp",
        return_value=_mock_llama_cpp(dim=16),
    ):
        collect_states_gguf(gguf, SHARED_PROMPTS[:1], "testfamily", out_dir)

    tensor = torch.load(out_dir / "prompt_0000.pt", weights_only=True)
    assert tensor.shape == (16,)
    assert tensor.dtype == torch.float32


def test_collect_states_gguf_one_bad_prompt_does_not_abort_the_rest(tmp_path):
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"placeholder")
    out_dir = tmp_path / "out"

    fake_module = MagicMock()

    class FlakyLlama:
        def __init__(self, **kwargs):
            self.calls = 0

        def create_embedding(self, prompt):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulated backend failure")
            return {"data": [{"embedding": [1.0, 2.0]}]}

    fake_module.Llama = FlakyLlama

    with patch("rosetta.collect_hidden_states_gguf._import_llama_cpp", return_value=fake_module):
        saved = collect_states_gguf(gguf, SHARED_PROMPTS[:4], "testfamily", out_dir)

    assert saved == 3  # 4 prompts, 1 simulated failure
    assert len(list(out_dir.glob("prompt_*.pt"))) == 3


def test_missing_llama_cpp_raises_actionable_error(tmp_path):
    """The core contract: a missing dependency must be a loud, explicit error naming the exact
    fix -- never a silent 0-states result that could be mistaken for 'nothing to collect'."""
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"placeholder")

    with patch(
        "rosetta.collect_hidden_states_gguf._import_llama_cpp",
        side_effect=LlamaCppUnavailable(),
    ):
        try:
            collect_states_gguf(gguf, SHARED_PROMPTS[:1], "testfamily", tmp_path / "out")
            assert False, "expected LlamaCppUnavailable"
        except LlamaCppUnavailable as e:
            assert "pip install llama-cpp-python" in str(e)


def test_run_collection_gguf_writes_a_summary_with_gguf_backend_tag(tmp_path):
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"placeholder")
    out_dir = tmp_path / "collected"

    with patch(
        "rosetta.collect_hidden_states_gguf._import_llama_cpp",
        return_value=_mock_llama_cpp(),
    ):
        results = run_collection_gguf(out_dir, single=("testfamily", gguf))

    assert results == {"testfamily": len(SHARED_PROMPTS)}
    import json

    summary = json.loads((out_dir / "collection_summary.json").read_text(encoding="utf-8"))
    assert summary["backend"] == "gguf"
    assert summary["families"]["testfamily"] == len(SHARED_PROMPTS)


def test_run_collection_gguf_skips_an_already_collected_family(tmp_path):
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"placeholder")
    out_dir = tmp_path / "collected"
    fam_dir = out_dir / "testfamily"
    fam_dir.mkdir(parents=True)
    for i in range(len(SHARED_PROMPTS)):
        (fam_dir / f"prompt_{i:04d}.pt").write_bytes(b"stub")

    # No _import_llama_cpp patch at all -- if this test needed it, it would raise
    # LlamaCppUnavailable and fail loudly, proving the skip path never touches llama_cpp.
    results = run_collection_gguf(out_dir, single=("testfamily", gguf))
    assert results == {"testfamily": len(SHARED_PROMPTS)}


def test_run_collection_gguf_propagates_missing_dependency_instead_of_recording_zero(tmp_path):
    """A missing llama-cpp-python must abort the whole collection loudly -- NOT get silently
    recorded as families: {"testfamily": 0} the way a real per-prompt failure would be. Those
    are different failure classes and must not be conflated."""
    gguf = tmp_path / "fake.gguf"
    gguf.write_bytes(b"placeholder")
    out_dir = tmp_path / "collected"

    with patch(
        "rosetta.collect_hidden_states_gguf._import_llama_cpp",
        side_effect=LlamaCppUnavailable(),
    ):
        try:
            run_collection_gguf(out_dir, single=("testfamily", gguf))
            assert False, "expected LlamaCppUnavailable to propagate"
        except LlamaCppUnavailable:
            pass


def test_shared_prompts_identical_between_both_collectors():
    """The whole point of extracting shared_prompts.py: both collectors must train the SAME
    signal, regardless of which one loaded the model."""
    from rosetta.collect_hidden_states import SHARED_PROMPTS as hf_prompts

    assert hf_prompts == SHARED_PROMPTS
