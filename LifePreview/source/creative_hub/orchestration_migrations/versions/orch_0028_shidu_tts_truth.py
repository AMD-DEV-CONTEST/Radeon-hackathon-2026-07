"""Harden immutable Shidu voice preset and TTS take truth.

Revision ID: orch_0028
Revises: orch_0027
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "orch_0028"
down_revision = "orch_0027"
branch_labels = None
depends_on = None

SCHEMA = "orchestration"


def upgrade() -> None:
    for column in (
        sa.Column("model_digest", sa.String(64), nullable=False),
        sa.Column("language", sa.String(100), nullable=False),
        sa.Column("instruction_digest", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("discovery_service_version", sa.String(100), nullable=False),
        sa.Column("discovery_tool_name", sa.String(200), nullable=False),
        sa.Column("discovery_schema_digest", sa.String(64), nullable=False),
    ):
        op.add_column("voice_preset_revisions", column, schema=SCHEMA)
    op.create_check_constraint(
        "ck_orch_voice_presets_model_digest",
        "voice_preset_revisions",
        "length(model_digest) = 64",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_voice_presets_instruction_digest",
        "voice_preset_revisions",
        "length(instruction_digest) = 64",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_orch_voice_presets_discovery_schema_digest",
        "voice_preset_revisions",
        "length(discovery_schema_digest) = 64",
        schema=SCHEMA,
    )
    for name, condition in (
        (
            "ck_orch_voice_presets_provider",
            "provider = 'qwen3-tts-custom-voice-mcp'",
        ),
        (
            "ck_orch_voice_presets_model",
            "model_id = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'",
        ),
        ("ck_orch_voice_presets_language", "language = 'Chinese'"),
        (
            "ck_orch_voice_presets_tool",
            "discovery_tool_name = 'qwen_tts.custom_voice'",
        ),
        (
            "ck_orch_voice_presets_schema",
            "discovery_schema_digest = '99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa'",
        ),
        (
            "ck_orch_voice_presets_speaker",
            "speaker IN ('Serena', 'Uncle_Fu', 'Vivian', 'Dylan')",
        ),
    ):
        op.create_check_constraint(
            name, "voice_preset_revisions", condition, schema=SCHEMA
        )

    for column in (
        sa.Column("requested_provider", sa.String(100), nullable=False),
        sa.Column("requested_model_id", sa.String(200), nullable=False),
        sa.Column("actual_provider", sa.String(100), nullable=False),
        sa.Column("actual_model_id", sa.String(200), nullable=False),
        sa.Column("actual_service_version", sa.String(100), nullable=False),
        sa.Column("actual_tool_name", sa.String(200), nullable=False),
        sa.Column("actual_schema_digest", sa.String(64), nullable=False),
        sa.Column("speaker", sa.String(100), nullable=False),
        sa.Column("language", sa.String(100), nullable=False),
        sa.Column("instruction_digest", sa.String(64), nullable=False),
        sa.Column("audio_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("audio_byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=False),
        sa.Column("channels", sa.Integer(), nullable=False),
        sa.Column("pcm_sample_width_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("peak_amplitude", sa.Float(), nullable=False),
        sa.Column("clipping_ratio", sa.Float(), nullable=False),
        sa.Column("silence_ratio", sa.Float(), nullable=False),
        sa.Column("leading_silence_seconds", sa.Float(), nullable=False),
        sa.Column("trailing_silence_seconds", sa.Float(), nullable=False),
        sa.Column("qc_accepted", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_classification", sa.String(100), nullable=True),
        sa.Column("lipsync_required", sa.Boolean(), nullable=False),
    ):
        op.add_column("tts_takes", column, schema=SCHEMA)
    for name, condition in (
        ("ck_orch_tts_takes_schema_digest", "length(actual_schema_digest) = 64"),
        ("ck_orch_tts_takes_instruction_digest", "length(instruction_digest) = 64"),
        ("ck_orch_tts_takes_audio_size", "audio_byte_size > 44"),
        ("ck_orch_tts_takes_sample_rate", "sample_rate_hz = 24000"),
        ("ck_orch_tts_takes_channels", "channels = 1"),
        ("ck_orch_tts_takes_pcm_width", "pcm_sample_width_bytes = 2"),
        (
            "ck_orch_tts_takes_duration",
            "duration_seconds > 0 AND duration_seconds <= 300",
        ),
        (
            "ck_orch_tts_takes_peak",
            "peak_amplitude >= 0 AND peak_amplitude <= 1",
        ),
        (
            "ck_orch_tts_takes_clipping",
            "clipping_ratio >= 0 AND clipping_ratio <= 1",
        ),
        (
            "ck_orch_tts_takes_silence",
            "silence_ratio >= 0 AND silence_ratio <= 1",
        ),
        (
            "ck_orch_tts_takes_edge_silence",
            "leading_silence_seconds >= 0 AND trailing_silence_seconds >= 0",
        ),
        ("ck_orch_tts_takes_qc_accepted", "qc_accepted"),
        ("ck_orch_tts_takes_retry_count", "retry_count BETWEEN 0 AND 3"),
        ("ck_orch_tts_takes_no_lipsync", "NOT lipsync_required"),
        (
            "ck_orch_tts_takes_provider",
            "requested_provider = 'qwen3-tts-custom-voice-mcp' AND actual_provider = 'qwen3-tts-custom-voice-mcp'",
        ),
        (
            "ck_orch_tts_takes_model",
            "requested_model_id = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice' AND actual_model_id = 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'",
        ),
        ("ck_orch_tts_takes_tool", "actual_tool_name = 'qwen_tts.custom_voice'"),
        (
            "ck_orch_tts_takes_schema",
            "actual_schema_digest = '99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa'",
        ),
        (
            "ck_orch_tts_takes_speaker",
            "speaker IN ('Serena', 'Uncle_Fu', 'Vivian', 'Dylan')",
        ),
        ("ck_orch_tts_takes_language", "language = 'Chinese'"),
        ("ck_orch_tts_takes_success_error", "error_classification IS NULL"),
    ):
        op.create_check_constraint(name, "tts_takes", condition, schema=SCHEMA)


def downgrade() -> None:
    for name in (
        "ck_orch_tts_takes_no_lipsync",
        "ck_orch_tts_takes_success_error",
        "ck_orch_tts_takes_language",
        "ck_orch_tts_takes_speaker",
        "ck_orch_tts_takes_schema",
        "ck_orch_tts_takes_tool",
        "ck_orch_tts_takes_model",
        "ck_orch_tts_takes_provider",
        "ck_orch_tts_takes_retry_count",
        "ck_orch_tts_takes_qc_accepted",
        "ck_orch_tts_takes_edge_silence",
        "ck_orch_tts_takes_silence",
        "ck_orch_tts_takes_clipping",
        "ck_orch_tts_takes_peak",
        "ck_orch_tts_takes_duration",
        "ck_orch_tts_takes_pcm_width",
        "ck_orch_tts_takes_channels",
        "ck_orch_tts_takes_sample_rate",
        "ck_orch_tts_takes_audio_size",
        "ck_orch_tts_takes_instruction_digest",
        "ck_orch_tts_takes_schema_digest",
    ):
        op.drop_constraint(name, "tts_takes", schema=SCHEMA, type_="check")
    for name in (
        "lipsync_required",
        "error_classification",
        "retry_count",
        "qc_accepted",
        "trailing_silence_seconds",
        "leading_silence_seconds",
        "silence_ratio",
        "clipping_ratio",
        "peak_amplitude",
        "duration_seconds",
        "pcm_sample_width_bytes",
        "channels",
        "sample_rate_hz",
        "audio_byte_size",
        "audio_artifact_id",
        "instruction_digest",
        "language",
        "speaker",
        "actual_schema_digest",
        "actual_tool_name",
        "actual_service_version",
        "actual_model_id",
        "actual_provider",
        "requested_model_id",
        "requested_provider",
    ):
        op.drop_column("tts_takes", name, schema=SCHEMA)

    for name in (
        "ck_orch_voice_presets_speaker",
        "ck_orch_voice_presets_schema",
        "ck_orch_voice_presets_tool",
        "ck_orch_voice_presets_language",
        "ck_orch_voice_presets_model",
        "ck_orch_voice_presets_provider",
        "ck_orch_voice_presets_discovery_schema_digest",
        "ck_orch_voice_presets_instruction_digest",
        "ck_orch_voice_presets_model_digest",
    ):
        op.drop_constraint(
            name, "voice_preset_revisions", schema=SCHEMA, type_="check"
        )
    for name in (
        "discovery_schema_digest",
        "discovery_tool_name",
        "discovery_service_version",
        "enabled",
        "instruction_digest",
        "language",
        "model_digest",
    ):
        op.drop_column("voice_preset_revisions", name, schema=SCHEMA)
