import io
import hashlib
import json
import struct
import wave

import pytest

import services.database_registry as registry
from app.dependencies.auth import USER_API_KEY
from main import app
from services.audio_contract import (
    AudioContractError,
    create_audio_task,
    create_pronunciation_entry,
    create_voice_profile,
    get_audio_asset_contract,
    get_audio_contract_status,
    get_audio_task,
    get_audio_waveform,
    list_audio_tasks,
    register_audio_output,
    retry_failed_audio_task,
)
from services.db import close_connection, get_db, init_db
from services.media_assets import (
    MediaAssetError,
    import_media_asset,
    soft_delete_media_asset,
    transition_media_asset,
)
from services.model_registry import create_model_profile, create_provider
from services.model_packages.registry import sync_catalog
from services.tts_execution import TTSExecutionError, run_audio_task
from tests.asgi_client import asgi_request


def setup_runtime(tmp_path, monkeypatch):
    root = tmp_path / "runtime"
    monkeypatch.setattr(registry, "REGISTRY_PATH", str(root / "registry.db"))
    monkeypatch.setattr(registry, "DATABASES_ROOT", str(root / "databases"))
    monkeypatch.setattr(registry, "OLD_DB_PATH", str(root / "missing.db"))
    registry.init_registry()
    init_db()
    return root


def mark_package_installed(package_id: str):
    sync_catalog()
    conn = registry._get_registry_conn()
    try:
        conn.execute(
            "UPDATE model_package_installations SET status='installed' "
            "WHERE package_id=?",
            (package_id,),
        )
        conn.commit()
    finally:
        conn.close()
    sync_catalog()


def wav_bytes(frame_count=800, rate=8_000):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = [0, 8_192, -16_384, 32_000]
        output.writeframes(
            b"".join(struct.pack("<h", samples[index % len(samples)]) for index in range(frame_count))
        )
    return stream.getvalue()


def import_audio(filename="voice.wav"):
    return import_media_asset(
        "default",
        "default",
        stream=io.BytesIO(wav_bytes()),
        filename=filename,
        declared_mime="audio/wav",
    )


def approve(asset_id):
    return transition_media_asset("default", asset_id, "approve")


class FakeTTSExecutor:
    def __init__(self, *, fail_segment_index=None):
        self.fail_segment_index = fail_segment_index
        self.texts = []

    def execute(
        self,
        task,
        segment,
        *,
        text,
        voice,
        output_path,
        job_started,
    ):
        self.texts.append(text)
        job_id = hashlib.sha256(segment["segment_id"].encode("utf-8")).hexdigest()
        assert job_started(job_id) is True
        if segment["segment_index"] == self.fail_segment_index:
            raise TTSExecutionError("FAKE_TTS_FAILURE", "Synthetic segment failure")
        samples = [
            ((index * 251 + segment["segment_index"] * 997) % 20_000) - 10_000
            for index in range(2_400)
        ]
        pcm = b"".join(struct.pack("<h", value) for value in samples)
        with wave.open(str(output_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24_000)
            output.writeframes(pcm)
        return {
            "runtime_job_id": job_id,
            "effective_backend": "cpu",
            "output_digest": hashlib.sha256(pcm).hexdigest(),
            "duration_ms": 100,
        }


def test_audio_assets_waveform_and_profiles_work_without_model(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    status = get_audio_contract_status()
    assert status["asset_management_available_without_model"] is True
    assert status["execution_implemented"] is True
    assert status["default_audio_model"] is None
    assert status["model_selection"]["mode"] == "per_task"
    assert status["execution"]["api_process_loads_model_weights"] is False
    assert status["hardware_evidence"]["rocm_verified"] is False

    asset = import_audio()
    with pytest.raises(AudioContractError) as consent_error:
        create_voice_profile(
            {
                "database_id": "default",
                "book_id": "default",
                "name": "Private reference",
                "voice_kind": "local_reference",
                "reference_asset_id": asset["asset_id"],
                "consent_confirmed": True,
            }
        )
    assert consent_error.value.code == "REFERENCE_AUDIO_NOT_APPROVED"

    approve(asset["asset_id"])
    profile = create_voice_profile(
        {
            "database_id": "default",
            "book_id": "default",
            "name": "Private reference",
            "locale": "zh-CN",
            "voice_kind": "local_reference",
            "reference_asset_id": asset["asset_id"],
            "consent_confirmed": True,
            "metadata": {"description": "local only"},
        }
    )
    assert profile["consent_confirmed"] is True
    assert profile["reference_asset_id"] == asset["asset_id"]
    with pytest.raises(MediaAssetError) as delete_error:
        soft_delete_media_asset("default", asset["asset_id"])
    assert delete_error.value.code == "ASSET_IS_VOICE_REFERENCE"

    waveform = get_audio_waveform("default", asset["asset_id"], points=64)
    assert waveform["format"] == "normalized_peak_envelope"
    assert 1 <= waveform["point_count"] <= 64
    assert max(waveform["points"]) > 0.9
    assert waveform["duration_ms"] == 100
    contract = get_audio_asset_contract("default", asset["asset_id"])
    assert contract["audio"]["waveform_available"] is True
    assert contract["audio"]["duration_ms"] == 100

    conn = get_db()
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'audio_%'"
        )
    }
    assert tables == {
        "audio_voice_profiles",
        "audio_tasks",
        "audio_task_segments",
        "audio_task_results",
        "audio_asset_outputs",
        "audio_pronunciation_entries",
        "audio_task_events",
    }
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
    close_connection()


def test_chapter_tts_segments_outputs_review_and_outdated_trigger(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    mark_package_installed("aetherdb.kokoro-82m")
    voice = create_voice_profile(
        {
            "database_id": "default",
            "book_id": "default",
            "name": "Narrator",
            "locale": "zh-CN",
            "voice_kind": "native_voice",
            "package_id": "aetherdb.kokoro-82m",
            "package_voice_name": "zf_xiaobei",
        }
    )
    text = ("第一段内容。" * 100) + "\n\n" + ("Second segment. " * 80)
    conn = get_db()
    conn.execute(
        "INSERT INTO chapters(chapter_id,book_id,title,content) VALUES (?,?,?,?)",
        ("CHP_AUDIO", "default", "Audio chapter", text),
    )
    conn.commit()
    conn.close()

    task = create_audio_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "audio.tts.chapter",
            "chapter_id": "CHP_AUDIO",
            "voice_profile_id": voice["voice_profile_id"],
            "requested_backend": "auto",
            "start_execution": False,
        }
    )
    assert task["status"] == "planned"
    assert task["target_kind"] == "native_package"
    assert task["model_profile_id"] == "aetherdb-native-tts:kokoro-82m"
    assert len(task["segments"]) >= 2
    assert "source_text" not in task["segments"][0]
    detailed = get_audio_task(
        "default",
        task["task_id"],
        include_source_text=True,
    )
    assert detailed["segments"][0]["source_text"]
    listed = list_audio_tasks("default", book_id="default")
    assert listed["tasks"][0]["source_text_hash"] == task["source_text_hash"]
    assert "segments" not in listed["tasks"][0]

    output = import_audio("chapter-output.wav")
    pending = register_audio_output(
        "default",
        task["task_id"],
        {"asset_id": output["asset_id"], "output_kind": "final"},
    )
    assert pending["status"] == "pending_review"
    with pytest.raises(AudioContractError) as kind_error:
        register_audio_output(
            "default",
            task["task_id"],
            {"asset_id": output["asset_id"], "output_kind": "enhanced"},
        )
    assert kind_error.value.code == "AUDIO_OUTPUT_KIND_MISMATCH"
    approve(output["asset_id"])
    assert list_audio_tasks("default", book_id="default")["tasks"][0]["status"] == "completed"
    completed = get_audio_task("default", task["task_id"])
    assert completed["status"] == "completed"

    conn = get_db()
    conn.execute(
        "UPDATE chapters SET content=?,updated_at=CURRENT_TIMESTAMP WHERE chapter_id=?",
        (text + " changed", "CHP_AUDIO"),
    )
    conn.commit()
    conn.close()
    outdated = get_audio_task("default", task["task_id"])
    assert outdated["status"] == "outdated"
    assert outdated["outputs"][0]["freshness"] == "outdated"
    asset_contract = get_audio_asset_contract("default", output["asset_id"])
    assert asset_contract["audio"]["outdated"] is True
    close_connection()


def test_audio_task_publish_approves_output_and_binds_chapter_asset(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    mark_package_installed("aetherdb.kokoro-82m")
    voice = create_voice_profile(
        {
            "database_id": "default",
            "book_id": "default",
            "name": "Narrator",
            "locale": "zh-CN",
            "voice_kind": "native_voice",
            "package_id": "aetherdb.kokoro-82m",
            "package_voice_name": "zf_xiaobei",
        }
    )
    conn = get_db()
    conn.execute(
        "INSERT INTO chapters(chapter_id,book_id,title,content) VALUES (?,?,?,?)",
        ("CHP_AUDIO_PUBLISH", "default", "Audio publish", "一段用于发布的正文。"),
    )
    conn.commit()
    conn.close()
    task = create_audio_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "audio.tts.chapter",
            "chapter_id": "CHP_AUDIO_PUBLISH",
            "voice_profile_id": voice["voice_profile_id"],
            "start_execution": False,
        }
    )
    output = import_audio("chapter-publish.wav")
    pending = register_audio_output(
        "default",
        task["task_id"],
        {"asset_id": output["asset_id"], "output_kind": "merged"},
    )
    assert pending["status"] == "pending_review"

    status, body = asgi_request(
        app,
        "POST",
        f"/api/audio/tasks/{task['task_id']}/publish",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={"binding_type": "chapter_narration"},
    )

    assert status == 200
    assert body["task"]["status"] == "completed"
    assert body["asset"]["lifecycle_status"] == "approved"
    assert body["binding"]["target_type"] == "chapter"
    assert body["binding"]["target_id"] == "CHP_AUDIO_PUBLISH"
    assert body["binding"]["binding_type"] == "chapter_narration"
    close_connection()


def test_kokoro_native_voice_rejects_unverified_locale(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    mark_package_installed("aetherdb.kokoro-82m")

    with pytest.raises(AudioContractError) as error:
        create_voice_profile(
            {
                "database_id": "default",
                "book_id": "default",
                "name": "Unsupported narrator",
                "locale": "ja-JP",
                "voice_kind": "native_voice",
                "package_id": "aetherdb.kokoro-82m",
                "package_voice_name": "jf_alpha",
            }
        )

    assert error.value.code == "NATIVE_VOICE_NOT_DECLARED"

    with pytest.raises(AudioContractError) as mismatch:
        create_voice_profile(
            {
                "database_id": "default",
                "book_id": "default",
                "name": "Mismatched narrator",
                "locale": "zh-CN",
                "voice_kind": "native_voice",
                "package_id": "aetherdb.kokoro-82m",
                "package_voice_name": "af_heart",
            }
        )

    assert mismatch.value.code == "NATIVE_VOICE_LOCALE_MISMATCH"


def test_native_tts_is_segmented_retryable_and_uses_frozen_dictionary(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    mark_package_installed("aetherdb.kokoro-82m")
    entry = create_pronunciation_entry(
        {
            "database_id": "default",
            "book_id": "default",
            "locale": "en-US",
            "term": "Aether",
            "pronunciation": "Ether",
            "entry_kind": "replacement",
        }
    )
    voice = create_voice_profile(
        {
            "database_id": "default",
            "book_id": "default",
            "name": "Kokoro test narrator",
            "locale": "en-US",
            "voice_kind": "native_voice",
            "package_id": "aetherdb.kokoro-82m",
            "package_voice_name": "af_heart",
        }
    )
    assert voice["voice_kind"] == "native_voice"
    assert voice["package_id"] == "aetherdb.kokoro-82m"

    text = "Aether speaks clearly. " * 90
    conn = get_db()
    conn.execute(
        "INSERT INTO chapters(chapter_id,book_id,title,content) VALUES (?,?,?,?)",
        ("CHP_NATIVE_TTS", "default", "Native TTS", text),
    )
    conn.commit()
    conn.close()
    task = create_audio_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "audio.tts.chapter",
            "chapter_id": "CHP_NATIVE_TTS",
            "voice_profile_id": voice["voice_profile_id"],
            "requested_backend": "cpu",
            "execution_config": {
                "speed": 1.1,
                "segment_pause_ms": 80,
                "peak_target": 0.8,
            },
            "start_execution": False,
        }
    )
    assert task["target_kind"] == "native_package"
    assert task["package_id"] == "aetherdb.kokoro-82m"
    assert task["model_profile_id"] == "aetherdb-native-tts:kokoro-82m"
    assert task["model_package_version"] == "1.0.0"
    assert task["dictionary_entry_count"] == 1
    assert len(task["segments"]) >= 2

    # Later dictionary edits do not mutate this task's persisted preprocessing snapshot.
    conn = get_db()
    conn.execute(
        "UPDATE audio_pronunciation_entries SET pronunciation='Changed' "
        "WHERE entry_id=?",
        (entry["entry_id"],),
    )
    conn.commit()
    conn.close()

    first = FakeTTSExecutor(fail_segment_index=1)
    failed = run_audio_task("default", task["task_id"], executor=first)
    assert failed["status"] == "failed"
    assert failed["segments"][0]["status"] == "completed"
    assert failed["segments"][1]["status"] == "failed"
    assert first.texts[0].startswith("Ether")
    assert "Changed" not in first.texts[0]
    retained_asset_id = failed["segments"][0]["output_asset_id"]
    retained_attempts = failed["segments"][0]["attempts"]

    import services.tts_execution as tts_execution

    monkeypatch.setattr(tts_execution, "enqueue_audio_task", lambda *_args: None)
    retried = retry_failed_audio_task("default", task["task_id"])
    assert retried["status"] == "planned"
    assert retried["segments"][0]["status"] == "completed"
    assert retried["segments"][1]["status"] == "planned"

    completed_generation = run_audio_task(
        "default",
        task["task_id"],
        executor=FakeTTSExecutor(),
    )
    assert completed_generation["status"] == "pending_review"
    assert completed_generation["progress"] == 1.0
    assert completed_generation["segments"][0]["output_asset_id"] == retained_asset_id
    assert completed_generation["segments"][0]["attempts"] == retained_attempts
    assert all(
        segment["status"] == "completed"
        for segment in completed_generation["segments"]
    )
    final_asset_id = completed_generation["output_asset_id"]
    final_contract = get_audio_asset_contract("default", final_asset_id)
    assert final_contract["asset"]["lifecycle_status"] == "temporary"
    assert final_contract["audio"]["outdated"] is False
    approve(final_asset_id)
    assert get_audio_task("default", task["task_id"])["status"] == "completed"
    close_connection()


def test_ollama_tts_is_rejected_even_when_user_marks_the_profile_as_tts(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    create_provider(
        {
            "id": "ollama-audio",
            "display_name": "User Ollama",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "api_format": "ollama",
            "credential_ref": None,
            "models_endpoint": "/api/tags",
            "enabled": True,
            "supports_model_discovery": True,
        }
    )
    create_model_profile(
        {
            "id": "ollama-audio:my-voice",
            "provider_id": "ollama-audio",
            "provider_model_name": "my-lab/private-voice:v7",
            "display_name": "My private voice",
            "model_type": "tts",
            "enabled": True,
            "privacy_level": "local_only",
        }
    )
    with pytest.raises(AudioContractError) as raised:
        create_voice_profile(
            {
                "database_id": "default",
                "book_id": "default",
                "name": "Unsupported Ollama voice",
                "voice_kind": "provider_voice",
                "model_profile_id": "ollama-audio:my-voice",
                "provider_voice_name": "speaker-17",
            }
        )
    assert raised.value.code == "OLLAMA_TTS_UNSUPPORTED"
    close_connection()


def test_provider_voice_rejects_a_different_execution_model(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    create_provider(
        {
            "id": "cloud-audio",
            "display_name": "Cloud Audio",
            "provider_type": "openai_compatible",
            "base_url": "https://tts.example.test/v1",
            "api_format": "openai_audio",
            "credential_ref": None,
            "enabled": True,
            "supports_model_discovery": False,
        }
    )
    for profile_id, model_name in (
        ("cloud-audio:voice-a", "voice-a-v1"),
        ("cloud-audio:voice-b", "voice-b-v1"),
    ):
        create_model_profile(
            {
                "id": profile_id,
                "provider_id": "cloud-audio",
                "provider_model_name": model_name,
                "display_name": model_name,
                "model_type": "tts",
                "enabled": True,
                "privacy_level": "local_only",
            }
        )
    voice = create_voice_profile(
        {
            "database_id": "default",
            "book_id": "default",
            "name": "Voice A",
            "voice_kind": "provider_voice",
            "model_profile_id": "cloud-audio:voice-a",
            "provider_voice_name": "speaker-a",
        }
    )

    with pytest.raises(AudioContractError) as raised:
        create_audio_task(
            {
                "database_id": "default",
                "book_id": "default",
                "operation": "audio.tts.segment",
                "source_text": "This must remain on voice model A.",
                "voice_profile_id": voice["voice_profile_id"],
                "model_profile_id": "cloud-audio:voice-b",
            }
        )
    assert raised.value.code == "VOICE_EXECUTION_TARGET_MISMATCH"
    close_connection()


def test_asr_result_requires_review_and_text_never_enters_audit(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    asset = import_audio("interview.wav")
    task = create_audio_task(
        {
            "database_id": "default",
            "book_id": "default",
            "operation": "audio.asr.transcribe",
            "source_asset_ids": [asset["asset_id"]],
        }
    )
    transcript = "private transcript content"
    status, response = asgi_request(
        app,
        "POST",
        f"/api/audio/tasks/{task['task_id']}/results",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={
            "result_type": "transcript",
            "content_text": transcript,
            "metadata": {"language": "en"},
        },
    )
    assert status == 201
    pending = response["task"]
    assert pending["status"] == "pending_review"
    assert pending["results"][0]["content_text"] == transcript
    hidden = get_audio_task("default", task["task_id"])
    assert "content_text" not in hidden["results"][0]
    status, response = asgi_request(
        app,
        "POST",
        f"/api/audio/results/{pending['results'][0]['result_id']}/review",
        headers={"X-API-Key": USER_API_KEY},
        params={"database_id": "default"},
        json_body={"approved": True},
    )
    assert status == 200
    approved = response["task"]
    assert approved["status"] == "completed"
    assert approved["results"][0]["approval_status"] == "approved"

    conn = get_db()
    audit_text = json.dumps(
        [dict(row) for row in conn.execute("SELECT * FROM audit_log").fetchall()],
        ensure_ascii=False,
    )
    assert "audio.task.result" in audit_text
    assert "audio.result.review" in audit_text
    assert transcript not in audit_text
    conn.close()
    close_connection()


def test_audio_api_requires_auth_and_exposes_evidence_without_fake_hardware_claim(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    assert asgi_request(app, "GET", "/api/audio/status")[0] == 401
    status, body = asgi_request(
        app,
        "GET",
        "/api/audio/status",
        headers={"X-API-Key": USER_API_KEY},
    )
    assert status == 200
    assert body["execution_implemented"] is True
    assert body["default_audio_model"] is None
    assert body["model_selection"]["automatic_substitution"] is False
    assert body["hardware_evidence"]["rocm_verified"] is False
    close_connection()
