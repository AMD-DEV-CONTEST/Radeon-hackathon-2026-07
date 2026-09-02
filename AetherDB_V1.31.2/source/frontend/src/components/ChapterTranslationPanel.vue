<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Languages,
  RefreshCw,
  Save,
  ShieldAlert,
  Sparkles,
  X,
} from "@lucide/vue";
import {
  approveChapterTranslation,
  createChapterTranslation,
  listChapterTranslations,
  listTranslationModels,
  rejectChapterTranslation,
  reviewChapterLocalization,
  updateChapterTranslation,
} from "../api/chapters.js";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();
const expanded = ref(false);
const loading = ref(false);
const error = ref("");
const models = ref([]);
const source = ref(null);
const translations = ref([]);
const targetLanguage = ref("en-US");
const modelProfileId = ref("");
const cloudUploadConfirmed = ref(false);
const draftTitle = ref("");
const draftContent = ref("");

const languageOptions = [
  { value: "zh-CN", label: "简体中文" },
  { value: "en-US", label: "英语" },
];
const sourceChapterId = computed(() => (
  store.activeChapter?.source_chapter_id || store.activeChapter?.chapter_id || ""
));
const currentSourceLanguage = computed(() => (
  source.value?.language_code
  || store.chapterLocalizations.find((item) => item.is_source)?.language_code
  || "zh-CN"
));
const availableTargets = computed(() => (
  languageOptions.filter((item) => item.value !== currentSourceLanguage.value)
));
const activeTask = computed(() => (
  translations.value.find((item) => (
    item.target_language_code === targetLanguage.value
    && ["review_required", "stale", "failed", "approved"].includes(item.task_status)
  )) || null
));
const selectedModel = computed(() => (
  models.value.find((item) => item.model_profile_id === modelProfileId.value) || null
));
const needsCloudConsent = computed(() => (
  selectedModel.value ? !selectedModel.value.is_local : false
));
const canEditTask = computed(() => (
  ["review_required", "failed"].includes(activeTask.value?.task_status)
));
const canReviewTask = computed(() => activeTask.value?.task_status === "review_required");
const canReviewLocalization = computed(() => (
  store.activeChapter
  && !store.activeChapter.is_source
  && ["draft", "stale", "review_required"].includes(store.chapterLocalizationStatus)
));

function languageLabel(code) {
  return t(languageOptions.find((item) => item.value === code)?.label || code);
}

function statusLabel(status) {
  return t({
    running: "翻译中",
    review_required: "待复核",
    approved: "已批准",
    rejected: "已拒绝",
    stale: "需要复核",
    failed: "翻译失败",
  }[status] || "状态未知");
}

function syncDraft(task = activeTask.value) {
  draftTitle.value = task?.draft_title || "";
  draftContent.value = task?.draft_content || "";
}

async function loadModels() {
  try {
    const response = await listTranslationModels();
    models.value = response?.models || [];
  } catch {
    models.value = [];
  }
}

async function loadTranslations() {
  if (!sourceChapterId.value) {
    source.value = null;
    translations.value = [];
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const response = await listChapterTranslations(sourceChapterId.value);
    source.value = response?.source || null;
    translations.value = response?.translations || [];
    const activeTarget = store.activeChapter?.is_source
      ? ""
      : store.activeChapter?.language_code;
    const targetValues = availableTargets.value.map((item) => item.value);
    targetLanguage.value = targetValues.includes(activeTarget)
      ? activeTarget
      : targetValues.includes(targetLanguage.value)
        ? targetLanguage.value
        : targetValues[0] || "en-US";
    syncDraft();
  } catch (err) {
    error.value = err?.message || t("翻译任务读取失败");
  } finally {
    loading.value = false;
  }
}

async function generateTranslation() {
  if (!sourceChapterId.value || !targetLanguage.value) return;
  if (needsCloudConsent.value && !cloudUploadConfirmed.value) {
    error.value = t("使用云端模型前必须确认发送章节标题和全文");
    return;
  }
  if (store.chapterDirty) {
    const saved = await store.autosaveCurrentChapter(true);
    if (!saved) {
      error.value = store.chapterError || t("翻译前保存失败");
      return;
    }
  }
  loading.value = true;
  error.value = "";
  try {
    const response = await createChapterTranslation(sourceChapterId.value, {
      target_language_code: targetLanguage.value,
      model_profile_id: modelProfileId.value || null,
      cloud_upload_confirmed: cloudUploadConfirmed.value,
      request_id: `translation-ui-${Date.now()}`,
    });
    await loadTranslations();
    const createdId = response?.translation?.translation_id;
    const created = translations.value.find((item) => item.translation_id === createdId);
    syncDraft(created);
    store.notifyAction(t("翻译草稿已生成，批准前不会写入目标章节"));
  } catch (err) {
    const firstCandidate = err?.detail?.candidates?.[0]?.model_profile_id;
    if (firstCandidate && !modelProfileId.value) modelProfileId.value = firstCandidate;
    error.value = err?.message || t("章节翻译失败");
  } finally {
    loading.value = false;
  }
}

async function saveTaskDraft() {
  if (!activeTask.value || !draftTitle.value.trim() || !draftContent.value.trim()) return;
  loading.value = true;
  error.value = "";
  try {
    await updateChapterTranslation(activeTask.value.translation_id, {
      title: draftTitle.value.trim(),
      content: draftContent.value,
    });
    await loadTranslations();
    store.notifyAction(t("翻译草稿已保存"));
  } catch (err) {
    error.value = err?.message || t("翻译草稿保存失败");
  } finally {
    loading.value = false;
  }
}

async function approveTask() {
  if (!activeTask.value || !source.value?.content_hash) return;
  loading.value = true;
  error.value = "";
  try {
    if (
      draftTitle.value !== activeTask.value.draft_title
      || draftContent.value !== activeTask.value.draft_content
    ) {
      await updateChapterTranslation(activeTask.value.translation_id, {
        title: draftTitle.value.trim(),
        content: draftContent.value,
      });
    }
    const response = await approveChapterTranslation(
      activeTask.value.translation_id,
      source.value.content_hash,
    );
    store.chapterLocalizations = response?.localizations || store.chapterLocalizations;
    if (response?.chapter?.chapter_id) await store.openChapter(response.chapter.chapter_id);
    await loadTranslations();
    store.notifyAction(t("译文已批准并写入目标章节"));
  } catch (err) {
    error.value = err?.message || t("翻译批准失败");
  } finally {
    loading.value = false;
  }
}

async function rejectTask() {
  if (!activeTask.value) return;
  loading.value = true;
  error.value = "";
  try {
    await rejectChapterTranslation(activeTask.value.translation_id);
    await loadTranslations();
    store.notifyAction(t("翻译草稿已拒绝"));
  } catch (err) {
    error.value = err?.message || t("翻译拒绝失败");
  } finally {
    loading.value = false;
  }
}

async function reviewManualLocalization(action) {
  const chapterId = store.activeChapter?.chapter_id;
  if (!chapterId || !source.value?.content_hash) return;
  if (store.chapterDirty) {
    const saved = await store.autosaveCurrentChapter(true);
    if (!saved) return;
  }
  loading.value = true;
  error.value = "";
  try {
    await reviewChapterLocalization(chapterId, action, source.value.content_hash);
    await store.openChapter(chapterId);
    await loadTranslations();
    store.notifyAction(t(action === "approve" ? "人工译文已批准" : "人工译文已拒绝"));
  } catch (err) {
    error.value = err?.message || t("人工译文审核失败");
  } finally {
    loading.value = false;
  }
}

async function toggleExpanded() {
  expanded.value = !expanded.value;
  if (expanded.value) await loadTranslations();
}

watch(
  () => store.activeChapter?.chapter_id,
  async () => {
    if (expanded.value) await loadTranslations();
  },
);
watch(activeTask, (task) => syncDraft(task));
watch(modelProfileId, () => {
  if (selectedModel.value?.is_local) cloudUploadConfirmed.value = false;
});
onMounted(loadModels);
</script>

<template>
  <section v-if="store.activeChapter && store.hasCapability('manage_translations')" class="translation-band">
    <button class="translation-toggle" type="button" :aria-expanded="expanded" @click="toggleExpanded">
      <span><Languages :size="16" /><strong>{{ t("翻译工作流") }}</strong></span>
      <span class="translation-toggle-state">
        {{ activeTask ? statusLabel(activeTask.task_status) : t("尚无模型草稿") }}
        <ChevronUp v-if="expanded" :size="15" />
        <ChevronDown v-else :size="15" />
      </span>
    </button>

    <div v-if="expanded" class="translation-body">
      <div class="translation-controls">
        <label>
          <span>{{ t("目标语言") }}</span>
          <select v-model="targetLanguage" :disabled="loading">
            <option v-for="item in availableTargets" :key="item.value" :value="item.value">
              {{ languageLabel(item.value) }}
            </option>
          </select>
        </label>
        <label>
          <span>{{ t("翻译模型") }}</span>
          <select v-model="modelProfileId" :disabled="loading">
            <option value="">{{ t("自动选择唯一模型") }}</option>
            <option v-for="model in models" :key="model.model_profile_id" :value="model.model_profile_id">
              {{ model.display_name }} · {{ model.provider_name }}
            </option>
          </select>
        </label>
        <label class="cloud-consent">
          <input v-model="cloudUploadConfirmed" type="checkbox" :disabled="loading || selectedModel?.is_local" />
          <span>{{ t("允许把章节标题和全文发送给所选云端 Provider") }}</span>
        </label>
        <button class="btn btn-primary generate-button" type="button" :disabled="loading || !store.draftContent.trim()" @click="generateTranslation">
          <RefreshCw v-if="loading" :size="15" class="spin" />
          <Sparkles v-else :size="15" />
          {{ t(loading ? "处理中" : "生成翻译草稿") }}
        </button>
      </div>

      <p v-if="error" class="translation-error"><ShieldAlert :size="15" />{{ error }}</p>

      <div v-if="activeTask" class="translation-review">
        <header>
          <span>
            <strong>{{ languageLabel(activeTask.target_language_code) }}</strong>
            <small>{{ statusLabel(activeTask.task_status) }} · {{ activeTask.provider_model_name || t("未记录模型") }}</small>
          </span>
          <small>{{ t("来源 revision") }} · {{ activeTask.source_revision_hash.slice(0, 10) }}</small>
        </header>
        <input v-model="draftTitle" :readonly="!canEditTask" :aria-label="t('翻译标题草稿')" />
        <textarea v-model="draftContent" :readonly="!canEditTask" :aria-label="t('翻译正文草稿')"></textarea>
        <footer>
          <button v-if="canEditTask" class="btn btn-secondary" type="button" :disabled="loading || !draftTitle.trim() || !draftContent.trim()" @click="saveTaskDraft">
            <Save :size="14" />{{ t("保存翻译草稿") }}
          </button>
          <button v-if="canReviewTask" class="btn btn-primary" type="button" :disabled="loading" @click="approveTask">
            <Check :size="14" />{{ t("批准并写入目标章节") }}
          </button>
          <button v-if="['review_required', 'failed', 'stale'].includes(activeTask.task_status)" class="btn btn-secondary danger-text" type="button" :disabled="loading" @click="rejectTask">
            <X :size="14" />{{ t("拒绝草稿") }}
          </button>
        </footer>
      </div>

      <div v-if="canReviewLocalization" class="manual-review">
        <span>
          <strong>{{ t("人工译文审核") }}</strong>
          <small>{{ t("当前正文只会在明确批准后成为有效译文。") }}</small>
        </span>
        <button class="btn btn-primary" type="button" :disabled="loading" @click="reviewManualLocalization('approve')">
          <Check :size="14" />{{ t("批准当前译文") }}
        </button>
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="reviewManualLocalization('reject')">
          <X :size="14" />{{ t("拒绝当前译文") }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.translation-band {
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: #fbfbfd;
}

.translation-toggle {
  width: 100%;
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  padding: 9px 16px;
}

.translation-toggle > span,
.translation-toggle-state {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.translation-toggle-state {
  color: var(--text-muted);
  font-size: 11px;
}

.translation-body {
  display: grid;
  gap: 12px;
  border-top: 1px solid var(--border);
  padding: 12px 16px 14px;
}

.translation-controls {
  display: grid;
  grid-template-columns: minmax(130px, .55fr) minmax(220px, 1fr) minmax(250px, 1.2fr) auto;
  gap: 9px;
  align-items: end;
}

.translation-controls label {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.translation-controls label > span {
  color: var(--text-secondary);
  font-size: 11px;
}

.translation-controls select {
  width: 100%;
  min-height: 34px;
}

.translation-controls .cloud-consent {
  min-height: 34px;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #fff;
  padding: 6px 9px;
}

.cloud-consent input {
  width: 15px;
  height: 15px;
}

.generate-button {
  min-height: 34px;
  white-space: nowrap;
}

.translation-error {
  display: flex;
  align-items: center;
  gap: 7px;
  color: #a33b3b;
  font-size: 11px;
}

.translation-review {
  display: grid;
  gap: 8px;
  border-top: 1px solid var(--border);
  padding-top: 11px;
}

.translation-review header,
.translation-review footer,
.manual-review {
  display: flex;
  align-items: center;
  gap: 8px;
}

.translation-review header {
  justify-content: space-between;
}

.translation-review header span,
.manual-review span {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.translation-review small,
.manual-review small {
  color: var(--text-muted);
  font-size: 10px;
}

.translation-review textarea {
  min-height: 170px;
  max-height: 340px;
  resize: vertical;
  line-height: 1.7;
}

.translation-review [readonly] {
  background: var(--bg-secondary);
}

.translation-review footer {
  justify-content: flex-end;
  flex-wrap: wrap;
}

.manual-review {
  justify-content: flex-end;
  border-top: 1px solid var(--border);
  padding-top: 11px;
}

.manual-review span {
  margin-right: auto;
}

.danger-text {
  color: #a33b3b;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1480px) {
  .translation-controls {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .translation-controls {
    grid-template-columns: 1fr;
  }

  .translation-review header,
  .manual-review {
    align-items: stretch;
    flex-direction: column;
  }

  .translation-review footer {
    justify-content: stretch;
  }

  .translation-review footer .btn,
  .manual-review .btn {
    width: 100%;
  }
}
</style>
