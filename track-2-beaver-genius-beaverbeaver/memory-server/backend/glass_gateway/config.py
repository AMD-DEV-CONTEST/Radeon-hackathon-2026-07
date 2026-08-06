from functools import lru_cache
import os
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource, EnvSettingsSource


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env(name: str, default: str | None = None) -> str | None:
    """Read the canonical unprefixed name, then the legacy GLASS_ alias."""
    return os.getenv(name, os.getenv(f"GLASS_{name}", default))


def _memory_data_root() -> Path:
    configured = _env("MEMORY_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (_project_root() / ".runtime").resolve()


def _memory_data_path(*parts: str) -> str:
    return str(_memory_data_root().joinpath(*parts))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=str(_project_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        legacy_env = EnvSettingsSource(settings_cls, env_prefix="GLASS_")
        legacy_dotenv = DotEnvSettingsSource(
            settings_cls,
            env_file=str(_project_root() / ".env"),
            env_file_encoding="utf-8",
            env_prefix="GLASS_",
        )
        return (
            init_settings,
            env_settings,
            legacy_env,
            dotenv_settings,
            legacy_dotenv,
            file_secret_settings,
        )

    device_token: str = Field(default="dev-token")
    user_tokens_json: SecretStr = Field(
        default_factory=lambda: SecretStr(_env("USER_TOKENS_JSON", "") or "")
    )
    auth_cookie_name: str = "beaver_session"
    auth_cookie_secure: bool = Field(
        default_factory=lambda: _env("AUTH_COOKIE_SECURE", "0") == "1"
    )
    memory_data_root: str = Field(
        default_factory=lambda: str(_memory_data_root())
    )
    asr_base_url: str | None = Field(default_factory=lambda: _env("CUSTOM_ASR_URL"))
    asr_api_key: str | None = None
    asr_model: str | None = None
    asr_fixed_text: str = "你好"
    memory_asr_provider: str = Field(
        default_factory=lambda: _env("MEMORY_ASR_PROVIDER", "legacy")
    )
    memory_asr_base_url: str | None = Field(
        default_factory=lambda: _env("MEMORY_ASR_BASE_URL")
    )
    memory_asr_api_key: str | None = Field(
        default_factory=lambda: _env("MEMORY_ASR_API_KEY")
    )
    memory_asr_model: str = Field(
        default_factory=lambda: _env(
            "MEMORY_ASR_MODEL", "fun-asr-flash-2026-06-15"
        )
    )
    memory_asr_language: str = Field(
        default_factory=lambda: _env("MEMORY_ASR_LANGUAGE", "auto")
    )
    memory_asr_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("MEMORY_ASR_TIMEOUT_SECONDS", "120")
        )
    )
    llm_base_url: str | None = Field(default_factory=lambda: _env("MINIMAX_LLM_BASE_URL"))
    llm_api_key: str | None = Field(default_factory=lambda: _env("MINIMAX_LLM_API_KEY"))
    llm_model: str | None = Field(default_factory=lambda: _env("MINIMAX_LLM_MODEL", "MiniMaxAI"))
    llm_fixed_reply: str = "你好，我在。你可以继续问我问题。"
    memory_scene_base_url: str | None = Field(
        default_factory=lambda: _env("DEEPSEEK_BASE_URL")
        or _env("OPENAI_BASE_URL")
        or _env("MINIMAX_LLM_BASE_URL")
    )
    memory_scene_api_key: str | None = Field(
        default_factory=lambda: _env("MEMORY_SCENE_API_KEY")
    )
    memory_scene_model: str | None = Field(
        default_factory=lambda: _env("DEEPSEEK_MODEL")
        or _env("OPENAI_MODEL")
        or _env("MINIMAX_LLM_MODEL")
        or "deepseek-chat"
    )
    memory_scene_timeout_seconds: float = Field(
        default_factory=lambda: float(_env("MEMORY_SCENE_TIMEOUT_SECONDS", "45"))
    )
    memory_scene_max_concurrency: int = Field(
        default_factory=lambda: max(
            1, int(_env("MEMORY_SCENE_MAX_CONCURRENCY", "1"))
        )
    )
    memory_scene_max_tokens: int = Field(
        default_factory=lambda: int(_env("MEMORY_SCENE_MAX_TOKENS", "1200"))
    )
    memory_scene_max_images: int = Field(
        default_factory=lambda: int(_env("MEMORY_SCENE_MAX_IMAGES", "5"))
    )
    memory_scene_attach_audio: bool = Field(
        default_factory=lambda: _env("MEMORY_SCENE_ATTACH_AUDIO", "1") != "0"
    )
    memory_scene_audio_transport: str = Field(
        default_factory=lambda: _env(
            "MEMORY_SCENE_AUDIO_TRANSPORT", "input_audio"
        )
    )
    memory_scene_max_audio_bytes: int = Field(
        default_factory=lambda: int(_env("MEMORY_SCENE_MAX_AUDIO_BYTES", "1572864"))
    )
    memory_context_enabled: bool = Field(
        default_factory=lambda: _env("MEMORY_CONTEXT_ENABLED", "1") != "0"
    )
    memory_context_base_url: str | None = Field(
        default_factory=lambda: _env("MEMORY_SCENE_BASE_URL")
        or _env("DEEPSEEK_BASE_URL")
        or _env("OPENAI_BASE_URL")
        or _env("MINIMAX_LLM_BASE_URL")
    )
    memory_context_api_key: str | None = Field(
        default_factory=lambda: _env("MEMORY_CONTEXT_API_KEY")
    )
    memory_context_model: str | None = Field(
        default_factory=lambda: _env("MEMORY_SCENE_MODEL")
        or _env("DEEPSEEK_MODEL")
        or _env("OPENAI_MODEL")
        or _env("MINIMAX_LLM_MODEL")
        or "deepseek-chat"
    )
    memory_context_timeout_seconds: float = Field(
        default_factory=lambda: float(_env("MEMORY_CONTEXT_TIMEOUT_SECONDS", "45"))
    )
    memory_context_max_tokens: int = Field(
        default_factory=lambda: int(_env("MEMORY_CONTEXT_MAX_TOKENS", "3200"))
    )
    memory_context_tail_chars: int = Field(
        default_factory=lambda: int(_env("MEMORY_CONTEXT_TAIL_CHARS", "24000"))
    )
    audio_denoise_filter: str | None = Field(
        default_factory=lambda: _env(
            "AUDIO_DENOISE_FILTER",
            "highpass=f=100,lowpass=f=10000,afftdn=nr=12:nf=-42:tn=1,"
            "loudnorm=I=-18:LRA=7:TP=-2",
        )
        or None
    )
    tts_url: str | None = Field(default_factory=lambda: _env("VOXCPM_TTS_URL"))
    tts_prompt_wav: str | None = Field(default_factory=lambda: _env("VOXCPM_PROMPT_WAV", "/assets/2food16k_2.wav"))
    dashscope_api_key: str | None = Field(default_factory=lambda: _env("DASHSCOPE_API_KEY"))
    dashscope_base_url: str = Field(default_factory=lambda: _env("DASHSCOPE_BASE_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"))
    dashscope_asr_model: str = Field(default_factory=lambda: _env("DASHSCOPE_ASR_MODEL", "qwen3-asr-flash-realtime-2026-02-10"))
    dashscope_tts_model: str = Field(default_factory=lambda: _env("DASHSCOPE_TTS_MODEL", "qwen3-tts-flash-realtime"))
    dashscope_tts_voice: str = Field(default_factory=lambda: _env("DASHSCOPE_TTS_VOICE", "Cherry"))
    dashscope_tts_sample_rate: int = Field(default_factory=lambda: int(_env("DASHSCOPE_TTS_SAMPLE_RATE", "24000")))
    heartbeat_ms: int = 15000
    audio_chunk_bytes: int = 4096
    command_max_ms: int = 8000
    photo_upload_dir: str = Field(
        default_factory=lambda: _env(
            "PHOTO_UPLOAD_DIR", _memory_data_path("received-photos")
        )
    )
    audio_upload_max_bytes: int = Field(
        default_factory=lambda: int(_env("AUDIO_UPLOAD_MAX_BYTES", "2097152"))
    )
    device_upload_body_timeout_seconds: float = Field(
        default_factory=lambda: max(
            0.1, float(_env("DEVICE_UPLOAD_BODY_TIMEOUT_SECONDS", "15"))
        )
    )
    raw_media_dir: str = Field(
        default_factory=lambda: _env("RAW_MEDIA_DIR", _memory_data_path("raw-media"))
    )
    memory_review_db_path: str = Field(
        default_factory=lambda: _env(
            "MEMORY_REVIEW_DB_PATH", _memory_data_path("memory-review.json")
        )
    )
    project_tracker_path: str = Field(
        default_factory=lambda: _env(
            "PROJECT_TRACKER_PATH", _memory_data_path("project-tracker.json")
        )
    )
    pm_write_token: str = Field(
        default_factory=lambda: _env("PM_WRITE_TOKEN", "dev-token")
    )
    everos_base_url: str = "http://127.0.0.1:8001"
    everos_root: str = Field(
        default_factory=lambda: _env(
            "EVEROS_ROOT",
            _memory_data_path("everos"),
        )
    )
    everos_app_id: str = "ai-glasses"
    everos_project_id: str = "beaver-memory-cn"
    everos_user_id: str = "owner"
    everos_timeout_seconds: float = 60.0
    memory_search_embedding_url: str = Field(
        default_factory=lambda: _env(
            "MEMORY_SEARCH_EMBEDDING_URL",
            "https://inference-service.example/embedding",
        )
    )
    memory_search_embedding_model: str = Field(
        default_factory=lambda: _env(
            "MEMORY_SEARCH_EMBEDDING_MODEL",
            "qwen3-vl-embedding",
        )
    )
    memory_search_embedding_api_key: str = Field(
        default_factory=lambda: _env("MEMORY_SEARCH_EMBEDDING_API_KEY", "")
    )
    memory_search_reranker_url: str = Field(
        default_factory=lambda: _env(
            "MEMORY_SEARCH_RERANKER_URL",
            "https://inference-service.example/rerank",
        )
    )
    memory_search_reranker_model: str = Field(
        default_factory=lambda: _env(
            "MEMORY_SEARCH_RERANKER_MODEL",
            "qwen3-vl-rerank",
        )
    )
    memory_search_reranker_api_key: str = Field(
        default_factory=lambda: _env("MEMORY_SEARCH_RERANKER_API_KEY", "")
    )
    memory_search_visual_projection_path: str = Field(
        default_factory=lambda: _env(
            "MEMORY_SEARCH_VISUAL_PROJECTION_PATH",
            _memory_data_path("memory-search", "visual-projection.jsonl"),
        )
    )
    memory_search_pipeline_version: str = "memory-search-v3-everos-episodes"
    memory_search_candidate_k: int = Field(
        default_factory=lambda: int(_env("MEMORY_SEARCH_CANDIDATE_K", "20"))
    )
    memory_search_visual_frames_per_episode: int = Field(
        default_factory=lambda: int(
            _env("MEMORY_SEARCH_VISUAL_FRAMES_PER_EPISODE", "100")
        )
    )
    memory_search_visual_reranker_candidates: int = Field(
        default_factory=lambda: int(
            _env("MEMORY_SEARCH_VISUAL_RERANKER_CANDIDATES", "10")
        )
    )
    memory_search_visual_embedding_weight: float = Field(
        default_factory=lambda: float(
            _env("MEMORY_SEARCH_VISUAL_EMBEDDING_WEIGHT", "0.25")
        )
    )
    memory_search_no_answer_min_score: float = Field(
        default_factory=lambda: float(
            _env("MEMORY_SEARCH_NO_ANSWER_MIN_SCORE", "0.4")
        )
    )
    memory_search_no_answer_min_margin: float | None = Field(
        default_factory=lambda: (
            float(_env("MEMORY_SEARCH_NO_ANSWER_MIN_MARGIN"))
            if _env("MEMORY_SEARCH_NO_ANSWER_MIN_MARGIN")
            else None
        )
    )
    memory_search_model_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("MEMORY_SEARCH_MODEL_TIMEOUT_SECONDS", "60")
        )
    )
    memory_search_upload_max_bytes: int = Field(
        default_factory=lambda: int(
            _env("MEMORY_SEARCH_UPLOAD_MAX_BYTES", "10485760")
        )
    )
    memory_capsule_window_ms: int = Field(
        default_factory=lambda: int(_env("MEMORY_CAPSULE_WINDOW_MS", "30000"))
    )
    memory_capsule_flush_ms: int = Field(
        default_factory=lambda: int(_env("MEMORY_CAPSULE_FLUSH_MS", "300000"))
    )
    memory_capsule_retry_ms: int = Field(
        default_factory=lambda: int(_env("MEMORY_CAPSULE_RETRY_MS", "60000"))
    )
    memory_image_late_grace_ms: int = Field(
        default_factory=lambda: int(_env("MEMORY_IMAGE_LATE_GRACE_MS", "10000"))
    )
    object_perception_enabled: bool = Field(
        default_factory=lambda: _env("OBJECT_PERCEPTION_ENABLED", "1") != "0"
    )
    object_perception_worker_url: str = Field(
        default_factory=lambda: _env(
            "OBJECT_PERCEPTION_WORKER_URL", "http://127.0.0.1:8791"
        )
    )
    object_perception_base_url: str = Field(
        default_factory=lambda: _env(
            "OBJECT_PERCEPTION_BASE_URL",
            _env("OBJECT_PERCEPTION_WORKER_URL", "http://127.0.0.1:8791"),
        )
    )
    object_perception_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(
            _env("OBJECT_PERCEPTION_API_KEY", "")
        )
    )
    object_perception_model: str = Field(
        default_factory=lambda: _env(
            "OBJECT_PERCEPTION_MODEL",
            _env("OBJECT_PERCEPTION_MODEL_ID", "yoloe-26s"),
        )
    )
    object_perception_max_media_bytes: int = Field(
        default_factory=lambda: int(
            _env("OBJECT_PERCEPTION_MAX_MEDIA_BYTES", "10485760")
        )
    )
    object_perception_store_path: str = Field(
        default_factory=lambda: _env(
            "OBJECT_PERCEPTION_STORE_PATH",
            _memory_data_path("object-perception", "jobs.json"),
        )
    )
    object_perception_vocabulary_path: str = Field(
        default_factory=lambda: _env(
            "OBJECT_PERCEPTION_VOCABULARY_PATH",
            str(Path(__file__).resolve().parent / "object_perception" / "vocabulary.v2.json"),
        )
    )
    object_perception_model_id: str = Field(
        default_factory=lambda: _env("OBJECT_PERCEPTION_MODEL_ID", "yoloe-26s")
    )
    object_perception_model_version: str = Field(
        default_factory=lambda: _env(
            "OBJECT_PERCEPTION_MODEL_VERSION", "yoloe-26s-seg-v1"
        )
    )
    object_perception_wait_ms: int = Field(
        default_factory=lambda: int(_env("OBJECT_PERCEPTION_WAIT_MS", "500"))
    )
    object_perception_stale_ms: int = Field(
        default_factory=lambda: int(_env("OBJECT_PERCEPTION_STALE_MS", "10000"))
    )
    object_perception_max_classes: int = Field(
        default_factory=lambda: int(_env("OBJECT_PERCEPTION_MAX_CLASSES", "120"))
    )
    object_perception_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("OBJECT_PERCEPTION_TIMEOUT_SECONDS", "10")
        )
    )
    object_card_enabled: bool = Field(
        default_factory=lambda: _env("OBJECT_CARD_ENABLED", "1") != "0"
    )
    object_card_base_url: str | None = Field(
        default_factory=lambda: _env("OBJECT_CARD_BASE_URL")
        or _env("MEMORY_SCENE_BASE_URL")
        or _env("OPENAI_BASE_URL")
    )
    object_card_api_key: str | None = Field(
        default_factory=lambda: _env("OBJECT_CARD_API_KEY")
    )
    object_card_model: str | None = Field(
        default_factory=lambda: _env("OBJECT_CARD_MODEL")
        or _env("MEMORY_SCENE_MODEL")
        or _env("OPENAI_MODEL")
        or "mimo-v2.5"
    )
    object_card_timeout_seconds: float = Field(
        default_factory=lambda: float(_env("OBJECT_CARD_TIMEOUT_SECONDS", "45"))
    )
    object_card_max_tokens: int = Field(
        default_factory=lambda: int(_env("OBJECT_CARD_MAX_TOKENS", "3200"))
    )
    object_card_max_images: int = Field(
        default_factory=lambda: int(_env("OBJECT_CARD_MAX_IMAGES", "6"))
    )
    object_card_allow_partial_candidates: bool = Field(
        default_factory=lambda: _env(
            "OBJECT_CARD_ALLOW_PARTIAL_CANDIDATES", "0"
        )
        != "0"
    )
    commitment_extraction_enabled: bool = Field(
        default_factory=lambda: _env("COMMITMENT_EXTRACTION_ENABLED", "1") != "0"
    )
    commitment_extraction_base_url: str | None = Field(
        default_factory=lambda: _env("COMMITMENT_EXTRACTION_BASE_URL")
        or _env("OBJECT_CARD_BASE_URL")
        or _env("MEMORY_SCENE_BASE_URL")
        or _env("OPENAI_BASE_URL")
    )
    commitment_extraction_api_key: str | None = Field(
        default_factory=lambda: _env("COMMITMENT_EXTRACTION_API_KEY")
    )
    commitment_extraction_model: str | None = Field(
        default_factory=lambda: _env("COMMITMENT_EXTRACTION_MODEL")
        or _env("OBJECT_CARD_MODEL")
        or _env("MEMORY_SCENE_MODEL")
        or _env("OPENAI_MODEL")
        or "mimo-v2.5"
    )
    commitment_extraction_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("COMMITMENT_EXTRACTION_TIMEOUT_SECONDS", "45")
        )
    )
    commitment_extraction_max_tokens: int = Field(
        default_factory=lambda: int(
            _env("COMMITMENT_EXTRACTION_MAX_TOKENS", "1600")
        )
    )
    daily_review_enabled: bool = Field(
        default_factory=lambda: _env("DAILY_REVIEW_ENABLED", "1") != "0"
    )
    daily_review_scheduler_enabled: bool = Field(
        default_factory=lambda: _env("DAILY_REVIEW_SCHEDULER_ENABLED", "1")
        != "0"
    )
    daily_review_timezone: str = Field(
        default_factory=lambda: _env(
            "DAILY_REVIEW_TIMEZONE", "Asia/Shanghai"
        )
    )
    daily_review_schedule_hour: int = Field(
        default_factory=lambda: int(
            _env("DAILY_REVIEW_SCHEDULE_HOUR", "22")
        )
    )
    daily_review_initial_delay_seconds: float = Field(
        default_factory=lambda: float(
            _env("DAILY_REVIEW_INITIAL_DELAY_SECONDS", "60")
        )
    )
    daily_review_poll_seconds: float = Field(
        default_factory=lambda: float(
            _env("DAILY_REVIEW_POLL_SECONDS", "60")
        )
    )
    daily_review_base_url: str | None = Field(
        default_factory=lambda: _env("DAILY_REVIEW_BASE_URL")
        or _env("COMMITMENT_EXTRACTION_BASE_URL")
        or _env("MEMORY_SCENE_BASE_URL")
        or _env("OPENAI_BASE_URL")
    )
    daily_review_api_key: str | None = Field(
        default_factory=lambda: _env("DAILY_REVIEW_API_KEY")
    )
    daily_review_model: str | None = Field(
        default_factory=lambda: _env("DAILY_REVIEW_MODEL")
        or _env("COMMITMENT_EXTRACTION_MODEL")
        or _env("MEMORY_SCENE_MODEL")
        or _env("OPENAI_MODEL")
        or "mimo-v2.5"
    )
    daily_review_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("DAILY_REVIEW_TIMEOUT_SECONDS", "60")
        )
    )
    daily_review_max_tokens: int = Field(
        default_factory=lambda: int(
            _env("DAILY_REVIEW_MAX_TOKENS", "4000")
        )
    )
    speech_presence_enabled: bool = Field(
        default_factory=lambda: _env("SPEECH_PRESENCE_ENABLED", "1") != "0"
    )
    speech_presence_fsmn_model_path: str = Field(
        default_factory=lambda: _env(
            "SPEECH_PRESENCE_FSMN_MODEL_PATH",
            str(_project_root() / ".runtime/models/fsmn-vad"),
        )
    )
    speech_presence_audioset_model_path: str = Field(
        default_factory=lambda: _env(
            "SPEECH_PRESENCE_AUDIOSET_MODEL_PATH",
            str(_project_root() / ".runtime/models/ast-audioset"),
        )
    )
    speech_presence_fsmn_revision: str = "f9a8b8274674755d925277e27063869038d41515"
    speech_presence_audioset_revision: str = "f826b80d28226b62986cc218e5cec390b1096902"
    speech_presence_silero_version: str = "6.2.1"
    speech_presence_ten_vad_enabled: bool = Field(
        default_factory=lambda: _env("SPEECH_PRESENCE_TEN_VAD_ENABLED", "1") != "0"
    )
    speech_presence_ten_vad_version: str = "1.0.6.8@22a3bcd4509d0faaa8eef4881e8af5f39c178950"
    speech_presence_ten_vad_threshold: float = Field(
        default_factory=lambda: float(
            _env("SPEECH_PRESENCE_TEN_VAD_THRESHOLD", "0.90")
        )
    )
    speech_presence_ten_vad_min_frames: int = Field(
        default_factory=lambda: int(
            _env("SPEECH_PRESENCE_TEN_VAD_MIN_FRAMES", "3")
        )
    )
    speech_presence_device: str = Field(
        default_factory=lambda: _env("SPEECH_PRESENCE_DEVICE", "cuda:0")
    )
    speech_presence_silence_dbfs: float = Field(
        default_factory=lambda: float(_env("SPEECH_PRESENCE_SILENCE_DBFS", "-55"))
    )
    speech_presence_probability_threshold: float = Field(
        default_factory=lambda: float(
            _env("SPEECH_PRESENCE_PROBABILITY_THRESHOLD", "0.05")
        )
    )
    speech_presence_short_recovery_ms: int = Field(
        default_factory=lambda: int(_env("SPEECH_PRESENCE_SHORT_RECOVERY_MS", "500"))
    )
    speech_presence_segment_padding_ms: int = Field(
        default_factory=lambda: int(_env("SPEECH_PRESENCE_SEGMENT_PADDING_MS", "200"))
    )
    window_asr_full_window_enabled: bool = Field(
        default_factory=lambda: _env("WINDOW_ASR_FULL_WINDOW_ENABLED", "1") != "0"
    )
    window_asr_tail_guard_ms: int = Field(
        default_factory=lambda: int(_env("WINDOW_ASR_TAIL_GUARD_MS", "5000"))
    )
    window_asr_fallback_speech_probability: float = Field(
        default_factory=lambda: float(
            _env("WINDOW_ASR_FALLBACK_SPEECH_PROBABILITY", "0.50")
        )
    )
    voice_perception_enabled: bool = Field(
        default_factory=lambda: _env("VOICE_PERCEPTION_ENABLED", "1") != "0"
    )
    voice_worker_url: str = Field(
        default_factory=lambda: _env(
            "VOICE_WORKER_URL", "http://127.0.0.1:8795"
        )
    )
    voice_base_url: str = Field(
        default_factory=lambda: _env(
            "VOICE_BASE_URL",
            _env("VOICE_WORKER_URL", "http://127.0.0.1:8795"),
        )
    )
    voice_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(_env("VOICE_API_KEY", ""))
    )
    voice_model: str = Field(
        default_factory=lambda: _env(
            "VOICE_MODEL", "sortformer-wespeaker"
        )
    )
    voice_max_media_bytes: int = Field(
        default_factory=lambda: int(
            _env("VOICE_MAX_MEDIA_BYTES", "33554432")
        )
    )
    voice_worker_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("VOICE_WORKER_TIMEOUT_SECONDS", "120")
        )
    )
    voice_worker_retry_seconds: float = Field(
        default_factory=lambda: float(
            _env("VOICE_WORKER_RETRY_SECONDS", "5")
        )
    )
    voice_job_store_path: str = Field(
        default_factory=lambda: _env(
            "VOICE_JOB_STORE_PATH",
            _memory_data_path("voice", "voice-jobs.json"),
        )
    )
    voice_embedding_store_path: str = Field(
        default_factory=lambda: _env(
            "VOICE_EMBEDDING_STORE_PATH",
            _memory_data_path("voice", "protected", "voice-job-embeddings.json"),
        )
    )
    voice_directory_path: str = Field(
        default_factory=lambda: _env(
            "VOICE_DIRECTORY_PATH",
            _memory_data_path("voice", "voice-directory.json"),
        )
    )
    voice_directory_protected_path: str = Field(
        default_factory=lambda: _env(
            "VOICE_DIRECTORY_PROTECTED_PATH",
            _memory_data_path("voice", "protected", "voice-directory-vectors.json"),
        )
    )
    voice_config_path: str = Field(
        default_factory=lambda: _env(
            "VOICE_CONFIG_PATH",
            str(
                _project_root()
                / "evaluation/speaker/configs/speaker-candidate-production-v1.json"
            ),
        )
    )
    voice_projection_wait_ms: int = Field(
        default_factory=lambda: int(_env("VOICE_PROJECTION_WAIT_MS", "350"))
    )
    voice_max_jobs: int = Field(
        default_factory=lambda: int(_env("VOICE_MAX_JOBS", "10000"))
    )
    identity_face_enabled: bool = Field(
        default_factory=lambda: _env("IDENTITY_FACE_ENABLED", "1") != "0"
    )
    identity_perception_enabled: bool = Field(
        default_factory=lambda: _env(
            "IDENTITY_PERCEPTION_ENABLED",
            _env("IDENTITY_FACE_ENABLED", "1"),
        )
        != "0"
    )
    identity_worker_url: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_WORKER_URL", "http://127.0.0.1:8794"
        )
    )
    identity_base_url: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_BASE_URL",
            _env("IDENTITY_WORKER_URL", "http://127.0.0.1:8794"),
        )
    )
    identity_api_key: SecretStr = Field(
        default_factory=lambda: SecretStr(_env("IDENTITY_API_KEY", ""))
    )
    identity_model: str = Field(
        default_factory=lambda: _env("IDENTITY_MODEL", "insightface")
    )
    identity_max_media_bytes: int = Field(
        default_factory=lambda: int(
            _env("IDENTITY_MAX_MEDIA_BYTES", "10485760")
        )
    )
    identity_worker_timeout_seconds: float = Field(
        default_factory=lambda: float(
            _env("IDENTITY_WORKER_TIMEOUT_SECONDS", "15")
        )
    )
    identity_worker_retry_seconds: float = Field(
        default_factory=lambda: float(
            _env("IDENTITY_WORKER_RETRY_SECONDS", "5")
        )
    )
    identity_job_store_path: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_JOB_STORE_PATH",
            _memory_data_path("identity", "face-jobs.json"),
        )
    )
    identity_embedding_store_path: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_EMBEDDING_STORE_PATH",
            _memory_data_path("identity", "protected", "face-job-embeddings.json"),
        )
    )
    identity_directory_path: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_DIRECTORY_PATH",
            _memory_data_path("identity", "identity-directory.json"),
        )
    )
    identity_directory_protected_path: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_DIRECTORY_PROTECTED_PATH",
            _memory_data_path("identity", "protected", "identity-directory-vectors.json"),
        )
    )
    identity_config_path: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_CONFIG_PATH",
            str(
                _project_root()
                / "evaluation/identity/configs/face-candidate-production-v1.json"
            ),
        )
    )
    identity_gallery_policy_path: str = Field(
        default_factory=lambda: _env(
            "IDENTITY_GALLERY_POLICY_PATH",
            str(
                _project_root()
                / "evaluation/identity/configs/face-gallery-single-frame-demo-v1.json"
            ),
        )
    )
    identity_projection_wait_ms: int = Field(
        default_factory=lambda: int(_env("IDENTITY_PROJECTION_WAIT_MS", "350"))
    )
    identity_max_jobs: int = Field(
        default_factory=lambda: int(_env("IDENTITY_MAX_JOBS", "10000"))
    )
    identity_voice_enabled: bool = Field(
        default_factory=lambda: _env("IDENTITY_VOICE_ENABLED", "1") != "0"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
