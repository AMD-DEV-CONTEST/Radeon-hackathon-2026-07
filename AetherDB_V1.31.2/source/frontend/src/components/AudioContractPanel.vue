<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  AudioLines,
  Check,
  CheckCircle2,
  BookOpenText,
  Download,
  ExternalLink,
  Link2,
  Mic2,
  Plus,
  RefreshCw,
  RotateCcw,
  Square,
  Trash2,
  X,
} from "@lucide/vue";
import {
  cancelAudioTask,
  createAudioTask,
  createPronunciationEntry,
  createVoiceProfile,
  deletePronunciationEntry,
  getAudioContractStatus,
  getAudioAsset,
  getAudioTask,
  getAudioWaveform,
  listAudioTaskEvents,
  listAudioTasks,
  listPronunciationEntries,
  listVoiceProfiles,
  publishAudioTask,
  retryAudioTask,
  reviewAudioResult,
  updatePronunciationEntry,
  updateVoiceProfile,
} from "../api/audioContract.js";
import {
  listMediaAssets,
  loadMediaContent,
} from "../api/mediaAssets.js";
import { listModelProfiles } from "../api/models.js";
import { listModelPackages } from "../api/modelPackages.js";
import { useAppStore } from "../stores/app.js";

const emit = defineEmits(["open-assets"]);
const store = useAppStore();
const { locale, t } = useI18n();

const contract = ref(null);
const voices = ref([]);
const tasks = ref([]);
const selectedTask = ref(null);
const audioAssets = ref([]);
const modelProfiles = ref([]);
const modelPackages = ref([]);
const pronunciationEntries = ref([]);
const taskEvents = ref([]);
const waveform = ref(null);
const audioPreviewUrl = ref("");
const audioPreviewBlob = ref(null);
const outputAsset = ref(null);
const loading = ref(false);
const action = ref("");
const errorMessage = ref("");
const successMessage = ref("");
const showVoiceForm = ref(false);
const showDictionary = ref(false);
let pollTimer = null;

const KOKORO_BASELINE_PACKAGE_ID = "aetherdb.kokoro-82m";
const KOKORO_BASELINE_VOICES = new Set(["af_heart", "bf_emma", "zf_xiaobei"]);

const voiceForm = ref({
  name: "",
  locale: "zh-CN",
  voice_kind: "local_reference",
  model_profile_id: "",
  provider_voice_name: "",
  reference_asset_id: "",
  package_id: "",
  package_voice_name: "",
  consent_confirmed: false,
});

const pronunciationForm = ref({
  locale: "zh-CN",
  term: "",
  pronunciation: "",
  entry_kind: "replacement",
});

const taskForm = ref({
  operation: "audio.tts.chapter",
  voice_profile_id: "",
  source_text: "",
  source_asset_id: "",
  source_asset_ids: [],
  model_profile_id: "",
  requested_backend: "auto",
  speed: 1,
  pause_ms: 120,
  peak: 0.92,
});

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const chapterId = computed(() => store.activeChapter?.chapter_id || "");
const hasScope = computed(() => Boolean(databaseId.value && bookId.value));
const isTts = computed(() => taskForm.value.operation.startsWith("audio.tts"));
const isChapterTts = computed(() => taskForm.value.operation === "audio.tts.chapter");
const isSegmentTts = computed(() => taskForm.value.operation === "audio.tts.segment");
const isMerge = computed(() => taskForm.value.operation === "audio.merge");
const needsSingleAsset = computed(() => (
  ["audio.asr.transcribe", "audio.preview", "audio.enhance"].includes(taskForm.value.operation)
));
const selectedVoice = computed(() => (
  voices.value.find((item) => item.voice_profile_id === taskForm.value.voice_profile_id) || null
));
const activeTasks = computed(() => (
  Boolean(contract.value?.execution_implemented)
  && tasks.value.some((task) => task.status === "in_progress")
));

const AUDIO_TYPES = {
  "audio.tts.chapter": ["audio", "tts", "text_to_speech", "audio_generation", "multimodal_audio"],
  "audio.tts.segment": ["audio", "tts", "text_to_speech", "audio_generation", "multimodal_audio"],
  "audio.asr.transcribe": ["audio", "asr", "speech_to_text", "transcription", "multimodal_audio"],
  "audio.preview": ["audio", "audio_processing", "multimodal_audio"],
  "audio.enhance": ["audio", "audio_enhancement", "audio_processing", "multimodal_audio"],
  "audio.merge": ["audio", "audio_processing", "multimodal_audio"],
};
const ttsPackages = computed(() => (
  modelPackages.value.filter((item) => (
    item.enabled
    && item.capabilities?.some((capability) => capability.startsWith("audio.tts."))
  ))
));
const installedTtsPackages = computed(() => (
  ttsPackages.value.filter((item) => (
    item.model_profile_id
    && item.installation?.status === "installed"
  ))
));
const routableTtsProfileIds = computed(() => new Set(
  installedTtsPackages.value.map((item) => item.model_profile_id),
));
const routableTtsModels = computed(() => (
  modelProfiles.value.filter((item) => (
    item.enabled && routableTtsProfileIds.value.has(item.id)
  ))
));
const eligibleModels = computed(() => (
  isTts.value
    ? routableTtsModels.value
    : modelProfiles.value.filter((item) => (
      item.enabled && AUDIO_TYPES[taskForm.value.operation]?.includes(item.model_type)
    ))
));
const ttsModels = computed(() => routableTtsModels.value);
const selectedVoicePackage = computed(() => (
  ttsPackages.value.find((item) => item.package_id === voiceForm.value.package_id) || null
));
const packageVoices = computed(() => (
  (selectedVoicePackage.value?.files || [])
    .filter((item) => item.role === "voice")
    .map((item) => item.path.split("/").pop()?.replace(/\.[^.]+$/, ""))
    .filter(Boolean)
    .filter((voiceName) => (
      selectedVoicePackage.value?.package_id !== KOKORO_BASELINE_PACKAGE_ID
      || KOKORO_BASELINE_VOICES.has(voiceName)
    ))
));
const approvedAudioAssets = computed(() => (
  audioAssets.value.filter((item) => item.lifecycle_status === "approved")
));
const canCreateVoice = computed(() => {
  if (!hasScope.value || !voiceForm.value.name.trim()) return false;
  if (voiceForm.value.voice_kind === "provider_voice") {
    return Boolean(voiceForm.value.model_profile_id && voiceForm.value.provider_voice_name.trim());
  }
  if (voiceForm.value.voice_kind === "native_voice") {
    return Boolean(
      installedTtsPackages.value.some(
        (item) => item.package_id === voiceForm.value.package_id,
      )
      && voiceForm.value.package_voice_name,
    );
  }
  return Boolean(voiceForm.value.reference_asset_id && voiceForm.value.consent_confirmed);
});
const canCreateTask = computed(() => {
  if (!hasScope.value || action.value) return false;
  if (
    isTts.value
    && (
      selectedVoice.value?.voice_kind !== "native_voice"
      || !taskForm.value.model_profile_id
    )
  ) return false;
  if (isChapterTts.value) return Boolean(chapterId.value && taskForm.value.voice_profile_id);
  if (isSegmentTts.value) {
    return Boolean(
      taskForm.value.voice_profile_id
      && taskForm.value.source_text.trim()
      && taskForm.value.source_text.length <= 800,
    );
  }
  if (needsSingleAsset.value) return Boolean(taskForm.value.source_asset_id);
  if (isMerge.value) return taskForm.value.source_asset_ids.length >= 2;
  return false;
});

const OPERATION_LABELS = {
  "audio.tts.chapter": "章节朗读",
  "audio.tts.segment": "片段朗读",
  "audio.asr.transcribe": "语音转写",
  "audio.preview": "音频预览处理",
  "audio.enhance": "音频增强",
  "audio.merge": "音频合并",
};
const STATUS_LABELS = {
  planned: "已规划",
  in_progress: "执行中",
  pending_review: "待审批",
  completed: "已完成",
  cancelled: "已取消",
  failed: "执行失败",
  outdated: "已过期",
};
const APPROVAL_LABELS = {
  pending: "待审批",
  pending_review: "待审批",
  approved: "已批准",
  rejected: "已拒绝",
};

function safeMessage(error, fallback) {
  return error?.detail?.message || error?.message || t(fallback);
}

function tone(status) {
  if (status === "completed") return "positive";
  if (status === "in_progress") return "active";
  if (status === "planned" || status === "pending_review") return "warning";
  if (status === "failed" || status === "outdated") return "danger";
  return "muted";
}

function voiceKindLabel(voice) {
  if (voice.voice_kind === "native_voice") return "本地原生声音";
  if (voice.voice_kind === "local_reference") return "本地参考音频";
  return "模型供应商声音";
}

function formatTime(value) {
  if (!value) return t("尚未开始");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

async function refresh({ silent = false } = {}) {
  if (!hasScope.value) {
    voices.value = [];
    tasks.value = [];
    audioAssets.value = [];
    return;
  }
  if (!silent) loading.value = true;
  errorMessage.value = "";
  const results = await Promise.allSettled([
    getAudioContractStatus(),
    listVoiceProfiles({ database_id: databaseId.value, book_id: bookId.value }),
    listAudioTasks({
      database_id: databaseId.value,
      book_id: bookId.value,
      limit: 100,
    }),
    listMediaAssets({
      database_id: databaseId.value,
      book_id: bookId.value,
      modality: "audio",
      limit: 200,
    }),
    listModelProfiles(),
    listPronunciationEntries({
      database_id: databaseId.value,
      book_id: bookId.value,
    }),
    store.isLocalOwner ? listModelPackages() : Promise.resolve({ packages: [] }),
  ]);
  if (results[0].status === "fulfilled") contract.value = results[0].value;
  if (results[1].status === "fulfilled") voices.value = results[1].value?.voice_profiles || [];
  if (results[2].status === "fulfilled") tasks.value = results[2].value?.tasks || [];
  else errorMessage.value = safeMessage(results[2].reason, "音频任务加载失败");
  if (results[3].status === "fulfilled") audioAssets.value = results[3].value?.assets || [];
  if (results[4].status === "fulfilled") modelProfiles.value = results[4].value?.model_profiles || [];
  if (results[5].status === "fulfilled") {
    pronunciationEntries.value = results[5].value?.entries || [];
  }
  if (results[6].status === "fulfilled") {
    modelPackages.value = results[6].value?.packages || [];
  }
  if (selectedTask.value?.task_id) {
    const current = tasks.value.find((task) => task.task_id === selectedTask.value.task_id);
    if (current) await openTask(current, { silent: true });
  }
  if (!taskForm.value.voice_profile_id && voices.value.length) {
    taskForm.value.voice_profile_id = voices.value.find((item) => item.enabled)?.voice_profile_id || "";
  }
  loading.value = false;
}

async function saveVoice() {
  if (!canCreateVoice.value) return;
  action.value = "voice";
  errorMessage.value = "";
  successMessage.value = "";
  try {
    const localReference = voiceForm.value.voice_kind === "local_reference";
    const nativeVoice = voiceForm.value.voice_kind === "native_voice";
    await createVoiceProfile({
      database_id: databaseId.value,
      book_id: bookId.value,
      name: voiceForm.value.name.trim(),
      locale: voiceForm.value.locale || "und",
      voice_kind: voiceForm.value.voice_kind,
      model_profile_id: nativeVoice ? null : voiceForm.value.model_profile_id || null,
      provider_voice_name: (
        voiceForm.value.voice_kind === "provider_voice"
          ? voiceForm.value.provider_voice_name.trim()
          : null
      ),
      reference_asset_id: localReference ? voiceForm.value.reference_asset_id : null,
      package_id: nativeVoice ? voiceForm.value.package_id : null,
      package_voice_name: nativeVoice ? voiceForm.value.package_voice_name : null,
      consent_confirmed: localReference && voiceForm.value.consent_confirmed,
      enabled: true,
      metadata: {},
    });
    voiceForm.value = {
      name: "",
      locale: "zh-CN",
      voice_kind: "local_reference",
      model_profile_id: "",
      provider_voice_name: "",
      reference_asset_id: "",
      package_id: "",
      package_voice_name: "",
      consent_confirmed: false,
    };
    showVoiceForm.value = false;
    successMessage.value = t("声音配置已创建");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "声音配置创建失败");
  } finally {
    action.value = "";
  }
}

async function savePronunciation() {
  if (
    !pronunciationForm.value.term.trim()
    || !pronunciationForm.value.pronunciation.trim()
    || action.value
  ) return;
  action.value = "pronunciation";
  errorMessage.value = "";
  try {
    await createPronunciationEntry({
      database_id: databaseId.value,
      book_id: bookId.value,
      locale: pronunciationForm.value.locale || "und",
      term: pronunciationForm.value.term.trim(),
      pronunciation: pronunciationForm.value.pronunciation.trim(),
      entry_kind: pronunciationForm.value.entry_kind,
      enabled: true,
    });
    pronunciationForm.value.term = "";
    pronunciationForm.value.pronunciation = "";
    successMessage.value = t("发音条目已保存，将冻结到之后创建的任务中");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "发音条目创建失败");
  } finally {
    action.value = "";
  }
}

async function togglePronunciation(entry) {
  action.value = `pronunciation:${entry.entry_id}`;
  try {
    await updatePronunciationEntry(entry.entry_id, databaseId.value, {
      enabled: !entry.enabled,
    });
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "发音条目更新失败");
  } finally {
    action.value = "";
  }
}

async function removePronunciation(entry) {
  action.value = `pronunciation:${entry.entry_id}`;
  try {
    await deletePronunciationEntry(entry.entry_id, databaseId.value);
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "发音条目删除失败");
  } finally {
    action.value = "";
  }
}

async function toggleVoice(voice) {
  action.value = `voice:${voice.voice_profile_id}`;
  try {
    await updateVoiceProfile(voice.voice_profile_id, databaseId.value, {
      enabled: !voice.enabled,
    });
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "声音配置更新失败");
  } finally {
    action.value = "";
  }
}

async function createTask() {
  if (!canCreateTask.value) return;
  action.value = "create";
  errorMessage.value = "";
  successMessage.value = "";
  try {
    const sourceAssetIds = isMerge.value
      ? [...taskForm.value.source_asset_ids]
      : needsSingleAsset.value
        ? [taskForm.value.source_asset_id]
        : [];
    const response = await createAudioTask({
      database_id: databaseId.value,
      book_id: bookId.value,
      operation: taskForm.value.operation,
      chapter_id: isChapterTts.value ? chapterId.value : null,
      source_text: isSegmentTts.value ? taskForm.value.source_text.trim() : null,
      source_revision: null,
      source_asset_ids: sourceAssetIds,
      voice_profile_id: isTts.value ? taskForm.value.voice_profile_id : null,
      model_profile_id: taskForm.value.model_profile_id || null,
      package_id: null,
      requested_backend: taskForm.value.requested_backend,
      execution_config: isTts.value ? {
        speed: Number(taskForm.value.speed),
        segment_pause_ms: Number(taskForm.value.pause_ms),
        peak_target: Number(taskForm.value.peak),
      } : {},
    });
    selectedTask.value = response.task;
    successMessage.value = t(
      contract.value?.execution_implemented
        ? "音频任务已创建"
        : "音频计划已创建，等待兼容执行器接管",
    );
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "音频任务创建失败");
  } finally {
    action.value = "";
  }
}

function releaseAudioPreview() {
  if (audioPreviewUrl.value) URL.revokeObjectURL(audioPreviewUrl.value);
  audioPreviewUrl.value = "";
  audioPreviewBlob.value = null;
  outputAsset.value = null;
}

async function loadAudioPreview(assetId) {
  waveform.value = null;
  releaseAudioPreview();
  if (!assetId) return;
  const results = await Promise.allSettled([
    getAudioWaveform(assetId, databaseId.value, 128),
    getAudioAsset(assetId, databaseId.value),
    loadMediaContent(assetId, databaseId.value),
  ]);
  if (results[0].status === "fulfilled") {
    waveform.value = results[0].value.waveform;
  }
  if (results[1].status === "fulfilled") {
    outputAsset.value = results[1].value.asset || null;
  }
  if (results[2].status === "fulfilled") {
    audioPreviewBlob.value = results[2].value;
    audioPreviewUrl.value = URL.createObjectURL(results[2].value);
  }
}

async function openTask(task, { silent = false } = {}) {
  if (!silent) action.value = `detail:${task.task_id}`;
  try {
    selectedTask.value = (
      await getAudioTask(task.task_id, databaseId.value, { includeResultText: true })
    ).task;
    taskEvents.value = (
      await listAudioTaskEvents(task.task_id, databaseId.value, 200)
    ).events || [];
    const sourceId = selectedTask.value.output_asset_id
      || selectedTask.value.input_asset_ids?.[0]
      || null;
    await loadAudioPreview(sourceId);
  } catch (error) {
    if (!silent) errorMessage.value = safeMessage(error, "音频任务详情加载失败");
  } finally {
    if (!silent) action.value = "";
  }
}

function downloadAudio() {
  if (!audioPreviewUrl.value || !selectedTask.value) return;
  const anchor = document.createElement("a");
  anchor.href = audioPreviewUrl.value;
  anchor.download = `${selectedTask.value.task_id}.wav`;
  anchor.click();
}

async function approveAndBindOutput() {
  const assetId = selectedTask.value?.output_asset_id;
  const targetChapterId = selectedTask.value?.chapter_id;
  if (!assetId || !targetChapterId) return;
  action.value = `publish:${selectedTask.value.task_id}`;
  errorMessage.value = "";
  try {
    await publishAudioTask(selectedTask.value.task_id, databaseId.value, {
      binding_type: "chapter_narration",
    });
    successMessage.value = t("音频已批准并绑定到对应章节");
    await openTask(selectedTask.value, { silent: true });
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "音频批准或章节绑定失败");
  } finally {
    action.value = "";
  }
}

function routeProfileForVoice(voice) {
  if (!voice || voice.voice_kind !== "native_voice") return voice?.model_profile_id || "";
  return (
    installedTtsPackages.value.find(
      (item) => item.package_id === voice.package_id,
    )?.model_profile_id || ""
  );
}

async function retryTask(task) {
  action.value = `retry:${task.task_id}`;
  try {
    selectedTask.value = (
      await retryAudioTask(task.task_id, databaseId.value)
    ).task;
    successMessage.value = t("失败片段已重新加入队列，已完成片段不会重复生成");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "音频任务重试失败");
  } finally {
    action.value = "";
  }
}

async function cancelTask(task) {
  action.value = `cancel:${task.task_id}`;
  try {
    selectedTask.value = (await cancelAudioTask(task.task_id, databaseId.value)).task;
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "音频任务取消失败");
  } finally {
    action.value = "";
  }
}

async function reviewResult(result, approved) {
  action.value = `review:${result.result_id}`;
  try {
    selectedTask.value = (
      await reviewAudioResult(result.result_id, databaseId.value, approved)
    ).task;
    successMessage.value = t(approved ? "转写结果已批准" : "转写结果已拒绝");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "音频结果审批失败");
  } finally {
    action.value = "";
  }
}

watch([databaseId, bookId], () => refresh(), { immediate: true });
watch(() => taskForm.value.operation, () => {
  taskForm.value.model_profile_id = "";
  taskForm.value.source_asset_id = "";
  taskForm.value.source_asset_ids = [];
  waveform.value = null;
  releaseAudioPreview();
  if (isTts.value && selectedVoice.value) {
    taskForm.value.model_profile_id = routeProfileForVoice(selectedVoice.value);
  }
});
watch(() => taskForm.value.voice_profile_id, () => {
  if (isTts.value) {
    taskForm.value.model_profile_id = routeProfileForVoice(selectedVoice.value);
  }
});
watch(() => taskForm.value.model_profile_id, (profileId) => {
  if (!isTts.value || !profileId) return;
  const modelPackage = installedTtsPackages.value.find(
    (item) => item.model_profile_id === profileId,
  );
  if (!modelPackage || selectedVoice.value?.package_id === modelPackage.package_id) return;
  taskForm.value.voice_profile_id = (
    voices.value.find((voice) => (
      voice.enabled
      && voice.voice_kind === "native_voice"
      && voice.package_id === modelPackage.package_id
    ))?.voice_profile_id || ""
  );
});
watch(() => voiceForm.value.voice_kind, () => {
  voiceForm.value.model_profile_id = "";
  voiceForm.value.provider_voice_name = "";
  voiceForm.value.reference_asset_id = "";
  voiceForm.value.package_id = "";
  voiceForm.value.package_voice_name = "";
  voiceForm.value.consent_confirmed = false;
});
watch(() => voiceForm.value.package_id, () => {
  voiceForm.value.package_voice_name = packageVoices.value[0] || "";
});
onMounted(() => {
  pollTimer = window.setInterval(() => {
    if (activeTasks.value && document.visibilityState === "visible") refresh({ silent: true });
  }, 3000);
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
  releaseAudioPreview();
});
</script>

<template>
  <section class="audio-panel">
    <header class="panel-heading">
      <div>
        <span class="heading-icon"><AudioLines :size="20" /></span>
        <div><h2>{{ t("音频创作") }}</h2><p>{{ t("声音、任务、波形与结果审批") }}</p></div>
      </div>
      <div class="heading-actions">
        <span :class="contract?.execution_implemented ? 'ready' : 'contract'">
          {{ t(contract?.execution_implemented ? "执行器已连接" : "仅契约模式") }}
        </span>
        <button class="icon-button" type="button" :title="t('刷新')" :disabled="loading" @click="refresh()">
          <RefreshCw :size="16" :class="{ spinning: loading }" />
        </button>
      </div>
    </header>

    <div v-if="!hasScope" class="empty-state">{{ t("请先选择世界库和作品") }}</div>
    <template v-else>
      <p v-if="contract && !contract.execution_implemented" class="contract-warning">
        <AlertTriangle :size="14" />
        {{ t("当前仅保存模型中立的音频计划与审批记录，不声明已执行音频推理。") }}
      </p>

      <section class="voice-band">
        <header>
          <div><Mic2 :size="17" /><strong>{{ t("声音配置") }}</strong><span>{{ voices.length }}</span></div>
          <button type="button" @click="showVoiceForm = !showVoiceForm">
            <X v-if="showVoiceForm" :size="14" /><Plus v-else :size="14" />
            {{ t(showVoiceForm ? "收起" : "新增声音") }}
          </button>
        </header>
        <form v-if="showVoiceForm" class="voice-form" @submit.prevent="saveVoice">
          <label><span>{{ t("名称") }}</span><input v-model="voiceForm.name" maxlength="100" required /></label>
          <label><span>{{ t("语言") }}</span><input v-model="voiceForm.locale" maxlength="40" /></label>
          <label>
            <span>{{ t("声音来源") }}</span>
            <select v-model="voiceForm.voice_kind">
              <option value="native_voice">{{ t("本地原生声音") }}</option>
              <option value="local_reference">{{ t("本地参考音频") }}</option>
            </select>
          </label>
          <template v-if="voiceForm.voice_kind === 'local_reference'">
            <label>
              <span>{{ t("参考音频") }}</span>
              <select v-model="voiceForm.reference_asset_id">
                <option value="">{{ t("选择已批准音频") }}</option>
                <option v-for="asset in approvedAudioAssets" :key="asset.asset_id" :value="asset.asset_id">
                  {{ asset.original_filename }}
                </option>
              </select>
            </label>
            <label class="consent-field">
              <input v-model="voiceForm.consent_confirmed" type="checkbox" />
              <span>{{ t("确认拥有该参考声音的合法使用授权") }}</span>
            </label>
          </template>
          <template v-else-if="voiceForm.voice_kind === 'native_voice'">
            <label>
              <span>{{ t("TTS 模型包") }}</span>
              <select v-model="voiceForm.package_id" required>
                <option value="">{{ t("选择受信任的本地模型包") }}</option>
                <option v-for="item in installedTtsPackages" :key="item.package_id" :value="item.package_id">
                  {{ item.display_name }}
                </option>
              </select>
            </label>
            <label>
              <span>{{ t("包内声音") }}</span>
              <select v-model="voiceForm.package_voice_name" required>
                <option value="">{{ t("选择声音") }}</option>
                <option v-for="voiceName in packageVoices" :key="voiceName" :value="voiceName">
                  {{ voiceName }}
                </option>
              </select>
            </label>
            <p class="source-state wide-field">
              {{ t("模型包按任务选择且不会静默替换；Kokoro 82M 仅作为轻量联调基线。") }}
            </p>
            <p v-if="!installedTtsPackages.length" class="feedback danger wide-field">
              <AlertTriangle :size="14" />{{ t("尚无已安装的 TTS 模型包，请先在 AI 设置中安装并验证。") }}
            </p>
          </template>
          <template v-else>
            <label>
              <span>{{ t("TTS 模型") }}</span>
              <select v-model="voiceForm.model_profile_id" required>
                <option value="">{{ t("选择已确认 TTS 能力的模型") }}</option>
                <option v-for="profile in ttsModels" :key="profile.id" :value="profile.id">
                  {{ profile.display_name }}
                </option>
              </select>
            </label>
            <label><span>{{ t("供应商声音名称") }}</span><input v-model="voiceForm.provider_voice_name" maxlength="256" required /></label>
          </template>
          <button class="primary-button" type="submit" :disabled="!canCreateVoice">
            <Check :size="14" />{{ t(action === "voice" ? "正在保存" : "保存声音配置") }}
          </button>
        </form>
        <div v-if="voices.length" class="voice-list">
          <label
            v-for="voice in voices"
            :key="voice.voice_profile_id"
            class="voice-item"
            :class="{ disabled: !voice.enabled }"
          >
            <Mic2 :size="14" />
            <span>
              <strong>{{ voice.name }}</strong>
              <small>{{ voice.locale }} · {{ t(voiceKindLabel(voice)) }}</small>
              <em v-if="voice.package_id">{{ voice.package_id }} / {{ voice.package_voice_name }}</em>
            </span>
            <input
              type="checkbox"
              :checked="voice.enabled"
              :disabled="action === `voice:${voice.voice_profile_id}`"
              :aria-label="t(voice.enabled ? '已启用' : '已停用')"
              @change="toggleVoice(voice)"
            />
          </label>
        </div>
      </section>

      <section class="dictionary-band">
        <header>
          <div>
            <BookOpenText :size="17" />
            <strong>{{ t("作品发音词典") }}</strong>
            <span>{{ pronunciationEntries.length }}</span>
          </div>
          <button type="button" @click="showDictionary = !showDictionary">
            {{ t(showDictionary ? "收起" : "管理词典") }}
          </button>
        </header>
        <template v-if="showDictionary">
          <form class="dictionary-form" @submit.prevent="savePronunciation">
            <label><span>{{ t("语言") }}</span><input v-model="pronunciationForm.locale" maxlength="40" /></label>
            <label><span>{{ t("原词") }}</span><input v-model="pronunciationForm.term" maxlength="160" required /></label>
            <label><span>{{ t("读法或替换文本") }}</span><input v-model="pronunciationForm.pronunciation" maxlength="512" required /></label>
            <label>
              <span>{{ t("规则类型") }}</span>
              <select v-model="pronunciationForm.entry_kind">
                <option value="replacement">{{ t("文本替换") }}</option>
                <option value="kokoro_phoneme">{{ t("Kokoro 音素") }}</option>
              </select>
            </label>
            <button class="primary-button" type="submit" :disabled="action === 'pronunciation'">
              <Plus :size="14" />{{ t("添加条目") }}
            </button>
          </form>
          <div class="dictionary-list">
            <div v-for="entry in pronunciationEntries" :key="entry.entry_id">
              <span>
                <strong>{{ entry.term }}</strong>
                <small>{{ entry.locale }} · {{ entry.entry_kind }} · {{ entry.pronunciation }}</small>
              </span>
              <input
                type="checkbox"
                :checked="entry.enabled"
                :aria-label="t(entry.enabled ? '已启用' : '已停用')"
                @change="togglePronunciation(entry)"
              />
              <button
                class="icon-button"
                type="button"
                :title="t('删除发音条目')"
                @click="removePronunciation(entry)"
              ><Trash2 :size="14" /></button>
            </div>
            <p v-if="!pronunciationEntries.length" class="empty-state compact">
              {{ t("尚无发音条目。任务创建时会保存不可变词典快照。") }}
            </p>
          </div>
        </template>
      </section>

      <div class="audio-layout">
        <form class="task-form" @submit.prevent="createTask">
          <label>
            <span>{{ t("任务类型") }}</span>
            <select v-model="taskForm.operation">
              <option value="audio.tts.chapter">{{ t("章节朗读") }}</option>
              <option value="audio.tts.segment">{{ t("片段朗读") }}</option>
              <option value="audio.asr.transcribe">{{ t("语音转写") }}</option>
              <option value="audio.preview">{{ t("音频预览处理") }}</option>
              <option value="audio.enhance">{{ t("音频增强") }}</option>
              <option value="audio.merge">{{ t("音频合并") }}</option>
            </select>
          </label>
          <label v-if="isTts">
            <span>{{ t("声音配置") }}</span>
            <select v-model="taskForm.voice_profile_id">
              <option value="">{{ t("选择声音配置") }}</option>
              <option
                v-for="voice in voices.filter((item) => item.enabled && item.voice_kind === 'native_voice')"
                :key="voice.voice_profile_id"
                :value="voice.voice_profile_id"
              >
                {{ voice.name }} · {{ voice.locale }}
              </option>
            </select>
          </label>
          <p v-if="isChapterTts" class="source-state">
            {{ chapterId ? t("当前章节：{title}", { title: store.chapterTitle }) : t("请先选择章节") }}
          </p>
          <label v-if="isSegmentTts" class="wide-field">
            <span>{{ t("朗读文本") }} <b>{{ taskForm.source_text.length }} / 800</b></span>
            <textarea v-model="taskForm.source_text" rows="5" maxlength="800" />
          </label>
          <label v-if="needsSingleAsset">
            <span>{{ t("源音频") }}</span>
            <select v-model="taskForm.source_asset_id">
              <option value="">{{ t("选择音频资产") }}</option>
              <option v-for="asset in audioAssets" :key="asset.asset_id" :value="asset.asset_id">
                {{ asset.original_filename }}
              </option>
            </select>
          </label>
          <label v-if="isMerge" class="wide-field">
            <span>{{ t("合并音频，至少选择两项") }}</span>
            <select v-model="taskForm.source_asset_ids" multiple size="5">
              <option v-for="asset in audioAssets" :key="asset.asset_id" :value="asset.asset_id">
                {{ asset.original_filename }}
              </option>
            </select>
          </label>
          <label>
            <span>{{ t(isTts ? "TTS 模型路由目标" : "执行模型") }}</span>
            <select v-model="taskForm.model_profile_id">
              <option value="">{{ t(isTts ? "选择已安装的 AetherDB TTS Worker 模型" : "仅创建计划") }}</option>
              <option v-for="profile in eligibleModels" :key="profile.id" :value="profile.id">
                {{ profile.display_name }} · {{ profile.provider_model_name }}
              </option>
            </select>
          </label>
          <p v-if="isTts" class="source-state wide-field">
            {{ t("TTS 由 AetherDB 唯一模型路由和独立 Audio Worker 执行，不通过 Ollama。") }}
          </p>
          <label>
            <span>{{ t("硬件后端") }}</span>
            <select v-model="taskForm.requested_backend">
              <option value="auto">{{ t("自动选择") }}</option>
              <option value="cpu">CPU</option>
              <option value="rocm_pytorch">ROCm / PyTorch</option>
              <option value="cuda">CUDA</option>
            </select>
          </label>
          <template v-if="isTts">
            <label class="range-field">
              <span>{{ t("语速") }} <b>{{ Number(taskForm.speed).toFixed(2) }}×</b></span>
              <input v-model.number="taskForm.speed" type="range" min="0.5" max="2" step="0.05" />
            </label>
            <label>
              <span>{{ t("片段间停顿") }}</span>
              <input v-model.number="taskForm.pause_ms" type="number" min="0" max="2000" step="20" />
            </label>
            <label class="range-field wide-field">
              <span>{{ t("峰值归一化") }} <b>{{ Number(taskForm.peak).toFixed(2) }}</b></span>
              <input v-model.number="taskForm.peak" type="range" min="0.1" max="0.99" step="0.01" />
            </label>
          </template>
          <p v-if="errorMessage" class="feedback danger wide-field"><AlertTriangle :size="14" />{{ errorMessage }}</p>
          <p v-if="successMessage" class="feedback positive wide-field"><CheckCircle2 :size="14" />{{ successMessage }}</p>
          <button class="primary-button wide-field" type="submit" :disabled="!canCreateTask">
            <AudioLines :size="15" />{{ t(action === "create" ? "正在创建任务" : "创建音频任务") }}
          </button>
        </form>

        <div class="task-list">
          <button
            v-for="task in tasks"
            :key="task.task_id"
            type="button"
            :class="{ selected: selectedTask?.task_id === task.task_id }"
            @click="openTask(task)"
          >
            <AudioLines :size="16" />
            <span><strong>{{ t(OPERATION_LABELS[task.operation] || task.operation) }}</strong><small>{{ formatTime(task.created_at) }}</small></span>
            <em :class="tone(task.status)">{{ t(STATUS_LABELS[task.status] || task.status) }}</em>
          </button>
          <div v-if="!tasks.length && !loading" class="empty-state compact">{{ t("尚无音频任务") }}</div>
        </div>

        <aside v-if="selectedTask" class="task-detail">
          <header>
            <div><small>{{ t("任务详情") }}</small><strong>{{ t(OPERATION_LABELS[selectedTask.operation] || selectedTask.operation) }}</strong></div>
            <em :class="tone(selectedTask.status)">{{ t(STATUS_LABELS[selectedTask.status] || selectedTask.status) }}</em>
          </header>
          <dl>
            <div><dt>{{ t("片段数") }}</dt><dd>{{ selectedTask.segments?.length || 0 }}</dd></div>
            <div><dt>{{ t("执行目标") }}</dt><dd>{{ selectedTask.target_kind || t("尚未确定") }}</dd></div>
            <div><dt>{{ t("请求后端") }}</dt><dd>{{ selectedTask.requested_backend }}</dd></div>
            <div><dt>{{ t("输出资产") }}</dt><dd>{{ selectedTask.output_asset_id || t("尚无输出") }}</dd></div>
            <div><dt>{{ t("路由模型") }}</dt><dd>{{ selectedTask.model_profile_id || t("尚未确定") }}</dd></div>
            <div><dt>{{ t("模型包") }}</dt><dd>{{ selectedTask.package_id || t("外部模型 / 未确定") }}</dd></div>
            <div><dt>{{ t("词典快照") }}</dt><dd>{{ selectedTask.dictionary_entry_count || 0 }} {{ t("条") }}</dd></div>
          </dl>
          <div class="task-progress">
            <div><i :style="{ width: `${Math.round((selectedTask.progress || 0) * 100)}%` }"></i></div>
            <span>{{ Math.round((selectedTask.progress || 0) * 100) }}%</span>
          </div>
          <div v-if="selectedTask.segments?.length" class="segment-list">
            <span
              v-for="segment in selectedTask.segments"
              :key="segment.segment_id"
              :class="tone(segment.status)"
              :title="segment.error_code || segment.status"
            >{{ segment.segment_index + 1 }}</span>
          </div>
          <div v-if="waveform?.points?.length" class="waveform" :aria-label="t('音频波形')">
            <i
              v-for="(point, index) in waveform.points"
              :key="index"
              :style="{ height: `${Math.max(4, Math.round(point * 100))}%` }"
            ></i>
          </div>
          <audio
            v-if="audioPreviewUrl"
            class="audio-player"
            :src="audioPreviewUrl"
            controls
            preload="metadata"
          ></audio>
          <p v-if="selectedTask.error_code" class="task-error">
            <strong>{{ selectedTask.error_code }}</strong><span>{{ selectedTask.error_message }}</span>
          </p>
          <section v-if="selectedTask.results?.length" class="result-list">
            <strong>{{ t("转写结果") }}</strong>
            <article v-for="result in selectedTask.results" :key="result.result_id">
              <p v-if="result.content_text">{{ result.content_text }}</p>
              <span>{{ t(APPROVAL_LABELS[result.approval_status] || result.approval_status || "待审批") }}</span>
              <div v-if="result.approval_status === 'pending'">
                <button type="button" @click="reviewResult(result, true)"><Check :size="13" />{{ t("批准") }}</button>
                <button type="button" @click="reviewResult(result, false)"><X :size="13" />{{ t("拒绝") }}</button>
              </div>
            </article>
          </section>
          <section v-if="taskEvents.length" class="event-list">
            <strong>{{ t("执行事件") }}</strong>
            <div v-for="event in taskEvents.slice(-8).reverse()" :key="event.event_id">
              <span>{{ event.event_type }}</span>
              <small>{{ formatTime(event.created_at) }}</small>
            </div>
          </section>
          <div class="detail-actions">
            <button
              v-if="['planned','in_progress'].includes(selectedTask.status)"
              type="button"
              class="secondary-button danger"
              @click="cancelTask(selectedTask)"
            ><Square :size="14" />{{ t("取消任务") }}</button>
            <button
              v-if="selectedTask.status === 'failed'"
              type="button"
              class="secondary-button"
              @click="retryTask(selectedTask)"
            ><RotateCcw :size="14" />{{ t("仅重试失败片段") }}</button>
            <button
              v-if="selectedTask.output_asset_id"
              type="button"
              class="secondary-button"
              @click="emit('open-assets')"
            ><ExternalLink :size="14" />{{ t("前往资产审批") }}</button>
            <button
              v-if="selectedTask.output_asset_id"
              type="button"
              class="secondary-button"
              @click="downloadAudio"
            ><Download :size="14" />{{ t("导出 WAV") }}</button>
            <button
              v-if="selectedTask.output_asset_id && selectedTask.chapter_id && selectedTask.status === 'pending_review'"
              type="button"
              class="primary-button"
              :disabled="action === `publish:${selectedTask.task_id}`"
              @click="approveAndBindOutput"
            ><Link2 :size="14" />{{ t("批准并绑定章节") }}</button>
          </div>
        </aside>
        <div v-else class="detail-placeholder"><AudioLines :size="28" />{{ t("选择音频任务查看契约与结果") }}</div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.audio-panel { min-height: 610px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); }
.panel-heading, .panel-heading > div, .heading-actions, .voice-band header, .voice-band header > div, .dictionary-band header, .dictionary-band header > div, .feedback, .contract-warning, .detail-actions { display: flex; align-items: center; }
.panel-heading { min-height: 58px; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding: 9px 12px; }
.panel-heading > div { gap: 10px; min-width: 0; }
.heading-icon { width: 36px; height: 36px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: #e8f2f4; color: #287080; }
.panel-heading h2 { margin: 0 0 3px; font-size: 14px; }
.panel-heading p { margin: 0; color: var(--text-muted); font-size: 10px; }
.heading-actions { gap: 7px; }
.heading-actions > span { border-radius: 999px; padding: 5px 8px; font-size: 9px; font-weight: 700; }
.heading-actions > span.ready { background: #e7f8f0; color: #15704f; }
.heading-actions > span.contract { background: #fff6e5; color: #95651b; }
.icon-button { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.contract-warning { gap: 7px; margin: 10px 12px 0; border-radius: 7px; background: #fff6e5; color: #8c621f; padding: 8px 10px; font-size: 10px; }
.voice-band, .dictionary-band { display: grid; gap: 9px; border-bottom: 1px solid var(--border); padding: 10px 12px; }
.voice-band header, .dictionary-band header { justify-content: space-between; gap: 10px; }
.voice-band header > div, .dictionary-band header > div { gap: 7px; color: var(--text-secondary); }
.voice-band header strong, .dictionary-band header strong { font-size: 11px; }
.voice-band header span, .dictionary-band header span { color: var(--text-muted); font-size: 9px; }
.voice-band header button, .dictionary-band header button, .primary-button, .secondary-button, .result-list button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; border-radius: 7px; cursor: pointer; font-size: 10px; }
.voice-band header button, .dictionary-band header button { min-height: 30px; border: 1px solid var(--border); background: #fff; color: var(--text-secondary); padding: 5px 8px; }
.voice-form, .dictionary-form, .task-form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 9px; }
.dictionary-form { grid-template-columns: repeat(4,minmax(0,1fr)) auto; align-items: end; }
.voice-form label, .dictionary-form label, .task-form label { min-width: 0; display: grid; gap: 4px; color: var(--text-secondary); font-size: 9px; }
.voice-form label > span, .dictionary-form label > span, .task-form label > span { display: flex; justify-content: space-between; gap: 7px; }
.voice-form input:not([type="checkbox"]), .voice-form select, .dictionary-form input, .dictionary-form select, .task-form select, .task-form textarea, .task-form input[type="number"] { width: 100%; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-primary); padding: 7px 8px; font: inherit; resize: vertical; }
.range-field input { width: 100%; accent-color: var(--accent); }
.consent-field { grid-template-columns: auto minmax(0,1fr); align-items: center; }
.consent-field input { accent-color: var(--accent); }
.voice-list { display: flex; gap: 7px; overflow-x: auto; padding-bottom: 2px; }
.voice-item { min-width: 190px; display: grid; grid-template-columns: 18px minmax(0,1fr) auto; align-items: center; gap: 7px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); padding: 8px; text-align: left; cursor: pointer; }
.voice-item.disabled { opacity: .58; }
.voice-item input { accent-color: var(--accent); }
.voice-list span { min-width: 0; display: grid; gap: 2px; }
.voice-list strong, .voice-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.voice-list strong { font-size: 10px; }
.voice-list small, .voice-list em { color: var(--text-muted); font-size: 8px; font-style: normal; }
.dictionary-list { display: grid; grid-template-columns: repeat(auto-fit,minmax(210px,1fr)); gap: 6px; }
.dictionary-list > div { min-width: 0; display: grid; grid-template-columns: minmax(0,1fr) auto 34px; align-items: center; gap: 6px; border: 1px solid var(--border); border-radius: 7px; padding: 7px; }
.dictionary-list > div > span { min-width: 0; display: grid; gap: 2px; }
.dictionary-list strong, .dictionary-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dictionary-list strong { font-size: 10px; }
.dictionary-list small { color: var(--text-muted); font-size: 8px; }
.audio-layout { display: grid; grid-template-columns: minmax(300px,.8fr) minmax(220px,.6fr) minmax(270px,.8fr); min-height: 430px; }
.task-form { align-content: start; border-right: 1px solid var(--border); padding: 12px; }
.wide-field { grid-column: 1 / -1; }
.source-state { grid-column: 1 / -1; margin: 0; border-radius: 7px; background: var(--bg-secondary); color: var(--text-secondary); padding: 8px; font-size: 9px; }
.feedback { gap: 6px; margin: 0; border-radius: 7px; padding: 8px 10px; font-size: 9px; }
.feedback.danger, .task-error { background: #fff0f0; color: #a33f3f; }
.feedback.positive { background: #edf9f3; color: #167251; }
.primary-button { min-height: 32px; border: 1px solid var(--accent); background: var(--accent); color: #fff; padding: 6px 9px; }
.primary-button:disabled { opacity: .5; cursor: not-allowed; }
.task-list { max-height: 620px; overflow: auto; border-right: 1px solid var(--border); }
.task-list > button { width: 100%; min-height: 56px; display: grid; grid-template-columns: 20px minmax(0,1fr) auto; align-items: center; gap: 7px; border: 0; border-bottom: 1px solid var(--border); background: #fff; color: inherit; padding: 8px; text-align: left; cursor: pointer; }
.task-list > button:hover, .task-list > button.selected { background: #f0f7f8; }
.task-list button span { min-width: 0; display: grid; gap: 2px; }
.task-list strong, .task-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-list strong { font-size: 9px; }
.task-list small { color: var(--text-muted); font-size: 8px; }
.task-list em, .task-detail em { width: max-content; border-radius: 999px; padding: 4px 7px; font-size: 8px; font-style: normal; font-weight: 700; white-space: nowrap; }
em.positive { background: #e7f8f0; color: #15704f; }
em.active { background: #e8f0fa; color: #326398; }
em.warning { background: #fff6e5; color: #95651b; }
em.danger { background: #fff0f0; color: #a33f3f; }
em.muted { background: #f0eef4; color: var(--text-secondary); }
.task-detail { min-width: 0; display: grid; align-content: start; gap: 10px; padding: 12px; }
.task-detail header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.task-detail header div { min-width: 0; display: grid; gap: 2px; }
.task-detail header small { color: var(--text-muted); font-size: 8px; }
.task-detail header strong { font-size: 11px; }
.task-detail dl { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px; margin: 0; }
.task-detail dl div { min-width: 0; display: grid; gap: 2px; border-radius: 6px; background: var(--bg-secondary); padding: 7px; }
.task-detail dt { color: var(--text-muted); font-size: 7px; }
.task-detail dd { overflow: hidden; margin: 0; text-overflow: ellipsis; white-space: nowrap; font-size: 9px; }
.task-progress { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 7px; color: var(--text-muted); font-size: 8px; }
.task-progress > div { height: 7px; overflow: hidden; border-radius: 999px; background: #e9e6ef; }
.task-progress i { display: block; height: 100%; background: #347d8a; }
.segment-list { display: flex; flex-wrap: wrap; gap: 4px; }
.segment-list span { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 5px; background: #f0eef4; color: var(--text-secondary); font-size: 8px; }
.segment-list span.positive { background: #e7f8f0; color: #15704f; }
.segment-list span.active { background: #e8f0fa; color: #326398; }
.segment-list span.danger { background: #fff0f0; color: #a33f3f; }
.waveform { height: 72px; display: flex; align-items: center; gap: 1px; overflow: hidden; border-radius: 7px; background: #eef4f5; padding: 7px; }
.waveform i { min-width: 1px; flex: 1; max-height: 100%; border-radius: 2px; background: #3d8290; }
.audio-player { width: 100%; min-height: 38px; }
.task-error { display: grid; gap: 3px; margin: 0; border-radius: 7px; padding: 8px; font-size: 9px; }
.result-list { display: grid; gap: 7px; }
.result-list > strong { font-size: 9px; }
.result-list article { display: grid; gap: 6px; border-radius: 7px; background: var(--bg-secondary); padding: 8px; }
.result-list p { max-height: 130px; overflow: auto; margin: 0; white-space: pre-wrap; font-size: 9px; line-height: 1.55; }
.result-list span { color: var(--text-muted); font-size: 8px; }
.result-list article > div { display: flex; gap: 6px; }
.result-list button, .secondary-button { min-height: 29px; border: 1px solid var(--border); background: #fff; color: var(--text-secondary); padding: 5px 8px; }
.event-list { display: grid; gap: 5px; }
.event-list > strong { font-size: 9px; }
.event-list > div { display: flex; justify-content: space-between; gap: 8px; border-bottom: 1px solid var(--border); padding-bottom: 4px; font-size: 8px; }
.event-list small { color: var(--text-muted); }
.detail-actions { flex-wrap: wrap; gap: 6px; }
.secondary-button.danger { color: #a33f3f; }
.detail-placeholder, .empty-state { min-height: 180px; display: grid; place-items: center; align-content: center; gap: 7px; color: var(--text-muted); padding: 18px; text-align: center; font-size: 9px; }
.empty-state.compact { min-height: 100px; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) {
  .audio-layout { grid-template-columns: 1fr; }
  .task-form, .task-list { border-right: 0; border-bottom: 1px solid var(--border); }
  .task-list { max-height: 240px; }
}
@media (max-width: 620px) {
  .panel-heading { align-items: flex-start; flex-direction: column; }
  .heading-actions { width: 100%; justify-content: space-between; }
  .voice-form, .dictionary-form, .task-form { grid-template-columns: 1fr; }
  .wide-field, .source-state { grid-column: auto; }
  .task-detail dl { grid-template-columns: 1fr; }
}
</style>
