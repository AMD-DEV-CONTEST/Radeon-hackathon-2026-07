<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { Bold, Heading1, Heading2, History, Italic, Languages, Link2, List, Maximize2, Minimize2, Plus, Quote, Save, TriangleAlert, Underline } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";
import ChapterTranslationPanel from "./ChapterTranslationPanel.vue";

const props = defineProps({
  immersive: { type: Boolean, default: false },
  expanded: { type: Boolean, default: false },
});
const emit = defineEmits(["request-immersive", "exit-immersive"]);
const store = useAppStore();
const { t } = useI18n();
const editorRef = ref(null);
const newLanguageCode = ref("en-US");
const chapterLanguageOptions = ["zh-CN", "en-US"];

const tools = [
  { id: "bold", label: "粗体", icon: Bold },
  { id: "italic", label: "斜体", icon: Italic },
  { id: "underline", label: "下划线", icon: Underline },
  { id: "heading1", label: "一级标题", icon: Heading1 },
  { id: "heading2", label: "二级标题", icon: Heading2 },
  { id: "quote", label: "引用", icon: Quote },
  { id: "list", label: "列表", icon: List },
  { id: "link", label: "链接", icon: Link2 },
];
const wordCount = computed(() => store.draftContent.trim().length);
const missingLanguageOptions = computed(() => {
  const existing = new Set(store.chapterLocalizations.map((item) => item.language_code));
  return chapterLanguageOptions.filter((languageCode) => !existing.has(languageCode));
});
const canManageTranslations = computed(() => store.hasCapability("manage_translations"));
const localizationStatusLabel = computed(() => {
  if (store.activeChapter?.is_source) return t("源版本");
  return t({
    not_started: "未开始",
    draft: "草稿",
    generated: "已生成",
    review_required: "待复核",
    approved: "已批准",
    stale: "需要复核",
  }[store.chapterLocalizationStatus] || "状态未知");
});
const saveLabel = computed(() => {
  if (store.chapterSaving) return t("正在保存");
  if (store.chapterDirty) return t("有未保存修改");
  return store.lastSavedAt ? t("已保存于 {time}", { time: store.lastSavedAt }) : t("尚未保存");
});
let autosaveTimer = null;

function scheduleAutosave() {
  window.clearTimeout(autosaveTimer);
  if (!store.activeChapter?.chapter_id) return;
  autosaveTimer = window.setTimeout(() => store.autosaveCurrentChapter(), 1600);
}

function updateDraft(event) {
  store.setDraftContent(event.target.value);
  scheduleAutosave();
}

function updateMeta(field, event) {
  store.setChapterMeta({ [field]: event.target.value });
  scheduleAutosave();
}

async function replaceSelection(prefix, suffix = "", placeholder = t("正文")) {
  const editor = editorRef.value;
  if (!editor || !store.activeBook) return;
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const selected = store.draftContent.slice(start, end) || placeholder;
  const inserted = `${prefix}${selected}${suffix}`;
  store.setDraftContent(`${store.draftContent.slice(0, start)}${inserted}${store.draftContent.slice(end)}`);
  scheduleAutosave();
  await nextTick();
  editor.focus();
  editor.setSelectionRange(start + prefix.length, start + prefix.length + selected.length);
}

async function prefixSelectedLines(prefix) {
  const editor = editorRef.value;
  if (!editor || !store.activeBook) return;
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const selected = store.draftContent.slice(start, end) || t("正文");
  const inserted = selected.split("\n").map((line) => `${prefix}${line}`).join("\n");
  store.setDraftContent(`${store.draftContent.slice(0, start)}${inserted}${store.draftContent.slice(end)}`);
  scheduleAutosave();
  await nextTick();
  editor.focus();
  editor.setSelectionRange(start, start + inserted.length);
}

function applyFormat(tool) {
  const inlineFormats = {
    bold: ["**", "**", t("粗体文字")],
    italic: ["*", "*", t("斜体文字")],
    underline: ["<u>", "</u>", t("下划线文字")],
    link: ["[", "](https://)", t("链接文字")],
  };
  if (inlineFormats[tool]) {
    replaceSelection(...inlineFormats[tool]);
    return;
  }
  const linePrefix = { heading1: "# ", heading2: "## ", quote: "> ", list: "- " }[tool];
  if (linePrefix) prefixSelectedLines(linePrefix);
}

async function analyzeFor(kind) {
  const result = await store.createDraftChangeSet();
  if (!result) return;
  store.notifyAction(t(kind === "reminder" ? "设定候选已更新，请在右侧审核" : "冲突结果已更新，请在右侧审核"));
}

function requestImmersive(event) {
  if (props.immersive || event?.target?.closest("button,input,select")) return;
  emit("request-immersive");
}

function languageLabel(languageCode) {
  return t({
    "zh-CN": "简体中文",
    "en-US": "英语",
  }[languageCode] || languageCode);
}

function localizationOptionLabel(localization) {
  const role = localization.is_source
    ? t("源版本")
    : t({
      not_started: "未开始",
      draft: "草稿",
      generated: "已生成",
      review_required: "待复核",
      approved: "已批准",
      stale: "需要复核",
    }[localization.translation_status] || "状态未知");
  return `${languageLabel(localization.language_code)} · ${role}`;
}

async function switchLocalization(event) {
  await store.switchChapterLocalization(event.target.value);
}

async function createLanguageVersion() {
  const available = missingLanguageOptions.value;
  const languageCode = available.includes(newLanguageCode.value)
    ? newLanguageCode.value
    : available[0];
  if (!languageCode) return;
  await store.createChapterLanguageVersion(languageCode);
  newLanguageCode.value = missingLanguageOptions.value[0] || "en-US";
}

onBeforeUnmount(() => window.clearTimeout(autosaveTimer));
</script>

<template>
  <section class="workspace-card" :class="{ immersive, expanded }" @dblclick="requestImmersive">
    <header class="workspace-header">
      <div class="title-wrap">
        <span class="pen-icon">✎</span>
        <div>
          <h2>{{ t("章节正文") }}</h2>
          <p>{{ store.activeChapter ? t("当前记录：{id}", { id: store.activeChapter.chapter_id }) : t("创建章节后开始持久化写作") }}</p>
        </div>
      </div>
      <div class="header-actions">
        <div class="save-state" :class="{ dirty: store.chapterDirty, error: store.chapterError }">
          <span class="green-dot"></span>
          <span>{{ saveLabel }}</span>
        </div>
        <button v-if="!immersive" class="mode-btn" type="button" @click="emit('request-immersive')">
          <Maximize2 :size="14" />{{ t("沉浸写作") }}
        </button>
        <button v-else class="mode-btn" type="button" @click="emit('exit-immersive')">
          <Minimize2 :size="14" />{{ t("退出沉浸") }}
        </button>
      </div>
    </header>

    <div class="chapter-bar">
      <label class="chapter-title-field">
        <span>{{ t("章节标题") }}</span>
        <input
          :value="store.chapterMeta.title"
          :disabled="!store.activeBook"
          :placeholder="t('例如：北境长城工程记录')"
          @input="updateMeta('title', $event)"
        />
      </label>
      <div class="chapter-localization-field">
        <span>{{ t("章节语言版本") }}</span>
        <div class="localization-controls">
          <select
            :value="store.activeChapter?.chapter_id || ''"
            :disabled="!store.activeChapter || store.chapterLocalizationsLoading"
            :aria-label="t('章节语言版本')"
            @change="switchLocalization"
          >
            <option
              v-for="localization in store.chapterLocalizations"
              :key="localization.localization_id"
              :value="localization.chapter_id"
            >
              {{ localizationOptionLabel(localization) }}
            </option>
          </select>
          <template v-if="missingLanguageOptions.length && canManageTranslations">
            <select
              class="new-language-select"
              :value="missingLanguageOptions.includes(newLanguageCode) ? newLanguageCode : missingLanguageOptions[0]"
              :aria-label="t('新增语言')"
              :disabled="store.chapterLocalizationsLoading"
              @change="newLanguageCode = $event.target.value"
            >
              <option v-for="languageCode in missingLanguageOptions" :key="languageCode" :value="languageCode">
                {{ languageLabel(languageCode) }}
              </option>
            </select>
            <button
              class="add-localization-button"
              type="button"
              :title="t('创建语言版本')"
              :aria-label="t('创建语言版本')"
              :disabled="store.chapterLocalizationsLoading"
              @click="createLanguageVersion"
            >
              <Plus :size="15" />
            </button>
          </template>
        </div>
        <small>{{ localizationStatusLabel }} · r{{ store.activeChapter?.content_revision || 1 }}</small>
      </div>
      <div class="chapter-coordinate"><span>{{ t("卷") }}</span><strong>{{ store.chapterMeta.volume }}</strong></div>
      <div class="chapter-coordinate"><span>{{ t("章节") }}</span><strong>{{ store.chapterMeta.chapterNo }}</strong></div>
    </div>

    <div
      v-if="store.activeChapter && !store.activeChapter.is_source"
      class="chapter-localization-state"
      :class="{ stale: store.chapterLocalizationStatus === 'stale' }"
    >
      <TriangleAlert v-if="store.chapterLocalizationStatus === 'stale'" :size="17" />
      <Languages v-else :size="17" />
      <span>
        <strong>{{ store.chapterLocalizationStatus === "stale" ? t("此语言版本需要复核") : t("本地化章节草稿") }}</strong>
        <small>{{ store.chapterLocalizationStatus === "stale" ? t("源章节已更新；旧译文已保留，重新审核前不会视为最新版本。") : t("此版本与源章节共享顺序和故事时间上下文。") }}</small>
      </span>
    </div>

    <ChapterTranslationPanel v-if="!immersive" />

    <textarea
      ref="editorRef"
      class="editor"
      :value="store.draftContent"
      :disabled="!store.activeBook"
      :placeholder="t('在这里写章节正文。需要入库的设定变化，请通过“分析本章”生成预览后再确认。')"
      @input="updateDraft"
    ></textarea>

    <div class="format-toolbar" :aria-label="t('格式工具栏')">
      <button v-for="tool in tools" :key="tool.id" type="button" :title="t(tool.label)" :aria-label="t(tool.label)" :disabled="!store.activeBook" @click="applyFormat(tool.id)">
        <component :is="tool.icon" :size="14" />
      </button>
      <button type="button" :title="t('读取版本历史')" :aria-label="t('读取版本历史')" :disabled="!store.activeChapter" @click="store.loadChapterVersions()"><History :size="14" /></button>
    </div>

    <footer class="workspace-footer">
      <span class="word-count">{{ t("{count} 字", { count: wordCount }) }} · {{ store.chapterMeta.volume }} / {{ store.chapterMeta.chapterNo }}</span>
      <div class="action-row">
        <button class="btn btn-secondary" type="button" :disabled="!store.activeBook || store.chapterSaving" @click="store.markSaved()"><Save :size="15" />{{ t(store.chapterSaving ? "保存中" : "保存正文") }}</button>
        <button class="btn btn-primary" type="button" :disabled="!store.activeChapter || store.analysisLoading || wordCount < 50" @click="store.createDraftChangeSet()">{{ t(store.analysisLoading ? "分析中" : "分析本章") }}</button>
        <button class="btn btn-secondary" type="button" :disabled="!store.activeChapter || store.analysisLoading || wordCount < 50" @click="analyzeFor('reminder')">{{ t("设定提醒") }}</button>
        <button class="btn btn-secondary" type="button" :disabled="!store.activeChapter || store.analysisLoading || wordCount < 50" @click="analyzeFor('conflict')">{{ t("检查冲突") }}</button>
        <button class="btn btn-primary new-doc" type="button" :disabled="!store.activeBook || store.chapterLoading" @click="store.createChapterDraft()">{{ t("新建章节") }}</button>
      </div>
    </footer>

    <div v-if="immersive && store.pendingChangeSet" class="changeset-preview">
      <div>
        <strong>{{ t("章节分析预览") }}</strong>
        <p>{{ store.pendingChangeSet.changeset_id }} · {{ store.pendingChangeSet.status }}</p>
      </div>
      <span>{{ t("{count} 条冲突待复核", { count: (store.pendingChangeSet.conflicts || []).length }) }}</span>
    </div>
  </section>
</template>

<style scoped>
.workspace-card {
  display: grid;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.92);
  box-shadow: var(--card-shadow);
}

.workspace-card.immersive {
  height: 100%;
  min-height: 0;
  grid-template-rows: auto auto 1fr auto auto;
  background: rgba(255,255,255,0.98);
  box-shadow: none;
}

.workspace-card.expanded:not(.immersive) {
  min-height: clamp(520px, 64vh, 780px);
  grid-template-rows: auto auto minmax(320px, 1fr) auto auto;
}

.workspace-header,
.workspace-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
}

.title-wrap,
.header-actions,
.save-state {
  display: flex;
  align-items: center;
  gap: 10px;
}

.save-state.dirty .green-dot { background: #d6a34a; }
.save-state.error .green-dot { background: #d65c5c; }

.title-wrap h2 {
  font-size: 17px;
}

.title-wrap p {
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 12px;
}

.pen-icon {
  color: var(--accent);
  font-size: 20px;
}

.save-state {
  color: var(--text-muted);
  font-size: 12px;
}

.green-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #32c48d;
}

.mode-btn {
  min-height: 30px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.75);
  color: var(--accent);
  cursor: pointer;
  padding: 4px 10px;
  font-size: 12px;
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.chapter-bar {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(260px, .9fr) 140px 130px;
  gap: 12px;
  padding: 0 16px 14px;
}

.chapter-localization-field { min-width: 0; display: grid; align-content: end; gap: 6px; }
.chapter-localization-field > span, .chapter-localization-field > small { color: var(--text-secondary); font-size: 12px; }
.chapter-localization-field > small { overflow: hidden; color: var(--text-muted); text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.localization-controls { min-width: 0; display: flex; gap: 5px; }
.localization-controls select { min-width: 0; min-height: 35px; flex: 1 1 120px; padding-block: 5px; font-size: 11px; }
.localization-controls .new-language-select { flex: 0 1 100px; }
.add-localization-button { width: 35px; height: 35px; flex: 0 0 35px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--accent); cursor: pointer; }
.add-localization-button:disabled { color: var(--text-muted); cursor: not-allowed; }
.chapter-localization-state { min-height: 44px; display: grid; grid-template-columns: auto minmax(0,1fr); gap: 9px; align-items: center; border-top: 1px solid #d9e8e0; border-bottom: 1px solid #d9e8e0; background: #f3fbf7; color: #167251; padding: 8px 16px; }
.chapter-localization-state.stale { border-color: #ead7bc; background: #fff9ef; color: #9a5b18; }
.chapter-localization-state span { min-width: 0; display: grid; gap: 2px; }
.chapter-localization-state strong { font-size: 11px; }
.chapter-localization-state small { color: var(--text-secondary); font-size: 10px; line-height: 1.45; }
.chapter-coordinate { min-width: 0; display: grid; align-content: end; gap: 6px; }
.chapter-coordinate strong { min-height: 35px; display: flex; align-items: center; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-secondary); color: var(--text-secondary); padding: 7px 10px; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }

.chapter-bar label {
  display: grid;
  gap: 6px;
}

.chapter-bar span {
  color: var(--text-secondary);
  font-size: 12px;
}

.editor {
  min-height: 220px;
  resize: vertical;
  border: 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  border-radius: 0;
  padding: 18px;
  color: var(--text-primary);
  line-height: 1.8;
  background: rgba(255,255,255,0.65);
}

.editor:disabled { background: #f7f7fa; color: var(--text-muted); cursor: not-allowed; }

.expanded:not(.immersive) .editor {
  min-height: clamp(320px, 46vh, 600px);
  height: 100%;
}

.immersive .editor {
  min-height: 0;
  height: 100%;
  resize: none;
  font-size: 16px;
  padding: 30px clamp(28px, 6vw, 88px);
  line-height: 2;
}

.immersive .workspace-header {
  padding-block: 10px;
}

.immersive .title-wrap p {
  display: none;
}

.format-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
}

.format-toolbar button {
  width: 28px;
  height: 26px;
  flex: 0 0 28px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #3e3a50;
  cursor: pointer;
  font-size: 12px;
}

.format-toolbar button:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.format-toolbar button:disabled { color: var(--text-muted); cursor: not-allowed; }

.word-count {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 12px;
}

.action-row {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  align-items: center;
  width: 100%;
}

.action-row .btn {
  min-width: 0;
  padding-inline: 7px;
  white-space: nowrap;
  font-size: 12px;
}

.action-row .btn:disabled { background: #aaa5ba; color: #fff; box-shadow: none; cursor: not-allowed; transform: none; }

.new-doc {
  justify-self: stretch;
}

.changeset-preview {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin: 0 16px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  padding: 12px;
}

.changeset-preview p,
.changeset-preview span {
  color: var(--text-secondary);
  font-size: 12px;
}

@media (max-width: 1480px) {
  .chapter-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .workspace-header,
  .workspace-footer,
  .changeset-preview {
    align-items: stretch;
    flex-direction: column;
  }

  .chapter-bar {
    grid-template-columns: 1fr;
  }

  .action-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .new-doc {
    justify-self: stretch;
    grid-column: 1 / -1;
  }
}


@media (max-height: 760px) {
  .workspace-card.expanded:not(.immersive) {
    min-height: 500px;
  }

  .expanded:not(.immersive) .editor {
    min-height: 300px;
  }
}
</style>
