import asyncio
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from glass_gateway.config import Settings, get_settings
from glass_gateway.integrations.everos import EverOSClient
from glass_gateway.integrations.everos_markdown import EverOSMarkdownReader
from glass_gateway.identity_perception.client import IdentityWorkerClient
from glass_gateway.identity_perception.coordinator import IdentityCoordinator
from glass_gateway.identity_perception.directory import (
    IdentityCandidateProcessor,
    IdentityDirectoryStore,
)
from glass_gateway.identity_perception.revisions import model_revision_from_config
from glass_gateway.identity_perception.store import IdentityJobStore
from glass_gateway.voice_perception.client import VoiceWorkerClient
from glass_gateway.voice_perception.coordinator import VoiceCoordinator
from glass_gateway.voice_perception.directory import VoiceCandidateDirectory
from glass_gateway.voice_perception.revisions import voice_model_revision_from_config
from glass_gateway.voice_perception.postprocessor import VoiceCandidatePostprocessor
from glass_gateway.voice_perception.store import VoiceJobStore
from glass_gateway.object_perception.client import ObjectPerceptionWorkerClient
from glass_gateway.object_perception.coordinator import ObjectPerceptionCoordinator
from glass_gateway.object_perception.store import ObjectPerceptionStore
from glass_gateway.object_perception.vocabulary import VocabularyComposer
from glass_gateway.providers.asr.mimo import MimoASRProvider
from glass_gateway.providers.asr.dashscope_http import DashScopeHTTPASRProvider
from glass_gateway.providers.asr.openai_compatible import OpenAICompatibleASRProvider
from glass_gateway.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from glass_gateway.providers.tts.dashscope_realtime import DashScopeRealtimeTTSProvider
from glass_gateway.services.audio_turn_manager import AudioTurnManager
from glass_gateway.services.card_planner import CardPlanner
from glass_gateway.services.capture_manager import CaptureManager
from glass_gateway.services.commitment_extractor import CommitmentExtractor
from glass_gateway.services.correction_writeback import CorrectionWritebackService
from glass_gateway.services.daily_review import DailyReviewScheduler, DailyReviewService
from glass_gateway.services.device_status_store import DeviceStatusStore
from glass_gateway.services.everos_bridge import EverOSMeetingBridge
from glass_gateway.services.event_context_stabilizer import (
    OpenAICompatibleEventContextStabilizer,
)
from glass_gateway.services.local_identity_recognition import LocalIdentityRecognizer
from glass_gateway.services.memory_capsule_bridge import EverOSCapsuleBridge
from glass_gateway.services.memory_review_store import MemoryReviewStore
from glass_gateway.services.object_card_interpreter import OpenAICompatibleObjectCardInterpreter
from glass_gateway.services.memory_search import ProductionMemorySearch
from glass_gateway.services.memory_scene_interpreter import OpenAICompatibleMemorySceneInterpreter
from glass_gateway.services.media_converter import MediaConverter
from glass_gateway.services.object_search_tool import ObjectSearchTool
from glass_gateway.services.production_identity_recognition import (
    ProductionIdentityRecognizer,
)
from glass_gateway.services.production_voice_recognition import (
    ProductionVoiceRecognizer,
)
from glass_gateway.services.reliable_media_store import ReliableMediaStore
from glass_gateway.services.session_manager import SessionManager
from glass_gateway.services.speech_presence import (
    CompositeSpeechPresenceDetector,
    PresenceDecisionConfig,
)


class LiveOnlyASRTranscriber:
    language = "zh"

    def __init__(
        self,
        asr: OpenAICompatibleASRProvider,
        *,
        minimum_timeout_seconds: float = 35.0,
        maximum_timeout_seconds: float = 120.0,
    ) -> None:
        self.asr = asr
        self.minimum_timeout_seconds = minimum_timeout_seconds
        self.maximum_timeout_seconds = maximum_timeout_seconds

    @property
    def provider_name(self) -> str:
        if self.asr.settings.dashscope_api_key:
            return "dashscope"
        if self.asr.settings.asr_base_url:
            return "custom_http"
        return "unavailable"

    @property
    def model_name(self) -> str:
        if self.asr.settings.dashscope_api_key:
            return self.asr.settings.dashscope_asr_model
        return self.asr.settings.asr_model or "provider-default"

    async def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        duration_seconds = len(pcm_bytes) / max(1, sample_rate * 2)
        timeout_seconds = min(
            self.maximum_timeout_seconds,
            max(self.minimum_timeout_seconds, 40.0 + duration_seconds * 0.75),
        )
        return await asyncio.wait_for(
            self.asr.transcribe_live_strict(pcm_bytes, sample_rate),
            timeout=timeout_seconds,
        )


class AppState:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.sessions = SessionManager()
        self.audio_turns = AudioTurnManager()
        self.cards = CardPlanner()
        self.asr = OpenAICompatibleASRProvider(self.settings)
        memory_asr_provider = self.settings.memory_asr_provider.strip().lower()
        if memory_asr_provider == "mimo":
            self.memory_asr = MimoASRProvider(
                api_key=self.settings.memory_asr_api_key or "",
                base_url=(
                    self.settings.memory_asr_base_url
                    or "https://asr-service.example/v1"
                ),
                model=self.settings.memory_asr_model,
                language=self.settings.memory_asr_language,
                timeout_seconds=self.settings.memory_asr_timeout_seconds,
            )
        elif memory_asr_provider in {"dashscope_http", "dashscope_json"}:
            self.memory_asr = DashScopeHTTPASRProvider(
                api_key=self.settings.memory_asr_api_key or "",
                endpoint=(
                    self.settings.memory_asr_base_url
                    or "https://asr-service.example/transcriptions"
                ),
                model=self.settings.memory_asr_model,
                language=self.settings.memory_asr_language,
                timeout_seconds=self.settings.memory_asr_timeout_seconds,
            )
        elif memory_asr_provider in {"legacy", "custom_http", "dashscope"}:
            self.memory_asr = LiveOnlyASRTranscriber(self.asr)
        else:
            raise ValueError(
                f"unsupported memory ASR provider: {self.settings.memory_asr_provider}"
            )
        self.llm = OpenAICompatibleLLMProvider(self.settings)
        self.tts = DashScopeRealtimeTTSProvider(self.settings)
        self.device_sockets: dict[str, WebSocket] = {}
        self.device_status = DeviceStatusStore()
        self.everos = EverOSClient(
            base_url=self.settings.everos_base_url,
            app_id=self.settings.everos_app_id,
            project_id=self.settings.everos_project_id,
            timeout_seconds=self.settings.everos_timeout_seconds,
        )
        self.everos_markdown = EverOSMarkdownReader(
            root=self.settings.everos_root,
            app_id=self.settings.everos_app_id,
            project_id=self.settings.everos_project_id,
        )
        self.memory_review_store = MemoryReviewStore(self.settings.memory_review_db_path)
        self.reliable_media = ReliableMediaStore(
            Path(self.settings.raw_media_dir) / "reliable-upload"
        )
        self.daily_review = DailyReviewService(
            self.settings,
            everos_getter=lambda: self.everos,
            markdown_getter=lambda: self.everos_markdown,
            store_getter=lambda: self.memory_review_store,
        )
        self.daily_review_scheduler = DailyReviewScheduler(
            self.settings,
            self.daily_review,
        )
        self.commitment_extractor = CommitmentExtractor(
            self.settings,
            self.memory_review_store,
        )
        self.correction_writeback = CorrectionWritebackService(
            review_store_getter=lambda: self.memory_review_store,
            everos_getter=lambda: self.everos,
            user_id=self.settings.everos_user_id,
            timeout_seconds=self.settings.everos_timeout_seconds,
            retry_interval_seconds=max(
                1.0, self.settings.memory_capsule_retry_ms / 1000
            ),
        )
        self.memory_search = ProductionMemorySearch(self.settings)
        self.object_search = ObjectSearchTool(
            self.settings,
            self.memory_review_store,
            post_json=self.memory_search._post_json,
        )
        self.object_perception_store = ObjectPerceptionStore(
            self.settings.object_perception_store_path
        )
        self.object_perception = (
            ObjectPerceptionCoordinator(
                store=self.object_perception_store,
                vocabulary=VocabularyComposer(
                    self.settings.object_perception_vocabulary_path,
                    review_store=self.memory_review_store,
                    max_classes=self.settings.object_perception_max_classes,
                ),
                worker_client=ObjectPerceptionWorkerClient(
                    self.settings.object_perception_base_url,
                    api_key=self.settings.object_perception_api_key.get_secret_value(),
                    model=self.settings.object_perception_model,
                    timeout_seconds=self.settings.object_perception_timeout_seconds,
                    max_media_bytes=self.settings.object_perception_max_media_bytes,
                ),
                model_id=self.settings.object_perception_model_id,
                model_version=self.settings.object_perception_model_version,
                wait_ms=self.settings.object_perception_wait_ms,
                stale_ms=self.settings.object_perception_stale_ms,
                review_store=self.memory_review_store,
            )
            if self.settings.object_perception_enabled
            else None
        )
        self.identity_job_store = IdentityJobStore(
            self.settings.identity_job_store_path,
            embedding_path=self.settings.identity_embedding_store_path,
            max_jobs=self.settings.identity_max_jobs,
        )
        self.identity_directory = IdentityDirectoryStore(
            self.settings.identity_directory_path,
            protected_path=self.settings.identity_directory_protected_path,
            config_path=self.settings.identity_config_path,
            gallery_policy_path=self.settings.identity_gallery_policy_path,
        )
        self.identity_candidate_processor = IdentityCandidateProcessor(
            job_store=self.identity_job_store,
            directory=self.identity_directory,
        )
        self.identity_perception = (
            IdentityCoordinator(
                store=self.identity_job_store,
                worker_client=IdentityWorkerClient(
                    self.settings.identity_base_url,
                    api_key=self.settings.identity_api_key.get_secret_value(),
                    model=self.settings.identity_model,
                    timeout_seconds=self.settings.identity_worker_timeout_seconds,
                    max_media_bytes=self.settings.identity_max_media_bytes,
                ),
                model_revision=model_revision_from_config(
                    self.settings.identity_config_path
                ),
                config_version=self.identity_directory.config_version,
                candidate_processor=self.identity_candidate_processor,
                retry_seconds=self.settings.identity_worker_retry_seconds,
            )
            if self.settings.identity_perception_enabled
            else None
        )
        self.voice_job_store = VoiceJobStore(
            self.settings.voice_job_store_path,
            embedding_path=self.settings.voice_embedding_store_path,
            max_jobs=self.settings.voice_max_jobs,
        )
        self.voice_directory = VoiceCandidateDirectory(
            self.settings.voice_directory_path,
            protected_path=self.settings.voice_directory_protected_path,
            config_path=self.settings.voice_config_path,
        )

        def attach_late_voice_projection(
            window_id: str, result: dict
        ) -> None:
            if not window_id:
                return
            self.memory_review_store.update_capsule_voice_projection(
                window_id=window_id,
                audio_speakers=list(result.get("audio_speakers") or []),
                voice_perception={
                    "status": result.get("status"),
                    "job_id": result.get("job_id"),
                    "asr_alignment": result.get("asr_alignment") or {},
                },
            )

        self.voice_postprocessor = VoiceCandidatePostprocessor(
            job_store=self.voice_job_store,
            directory=self.voice_directory,
            projection_callback=attach_late_voice_projection,
        )
        self.voice_perception = (
            VoiceCoordinator(
                store=self.voice_job_store,
                worker_client=VoiceWorkerClient(
                    self.settings.voice_base_url,
                    api_key=self.settings.voice_api_key.get_secret_value(),
                    model=self.settings.voice_model,
                    timeout_seconds=self.settings.voice_worker_timeout_seconds,
                    max_media_bytes=self.settings.voice_max_media_bytes,
                ),
                model_revision=voice_model_revision_from_config(
                    self.settings.voice_config_path
                ),
                config_version=self.voice_directory.config_version,
                postprocessor=self.voice_postprocessor,
                retry_seconds=self.settings.voice_worker_retry_seconds,
            )
            if self.settings.voice_perception_enabled
            else None
        )
        self.production_voice_recognizer = (
            ProductionVoiceRecognizer(
                coordinator=self.voice_perception,
                job_store=self.voice_job_store,
                directory=self.voice_directory,
                postprocessor=self.voice_postprocessor,
                wait_ms=self.settings.voice_projection_wait_ms,
            )
            if self.voice_perception is not None
            else None
        )
        self.event_context_stabilizer = OpenAICompatibleEventContextStabilizer(
            self.settings,
            self.memory_review_store,
        )
        self.object_card_interpreter = OpenAICompatibleObjectCardInterpreter(
            self.settings,
            self.memory_review_store,
        )
        self.speech_presence = (
            CompositeSpeechPresenceDetector(
                fsmn_model_path=self.settings.speech_presence_fsmn_model_path,
                audioset_model_path=self.settings.speech_presence_audioset_model_path,
                fsmn_revision=self.settings.speech_presence_fsmn_revision,
                audioset_revision=self.settings.speech_presence_audioset_revision,
                silero_version=self.settings.speech_presence_silero_version,
                ten_vad_enabled=self.settings.speech_presence_ten_vad_enabled,
                ten_vad_version=self.settings.speech_presence_ten_vad_version,
                ten_vad_threshold=self.settings.speech_presence_ten_vad_threshold,
                ten_vad_min_frames=self.settings.speech_presence_ten_vad_min_frames,
                device=self.settings.speech_presence_device,
                decision_config=PresenceDecisionConfig(
                    silence_dbfs=self.settings.speech_presence_silence_dbfs,
                    speech_probability_threshold=(
                        self.settings.speech_presence_probability_threshold
                    ),
                    short_speech_recovery_ms=(
                        self.settings.speech_presence_short_recovery_ms
                    ),
                    segment_padding_ms=self.settings.speech_presence_segment_padding_ms,
                ),
            )
            if self.settings.speech_presence_enabled
            else None
        )
        self.media_converter = MediaConverter(
            self.settings.raw_media_dir,
            audio_filter=self.settings.audio_denoise_filter,
        )
        self.everos_bridge = EverOSMeetingBridge(
            raw_media_root=self.settings.raw_media_dir,
            converter=self.media_converter,
            everos=self.everos,
            audio_transcriber=self.memory_asr,
            transcription_chunk_bytes=64 * 1024 * 1024,
        )
        voice_identity_recognizer = LocalIdentityRecognizer(
            enable_face=False,
            enable_voice=(
                self.settings.identity_voice_enabled
                and self.production_voice_recognizer is None
            ),
        )
        self.production_identity_recognizer = (
            ProductionIdentityRecognizer(
                job_store=self.identity_job_store,
                directory=self.identity_directory,
                voice_recognizer=(
                    self.production_voice_recognizer or voice_identity_recognizer
                ),
                wait_ms=self.settings.identity_projection_wait_ms,
            )
            if (
                self.settings.identity_perception_enabled
                or self.production_voice_recognizer is not None
            )
            else None
        )
        self.memory_capsule_bridge = EverOSCapsuleBridge(
            raw_media_root=self.settings.raw_media_dir,
            converter=self.media_converter,
            everos=self.everos,
            review_store=self.memory_review_store,
            user_id=self.settings.everos_user_id,
            sender_name="眼镜用户",
            audio_transcriber=self.memory_asr,
            speech_presence_detector=self.speech_presence,
            identity_recognizer=self.production_identity_recognizer
            or voice_identity_recognizer,
            scene_interpreter=OpenAICompatibleMemorySceneInterpreter(self.settings),
            object_perception=self.object_perception,
            object_card_interpreter=self.object_card_interpreter,
            commitment_extractor=self.commitment_extractor,
            event_context_stabilizer=self.event_context_stabilizer,
            transcription_chunk_bytes=64 * 1024 * 1024,
            asr_full_window_enabled=self.settings.window_asr_full_window_enabled,
            asr_tail_guard_ms=self.settings.window_asr_tail_guard_ms,
            asr_fallback_speech_probability=(
                self.settings.window_asr_fallback_speech_probability
            ),
            flush_interval_ms=self.settings.memory_capsule_flush_ms,
            retry_interval_ms=self.settings.memory_capsule_retry_ms,
        )
        self.capture = CaptureManager(
            raw_media_root=self.settings.raw_media_dir,
            bridge=self.memory_capsule_bridge,
            user_id=self.settings.everos_user_id,
            sender_name="眼镜用户",
            max_window_ms=self.settings.memory_capsule_window_ms,
            image_late_grace_ms=self.settings.memory_image_late_grace_ms,
        )


def _settings_for_user(base: Settings, user_id: str) -> Settings:
    runtime_parent = Path(base.memory_review_db_path).expanduser().resolve().parent
    root = runtime_parent / "users" / user_id
    overrides: dict[str, Any] = {
        "everos_user_id": user_id,
        "photo_upload_dir": str(root / "received-photos"),
        "raw_media_dir": str(root / "raw-media"),
        "memory_review_db_path": str(root / "memory-review.json"),
        "memory_search_visual_projection_path": str(root / "memory-search" / "visual-projection.jsonl"),
        "object_perception_store_path": str(root / "object-perception" / "jobs.json"),
        "voice_job_store_path": str(root / "voice" / "jobs.json"),
        "voice_embedding_store_path": str(root / "voice" / "embeddings.jsonl"),
        "voice_directory_path": str(root / "voice" / "directory.json"),
        "voice_directory_protected_path": str(root / "voice" / "protected.json"),
        "identity_job_store_path": str(root / "identity" / "jobs.json"),
        "identity_embedding_store_path": str(root / "identity" / "embeddings.jsonl"),
        "identity_directory_path": str(root / "identity" / "directory.json"),
        "identity_directory_protected_path": str(root / "identity" / "protected.json"),
    }
    return base.model_copy(update=overrides)


class AppStateRegistry:
    def __init__(self) -> None:
        from glass_gateway.auth import auth_registry

        base = get_settings()
        self._states = {
            principal.user_id: AppState(_settings_for_user(base, principal.user_id))
            for principal in auth_registry.principals()
        }
        self._default_user_id = auth_registry.principals()[0].user_id

    def current(self) -> AppState:
        from glass_gateway.auth import auth_registry

        user_id = auth_registry.current_user_id() or self._default_user_id
        return self._states[user_id]

    def all(self) -> list[AppState]:
        return list(self._states.values())


class AppStateProxy:
    def __init__(self, registry: AppStateRegistry) -> None:
        object.__setattr__(self, "_registry", registry)

    def __getattr__(self, name: str):
        return getattr(self._registry.current(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._registry.current(), name, value)


app_state_registry = AppStateRegistry()
app_state = AppStateProxy(app_state_registry)
