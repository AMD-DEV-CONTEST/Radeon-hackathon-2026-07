"""Tests for REAL_LOCAL_MODEL_ADMISSION_LOCK_001."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

mod = importlib.import_module("models.real_local_model_admission")
rec_mod = importlib.import_module("models.real_local_model_admission_record")
det_mod = importlib.import_module("models.real_ollama_provider_detection_record")

admit = mod.admit
TOKENS = rec_mod.REAL_LOCAL_MODEL_ADMISSION_STATUS_TOKENS
RealLocalModelAdmissionRecord = rec_mod.RealLocalModelAdmissionRecord
RealOllamaProviderDetectionRecord = det_mod.RealOllamaProviderDetectionRecord

LOCK_PATH = _REPO_ROOT / "locks" / "sentinel" / "REAL_LOCAL_MODEL_ADMISSION_LOCK_001.json"
EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "real_local_model_admission"
EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"

EXPECTED = frozenset(
    {
        "REAL_LOCAL_MODEL_ADMITTED",
        "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER",
        "REAL_LOCAL_MODEL_BLOCKED_UNPINNED",
        "REAL_LOCAL_MODEL_BLOCKED_STALE",
        "REAL_LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS",
        "REAL_LOCAL_MODEL_BLOCKED_NOT_OPTED_IN",
        "REAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER",
    }
)


def _detected():
    return RealOllamaProviderDetectionRecord(
        decision="REAL_OLLAMA_PROVIDER_DETECTED",
        endpoint="http://127.0.0.1:11434",
        elapsed_ms=12,
        models=("determinex-engineer-v11-dsl",),
    )


def _not_running():
    return RealOllamaProviderDetectionRecord(
        decision="REAL_OLLAMA_PROVIDER_BLOCKED_NOT_RUNNING",
        endpoint="http://127.0.0.1:11434",
        elapsed_ms=5,
    )


def test_status_tokens_exact():
    assert set(TOKENS) == EXPECTED


def test_network_provider_blocked_even_with_detection():
    r = admit(
        detection=_detected(),
        provider="anthropic",
        model_id="claude-3",
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_NETWORK_PROVIDER"
    assert r.network_provider_admitted is False


def test_no_model_provider_blocked():
    r = admit(
        detection=_detected(),
        provider="no_model",
        model_id="",
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER"


def test_unknown_provider_blocked():
    r = admit(
        detection=_detected(),
        provider="quantum-cloud",
        model_id="x",
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER"


def test_stale_id_blocked():
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id="determinex-engineer-v10-dsl",
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_STALE"


def test_unpinned_id_blocked():
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id="totally-not-a-real-model",
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_UNPINNED"


def test_unsupported_task_class_blocked():
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id=current,
        task_classes=("ZAP_BRAIN",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS"


def test_empty_task_classes_blocked():
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id=current,
        task_classes=(),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_UNSUPPORTED_TASK_CLASS"


def test_ollama_requires_detection():
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    r = admit(
        detection=_not_running(),
        provider="ollama",
        model_id=current,
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_NO_PROVIDER"


def test_opt_in_required_even_with_detection_and_valid_id():
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id=current,
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=False,
    )
    assert r.decision == "REAL_LOCAL_MODEL_BLOCKED_NOT_OPTED_IN"


def test_admission_succeeds_with_all_gates_satisfied():
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id=current,
        task_classes=("BUILD_DIAGNOSIS", "PATCH_PLANNING"),
        opt_in=True,
    )
    assert r.decision == "REAL_LOCAL_MODEL_ADMITTED"
    assert r.source_mutation_authorized is False
    assert r.training_eligible is False
    assert r.dry_run_default is True
    assert r.network_provider_admitted is False
    assert r.opt_in is True
    assert "BUILD_DIAGNOSIS" in r.task_classes_admitted


def test_admission_record_serializes_with_safe_flags():
    from models.model_router import CURRENT_MODEL_IDS

    current = sorted(CURRENT_MODEL_IDS)[0]
    r = admit(
        detection=_detected(),
        provider="ollama",
        model_id=current,
        task_classes=("BUILD_DIAGNOSIS",),
        opt_in=True,
    )
    d = r.to_dict()
    json.dumps(d)
    assert d["source_mutation_authorized"] is False
    assert d["training_eligible"] is False
    assert d["network_provider_admitted"] is False


def test_module_does_not_call_a_model():
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subprocess.Popen",
        "subprocess.run",
        "urllib.request.urlopen",
        "requests.get",
        "httpx",
        "ollama.run",
        "ollama.pull",
    ):
        assert forbidden not in src


def test_lock_manifest_exists_and_validates():
    assert LOCK_PATH.is_file()
    blob = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert blob["lock_id"] == "REAL_LOCAL_MODEL_ADMISSION_LOCK_001"
    assert set(blob.get("status_tokens", [])).issubset(EXPECTED)
    sd = blob.get("scope_discipline", {})
    assert sd.get("source_mutation_authorized") is False
    assert sd.get("training_eligibility_opened") is False
    assert sd.get("live_model_called") is False
    assert sd.get("network_provider_admitted") is False


def test_evidence_artifact_present():
    candidates = sorted(EVIDENCE_DIR.glob("run_*.json"))
    assert candidates


def test_evidence_index_entry_present():
    idx = json.loads(EVIDENCE_INDEX.read_text(encoding="utf-8"))
    ids = {e.get("evidence_id") for e in idx.get("entries", [])}
    assert "REAL_LOCAL_MODEL_ADMISSION_LOCK_001" in ids
