<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileText,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Square,
  Upload,
} from "@lucide/vue";
import {
  cancelImportTask,
  confirmImportTask,
  createImportTask,
  getImportTask,
  getImportTaskPreview,
  listImportTasks,
  retryImportTask,
} from "../api/import.js";
import { confirmChangeSet, getChangeSet } from "../api/changesets.js";
import { getAnalysisPreferences, updateAnalysisPreferences } from "../api/models.js";
import { getActiveBook, getActiveDatabase } from "../api/settings.js";
import { ENTITY_TYPE_LABELS } from "../domain/entities.js";

const route = useRoute();
const router = useRouter();
const { locale, t } = useI18n();
const sourceText = ref("");
const importMode = ref(normalizeMode(route.query.source));
const sourceFormat = ref("auto");
const databaseId = ref(String(route.query.database_id || ""));
const bookId = ref(String(route.query.book_id || ""));
const task = ref(null);
const preview = ref(null);
const tasks = ref([]);
const selectedIds = ref([]);
const loading = ref(false);
const confirming = ref(false);
const autoAnalyze = ref(true);
const analysisMode = ref("");
const savedAnalysisMode = ref("ask");
const cloudModelAvailable = ref(false);
const analysisChangeSets = ref([]);
const confirmingChangeSet = ref("");
const error = ref("");
const pollTimer = ref(null);

const modes = [
  { key: "quick_notes", label: "设定与笔记", description: "把零散资料整理为实体候选", icon: FileText },
  { key: "chapters", label: "章节导入", description: "识别章节并批量写入草稿", icon: BookOpen },
  { key: "full_book", label: "整本书导入", description: "解析长文本和完整章节结构", icon: Upload },
  { key: "world_setting", label: "世界设定", description: "整理规则、地点、势力与概念", icon: Square },
];

function normalizeMode(value) {
  if (value === "text") return "quick_notes";
  if (["quick_notes", "chapters", "full_book", "world_setting", "entity_data"].includes(value)) return value;
  return "chapters";
}

const wordCount = computed(() => sourceText.value.trim().length);
const isChapterMode = computed(() => ["chapters", "full_book"].includes(preview.value?.detected_mode || importMode.value));
const candidates = computed(() => isChapterMode.value ? (preview.value?.chapter_candidates || []) : (preview.value?.entity_candidates || []));
const selectedEntityTitles = computed(() => new Set(
  candidates.value
    .filter((item) => selectedIds.value.includes(item.candidate_id))
    .map((item) => item.title),
));
const relationCandidates = computed(() => preview.value?.relation_candidates || []);
const selectedRelationCandidates = computed(() => relationCandidates.value.filter(
  (item) => selectedEntityTitles.value.has(item.source) && selectedEntityTitles.value.has(item.target),
));
const visibleRelationCandidates = computed(() => selectedRelationCandidates.value.slice(0, 8));
const analysisChoiceModes = ["chapters", "full_book", "world_setting"];
const needsAnalysisChoice = computed(() => autoAnalyze.value && analysisChoiceModes.includes(importMode.value));
const canCreate = computed(() => Boolean(
  sourceText.value.trim()
  && databaseId.value
  && bookId.value
  && !loading.value
  && (!needsAnalysisChoice.value || analysisMode.value),
));
const TASK_STATUS_KEYS = {
  queued: "等待处理", running: "正在解析", awaiting_confirmation: "等待确认", completed: "已完成", failed: "失败", cancelled: "已取消",
};
const TASK_STAGE_KEYS = {
  parsing: "清理与识别文本", chapter_detection: "识别章节结构", candidate_extraction: "生成候选项", awaiting_confirmation: "等待用户确认",
  formal_write: "写入已确认内容", analysis_queued: "等待实体识别", chapter_analysis: "正在识别实体与关系",
  analysis_completed: "实体候选等待确认", analysis_failed: "实体识别失败", completed: "导入完成", failed: "任务失败", cancelled: "任务已取消",
};
const RECENT_STATUS_KEYS = {
  queued: "等待",
  running: "解析中",
  awaiting_confirmation: "待确认",
  completed: "完成",
  failed: "失败",
  cancelled: "取消",
};
const taskStatusLabel = computed(() => t(TASK_STATUS_KEYS[task.value?.status] || "尚未创建任务"));
const stageLabel = computed(() => t(TASK_STAGE_KEYS[task.value?.stage] || "准备导入"));

function formatNumber(value) {
  return Number(value || 0).toLocaleString(locale.value);
}

function recentTaskStatus(status) {
  return t(RECENT_STATUS_KEYS[status] || status);
}

function relationLabel(item) {
  return `${item.source || "?"} -> ${item.relation_type || "related_to"} -> ${item.target || "?"}`;
}

const changeSetGroups = computed(() => [
  { key: "entities", label: "新增实体", count: isChapterMode.value ? 0 : candidates.value.length },
  { key: "updates", label: "更新实体", count: 0 },
  { key: "relations", label: "新关系", count: preview.value?.relation_candidates?.length || 0 },
  { key: "chapters", label: "章节草稿", count: isChapterMode.value ? candidates.value.length : 0 },
  { key: "timeline", label: "时间线事件", count: 0 },
  { key: "conflicts", label: "冲突", count: 0 },
  { key: "warnings", label: "警告", count: preview.value?.warnings?.length || 0 },
  { key: "unresolved", label: "未解决项", count: 0 },
]);

const displayedChangeSetGroups = computed(() => changeSetGroups.value.map((group) => (
  group.key === "relations"
    ? {
      ...group,
      count: isChapterMode.value
        ? relationCandidates.value.length
        : selectedRelationCandidates.value.length,
    }
    : group
)));

async function loadContext() {
  if (databaseId.value && bookId.value) return;
  const [database, book] = await Promise.allSettled([getActiveDatabase(), getActiveBook()]);
  if (!databaseId.value && database.status === "fulfilled") databaseId.value = database.value?.active_database_id || "";
  if (!bookId.value && book.status === "fulfilled") bookId.value = book.value?.active_book_id || "";
}

async function loadAnalysisPreference() {
  try {
    const result = await getAnalysisPreferences();
    savedAnalysisMode.value = result?.default_mode || "ask";
    cloudModelAvailable.value = Boolean(result?.cloud_model_available);
    analysisMode.value = savedAnalysisMode.value === "local_rules"
      || (savedAnalysisMode.value === "cloud_model" && cloudModelAvailable.value)
      ? savedAnalysisMode.value
      : "";
  } catch {
    savedAnalysisMode.value = "ask";
    analysisMode.value = "";
    cloudModelAvailable.value = false;
  }
}

async function loadTaskList() {
  try { tasks.value = (await listImportTasks(20))?.tasks || []; }
  catch { tasks.value = []; }
}

function stopPolling() {
  if (pollTimer.value) window.clearInterval(pollTimer.value);
  pollTimer.value = null;
}

async function refreshTask() {
  if (!task.value?.id) return;
  try {
    const response = await getImportTask(task.value.id);
    task.value = response?.task || task.value;
    if (task.value.stage === "analysis_completed") await loadAnalysisChangeSets();
    if (task.value.preview) setPreview(task.value.preview);
    if (task.value.status === "awaiting_confirmation" && !preview.value) {
      const result = await getImportTaskPreview(task.value.id);
      setPreview(result?.preview);
    }
    if (["awaiting_confirmation", "completed", "failed", "cancelled"].includes(task.value.status)) {
      stopPolling();
      await loadTaskList();
    }
  } catch (err) {
    error.value = err.message || t("无法刷新导入任务");
    stopPolling();
  }
}

async function loadAnalysisChangeSets() {
  const ids = task.value?.result?.pending_changeset_ids || [];
  const responses = await Promise.allSettled(ids.map((id) => getChangeSet(id)));
  analysisChangeSets.value = responses
    .filter((item) => item.status === "fulfilled")
    .map((item) => item.value);
}

async function confirmEntityChangeSet(changeSetId) {
  confirmingChangeSet.value = changeSetId;
  error.value = "";
  try {
    await confirmChangeSet(changeSetId);
    await loadAnalysisChangeSets();
  } catch (err) {
    error.value = err?.detail?.message || err.message || t("实体候选写入失败");
  } finally {
    confirmingChangeSet.value = "";
  }
}

function startPolling() {
  stopPolling();
  refreshTask();
  pollTimer.value = window.setInterval(refreshTask, 900);
}

function setPreview(value) {
  if (!value) return;
  preview.value = value;
  const list = ["chapters", "full_book"].includes(value.detected_mode) ? value.chapter_candidates || [] : value.entity_candidates || [];
  selectedIds.value = list.map((item) => item.candidate_id);
}

async function createTask() {
  if (!canCreate.value) return;
  const shouldAnalyze = autoAnalyze.value && ["chapters", "full_book"].includes(importMode.value);
  const shouldAttachAnalysisMode = needsAnalysisChoice.value && analysisMode.value;
  loading.value = true;
  error.value = "";
  preview.value = null;
  selectedIds.value = [];
  try {
    const response = await createImportTask({
      database_id: databaseId.value,
      book_id: bookId.value,
      text: sourceText.value,
      mode: importMode.value,
      source_format: sourceFormat.value,
      file_refs: [],
      options: {
        language: "auto",
        analyze_after_confirm: shouldAnalyze,
        ...(shouldAttachAnalysisMode ? { analysis_mode: analysisMode.value } : {}),
      },
    });
    task.value = response?.task;
    if (savedAnalysisMode.value === "ask" && analysisMode.value) {
      try {
        await updateAnalysisPreferences(analysisMode.value);
        savedAnalysisMode.value = analysisMode.value;
      } catch {
        // The import task is already valid; preference persistence is best-effort.
      }
    }
    router.replace({ query: { ...route.query, task: task.value?.id, source: importMode.value, database_id: databaseId.value, book_id: bookId.value } });
    startPolling();
  } catch (err) { error.value = err?.detail?.message || err.message || t("创建导入任务失败"); }
  finally { loading.value = false; }
}

async function resumeTask(item) {
  task.value = item;
  preview.value = null;
  selectedIds.value = [];
  databaseId.value = item.database_id;
  bookId.value = item.book_id;
  router.replace({ query: { task: item.id, source: item.detected_mode || item.requested_mode, database_id: item.database_id, book_id: item.book_id } });
  if (item.preview) setPreview(item.preview);
  if (["queued", "running"].includes(item.status)) startPolling();
  else await refreshTask();
}

async function cancelTask() {
  if (!task.value?.id) return;
  try { task.value = (await cancelImportTask(task.value.id))?.task || task.value; await refreshTask(); }
  catch (err) { error.value = err?.detail?.message || err.message || t("取消任务失败"); }
}

async function retryTask() {
  if (!task.value?.id) return;
  try {
    task.value = (await retryImportTask(task.value.id))?.task;
    preview.value = null;
    selectedIds.value = [];
    router.replace({ query: { ...route.query, task: task.value.id } });
    startPolling();
  } catch (err) { error.value = err?.detail?.message || err.message || t("重试任务失败"); }
}

async function confirmSelection() {
  if (!task.value?.id || !preview.value?.preview_hash || !selectedIds.value.length) return;
  confirming.value = true;
  error.value = "";
  const selected = candidates.value.filter((item) => selectedIds.value.includes(item.candidate_id));
  const payload = { preview_hash: preview.value.preview_hash, entity_selections: [], chapter_selections: [], relation_selections: [] };
  if (isChapterMode.value) {
    payload.chapter_selections = selected.map((item) => ({ candidate_id: item.candidate_id, title: item.title, content: item.content || "" }));
  } else {
    payload.entity_selections = selected.map((item) => ({ candidate_id: item.candidate_id, title: item.title, type: item.type || "concept", content: item.content || "", tags: item.tags || [], importance: item.importance || 3 }));
    payload.relation_selections = selectedRelationCandidates.value
      .map((item) => ({
        candidate_id: item.candidate_id,
        source: item.source,
        target: item.target,
        relation_type: item.relation_type || "related_to",
        description: item.description || "",
      }));
  }
  try {
    task.value = (await confirmImportTask(task.value.id, payload))?.task || task.value;
    if (["queued", "running"].includes(task.value?.status)) startPolling();
    await loadTaskList();
  } catch (err) { error.value = err?.detail?.message || err.message || t("确认导入失败"); }
  finally { confirming.value = false; }
}

onMounted(async () => {
  await Promise.all([loadContext(), loadAnalysisPreference()]);
  await loadTaskList();
  if (route.query.task) {
    try { await resumeTask((await getImportTask(String(route.query.task)))?.task); }
    catch (err) { error.value = err.message || t("无法恢复导入任务"); }
  }
});
onBeforeUnmount(stopPolling);
</script>

<template>
  <div class="page-shell import-page">
    <header class="page-header">
      <div><h1>{{ t("批量导入") }}</h1><p>{{ t("解析任务会持久化保存；只有经过选择并确认的候选项才会写入当前世界。") }}</p></div>
      <span class="status-pill">{{ taskStatusLabel }}</span>
    </header>

    <div v-if="!databaseId || !bookId" class="context-warning"><AlertTriangle :size="18" /><div><strong>{{ t("需要明确导入目标") }}</strong><span>{{ t("请先创建或选择世界与作品，再开始批量导入。") }}</span></div><button class="btn btn-primary" type="button" @click="router.push('/')">{{ t("返回首页创建世界") }}</button></div>
    <div v-if="error" class="error-notice"><AlertTriangle :size="16" />{{ error }}</div>

    <div class="import-layout">
      <section class="panel source-panel">
        <header class="panel-heading"><div><span>{{ t("步骤 1") }}</span><h2>{{ t("准备导入内容") }}</h2></div><strong>{{ t("{count} 字", { count: formatNumber(wordCount) }) }}</strong></header>
        <div class="mode-grid">
          <button v-for="item in modes" :key="item.key" type="button" :class="{ active: importMode === item.key }" :disabled="Boolean(task && !['failed','cancelled','completed'].includes(task.status))" @click="importMode = item.key">
            <component :is="item.icon" :size="18" /><span><strong>{{ t(item.label) }}</strong><small>{{ t(item.description) }}</small></span>
          </button>
        </div>
        <div class="target-row"><div><span>{{ t("目标世界库") }}</span><strong>{{ databaseId || t("未选择") }}</strong></div><div><span>{{ t("目标作品") }}</span><strong>{{ bookId || t("未选择") }}</strong></div><label><span>{{ t("文本格式") }}</span><select v-model="sourceFormat"><option value="auto">{{ t("自动识别") }}</option><option value="text">{{ t("纯文本") }}</option><option value="markdown">Markdown</option><option value="html">HTML</option></select></label></div>
        <textarea v-model="sourceText" rows="17" :disabled="Boolean(task && !['failed','cancelled','completed'].includes(task.status))" :placeholder="t('粘贴章节、整本作品或世界设定。章节标题会用于识别结构...')" />
        <label v-if="['chapters','full_book'].includes(importMode)" class="check-row"><input v-model="autoAnalyze" type="checkbox" />{{ t("导入章节后自动识别实体与关系") }}</label>
        <div v-if="needsAnalysisChoice" class="analysis-choice">
          <span>{{ t("本次实体分析方式") }}</span>
          <div role="group" :aria-label="t('本次实体分析方式')">
            <button type="button" :class="{ active: analysisMode === 'local_rules' }" @click="analysisMode = 'local_rules'">
              <strong>{{ t("本地规则") }}</strong><small>{{ t("完全离线，结果偏保守") }}</small>
            </button>
            <button type="button" :class="{ active: analysisMode === 'cloud_model' }" :disabled="!cloudModelAvailable" @click="analysisMode = 'cloud_model'">
              <strong>{{ t("云端模型") }}</strong><small>{{ t(cloudModelAvailable ? "提高识别准确性与归纳能力" : "需要先配置可用云端模型") }}</small>
            </button>
          </div>
          <small v-if="!analysisMode">{{ t("首次分析需要选择；选择会保存为默认值，可在 AI 设置中修改。") }}</small>
        </div>
        <button class="btn btn-primary primary-action" type="button" :disabled="!canCreate" @click="createTask"><Upload :size="16" />{{ t(loading ? "正在创建任务..." : "创建解析任务") }}</button>
      </section>

      <section class="panel task-panel">
        <header class="panel-heading"><div><span>{{ t("步骤 2") }}</span><h2>{{ t("任务进度与变更预览") }}</h2></div><button v-if="task" class="icon-button" type="button" :title="t('刷新任务')" @click="refreshTask"><RefreshCw :size="16" /></button></header>
        <div v-if="task" class="task-progress">
          <div class="task-status"><LoaderCircle v-if="['queued','running'].includes(task.status)" :size="20" class="spinning" /><CheckCircle2 v-else-if="task.status === 'completed'" :size="20" /><AlertTriangle v-else-if="['failed','cancelled'].includes(task.status)" :size="20" /><FileText v-else :size="20" /><div><strong>{{ taskStatusLabel }}</strong><span>{{ stageLabel }}</span></div><b>{{ Math.round((task.progress || 0) * 100) }}%</b></div>
          <div class="progress-track"><i :style="{ width: `${Math.round((task.progress || 0) * 100)}%` }"></i></div>
          <div class="task-actions"><button v-if="['queued','running'].includes(task.status)" class="btn btn-secondary" type="button" @click="cancelTask">{{ t("取消任务") }}</button><button v-if="['failed','cancelled'].includes(task.status)" class="btn btn-secondary" type="button" @click="retryTask"><RotateCcw :size="15" />{{ t("重新解析") }}</button></div>
        </div>
        <div v-else class="empty-state"><Upload :size="28" /><strong>{{ t("尚未创建导入任务") }}</strong><small>{{ t("任务创建后，即使离开页面也可以从最近任务中继续。") }}</small></div>

        <template v-if="preview">
          <div class="changeset-grid"><article v-for="group in displayedChangeSetGroups" :key="group.key" :class="{ alert: ['conflicts','warnings'].includes(group.key) }"><strong>{{ group.count }}</strong><span>{{ t(group.label) }}</span></article></div>
          <div v-if="preview.warnings?.length" class="warning-list"><div v-for="warning in preview.warnings" :key="warning"><AlertTriangle :size="15" />{{ warning }}</div></div>
          <div class="candidate-list">
            <label v-for="candidate in candidates" :key="candidate.candidate_id" class="candidate-card">
              <input v-model="selectedIds" type="checkbox" :value="candidate.candidate_id" />
              <span><strong>{{ candidate.title }}</strong><small v-if="isChapterMode">{{ t("章节草稿") }} · {{ t("{count} 字", { count: formatNumber(candidate.word_count || candidate.content?.length) }) }}</small><small v-else>{{ t(ENTITY_TYPE_LABELS[candidate.type] || candidate.type || "概念") }} · {{ t("重要度 {value}", { value: candidate.importance || 3 }) }}</small></span>
            </label>
            <div v-if="!candidates.length" class="small-empty">{{ t("预览中没有可确认的候选项") }}</div>
          </div>
          <div v-if="!isChapterMode && relationCandidates.length" class="relation-preview">
            <header>
              <strong>{{ t("关系候选预览") }}</strong>
              <span>{{ t("将写入 {count} / {total} 条", { count: selectedRelationCandidates.length, total: relationCandidates.length }) }}</span>
            </header>
            <div v-if="visibleRelationCandidates.length" class="relation-list">
              <article v-for="relation in visibleRelationCandidates" :key="relation.candidate_id">
                <strong>{{ relationLabel(relation) }}</strong>
                <small v-if="relation.description">{{ relation.description }}</small>
              </article>
            </div>
            <div v-else class="small-empty compact">{{ t("选择关系两端的实体后，关系会随确认一起写入。") }}</div>
          </div>
          <div v-if="analysisChangeSets.length" class="analysis-results">
            <header><strong>{{ t("实体识别结果") }}</strong><span>{{ t("确认后才会写入实体与关系") }}</span></header>
            <article v-for="item in analysisChangeSets" :key="item.changeset_id">
              <div><strong>{{ t("{entities} 个实体 · {relations} 条关系", { entities: item.entities?.length || 0, relations: item.relations?.length || 0 }) }}</strong><small>{{ item.source_chapter_id }}</small></div>
              <span class="state-badge" :class="{ positive: item.status === 'confirmed' }">{{ t(item.status === 'confirmed' ? '已写入' : '待确认') }}</span>
              <button v-if="item.status === 'pending'" class="btn btn-primary compact" type="button" :disabled="Boolean(confirmingChangeSet)" @click="confirmEntityChangeSet(item.changeset_id)">{{ t(confirmingChangeSet === item.changeset_id ? '写入中...' : '确认实体') }}</button>
            </article>
          </div>
        </template>
      </section>

      <aside class="side-column">
        <section class="panel confirm-panel"><span>{{ t("步骤 3") }}</span><h2>{{ t("确认写入") }}</h2><div class="selection-count"><strong>{{ selectedIds.length }}</strong><span>{{ t("已选择候选项") }}</span></div><button class="btn btn-primary" type="button" :disabled="task?.status !== 'awaiting_confirmation' || !selectedIds.length || confirming" @click="confirmSelection">{{ t(confirming ? "正在写入..." : "确认并写入") }}</button><p>{{ t("AI 不会直接写数据库。预览哈希与候选选择都会由后端再次校验。") }}</p><div v-if="task?.status === 'completed'" class="completed-box"><CheckCircle2 :size="20" /><div><strong>{{ t("导入完成") }}</strong><span>{{ t("可返回首页继续创作或检查设定。") }}</span></div></div></section>
        <section class="panel recent-tasks"><header><h2>{{ t("最近任务") }}</h2><button class="icon-button" type="button" :title="t('刷新任务列表')" @click="loadTaskList"><RefreshCw :size="15" /></button></header><button v-for="item in tasks" :key="item.id" type="button" :class="{ active: item.id === task?.id }" @click="resumeTask(item)"><span><strong>{{ item.detected_mode || item.requested_mode }}</strong><small>{{ item.created_at || item.id.slice(-8) }}</small></span><em>{{ recentTaskStatus(item.status) }}</em></button><div v-if="!tasks.length" class="small-empty">{{ t("暂无导入任务") }}</div></section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.import-page { max-width: 1600px; margin: 0 auto; }
.context-warning { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 11px; align-items: center; margin-bottom: 14px; border: 1px solid #f0d6ac; border-radius: 8px; background: #fff8ed; color: #8f5b17; padding: 12px; }
.context-warning div { display: grid; gap: 3px; }
.context-warning span { font-size: 11px; }
.error-notice { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; border-radius: 8px; background: #fff0f0; color: #a33f3f; padding: 10px 12px; font-size: 12px; }
.import-layout { display: grid; grid-template-columns: minmax(330px,.9fr) minmax(420px,1.15fr) 270px; gap: 14px; align-items: start; }
.source-panel, .task-panel, .side-column, .confirm-panel, .recent-tasks { display: grid; gap: 13px; min-width: 0; }
.side-column { position: sticky; top: 18px; }
.panel-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.panel-heading div { display: grid; gap: 3px; }
.panel-heading span, .confirm-panel > span { color: var(--accent); font-size: 10px; }
.panel-heading h2, .confirm-panel h2, .recent-tasks h2 { font-size: 15px; }
.panel-heading > strong { color: var(--text-secondary); font-size: 11px; }
.mode-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 7px; }
.mode-grid button { min-height: 64px; display: grid; grid-template-columns: auto minmax(0,1fr); gap: 8px; align-items: start; border: 1px solid var(--border); border-radius: 8px; background: #fff; color: var(--text-secondary); cursor: pointer; text-align: left; padding: 9px; }
.mode-grid button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.mode-grid button:disabled { cursor: not-allowed; opacity: .62; }
.mode-grid span { display: grid; gap: 3px; }
.mode-grid strong { color: var(--text-primary); font-size: 11px; }
.mode-grid small { color: var(--text-secondary); font-size: 9px; line-height: 1.45; }
.target-row { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 7px; }
.target-row > div, .target-row label { display: grid; gap: 4px; min-width: 0; border-radius: 8px; background: var(--bg-secondary); padding: 8px; }
.target-row span { color: var(--text-muted); font-size: 9px; }
.target-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.target-row select { padding: 3px; font-size: 10px; }
.analysis-choice { display: grid; gap: 7px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-secondary); padding: 9px; }
.analysis-choice > span { color: var(--text-secondary); font-size: 10px; font-weight: 600; }
.analysis-choice > div { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 7px; }
.analysis-choice button { min-height: 48px; display: grid; gap: 2px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-primary); cursor: pointer; text-align: left; padding: 8px; }
.analysis-choice button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.analysis-choice button:disabled { cursor: not-allowed; opacity: .58; }
.analysis-choice strong { font-size: 10px; }
.analysis-choice small { color: var(--text-secondary); font-size: 9px; line-height: 1.45; }
.analysis-choice > small { color: #8f5b17; }
.primary-action { width: 100%; }
.task-progress { display: grid; gap: 9px; border-radius: 8px; background: var(--bg-secondary); padding: 12px; }
.task-status { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 9px; align-items: center; }
.task-status > div { display: grid; gap: 2px; }
.task-status strong { font-size: 12px; }
.task-status span { color: var(--text-secondary); font-size: 10px; }
.task-status b { font-size: 13px; }
.progress-track { height: 7px; overflow: hidden; border-radius: 999px; background: #e4e0ec; }
.progress-track i { display: block; height: 100%; background: var(--accent); transition: width .25s ease; }
.task-actions { display: flex; justify-content: flex-end; gap: 7px; }
.changeset-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 6px; }
.changeset-grid article { display: grid; gap: 2px; border-radius: 7px; background: var(--bg-secondary); padding: 8px; }
.changeset-grid strong { color: var(--accent); font-size: 17px; }
.changeset-grid span { color: var(--text-secondary); font-size: 9px; }
.changeset-grid article.alert strong { color: #a2671a; }
.warning-list { display: grid; gap: 5px; }
.warning-list div { display: flex; align-items: flex-start; gap: 6px; border-radius: 7px; background: #fff8ed; color: #8f5b17; padding: 8px; font-size: 10px; line-height: 1.5; }
.candidate-list { display: grid; gap: 7px; max-height: 470px; overflow-y: auto; padding-right: 2px; }
.candidate-card { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 9px; align-items: start; border: 1px solid var(--border); border-radius: 8px; background: #fff; padding: 9px; cursor: pointer; }
.candidate-card input { width: auto; margin-top: 2px; }
.candidate-card span { display: grid; gap: 3px; min-width: 0; }
.candidate-card strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.candidate-card small { color: var(--text-secondary); font-size: 9px; }
.relation-preview { display: grid; gap: 8px; border-top: 1px solid var(--border); padding-top: 12px; }
.relation-preview > header { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
.relation-preview > header strong { font-size: 12px; }
.relation-preview > header span { color: var(--text-secondary); font-size: 9px; }
.relation-list { display: grid; gap: 6px; max-height: 190px; overflow-y: auto; }
.relation-list article { display: grid; gap: 3px; border: 1px solid var(--border); border-radius: 7px; background: #fff; padding: 8px; }
.relation-list strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-primary); font-size: 10px; }
.relation-list small { color: var(--text-secondary); font-size: 9px; line-height: 1.45; }
.analysis-results { display: grid; gap: 7px; border-top: 1px solid var(--border); padding-top: 12px; }
.analysis-results > header, .analysis-results > article { display: flex; gap: 9px; align-items: center; justify-content: space-between; }
.analysis-results > header span, .analysis-results small { color: var(--text-secondary); font-size: 9px; }
.analysis-results > article { border: 1px solid var(--border); border-radius: 8px; padding: 9px; }
.analysis-results > article > div { display: grid; gap: 3px; min-width: 0; }
.selection-count { display: grid; place-items: center; min-height: 75px; border-radius: 8px; background: var(--accent-soft); color: var(--accent); }
.selection-count strong { font-size: 25px; }
.selection-count span { font-size: 10px; }
.confirm-panel p { color: var(--text-secondary); font-size: 10px; line-height: 1.6; }
.completed-box { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 8px; align-items: center; border-radius: 8px; background: #eaf8f2; color: #167251; padding: 10px; }
.completed-box div { display: grid; gap: 2px; }
.completed-box strong { font-size: 11px; }
.completed-box span { font-size: 9px; }
.recent-tasks header { display: flex; justify-content: space-between; align-items: center; }
.recent-tasks > button:not(.icon-button) { display: flex; justify-content: space-between; gap: 8px; align-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; cursor: pointer; text-align: left; padding: 8px; }
.recent-tasks > button.active { border-color: var(--accent); background: var(--accent-soft); }
.recent-tasks button span { display: grid; gap: 2px; min-width: 0; }
.recent-tasks button strong { font-size: 10px; }
.recent-tasks button small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 8px; }
.recent-tasks em { color: var(--text-secondary); font-size: 9px; font-style: normal; }
.icon-button { width: 32px; height: 32px; display: inline-grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.small-empty { min-height: 72px; display: grid; place-items: center; border: 1px dashed var(--border); border-radius: 8px; color: var(--text-muted); font-size: 10px; }
.small-empty.compact { min-height: 46px; padding: 8px; text-align: center; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1450px) { .import-layout { grid-template-columns: minmax(300px,.9fr) minmax(380px,1.1fr); } .side-column { position: static; grid-column: 1 / -1; grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 850px) { .import-layout, .side-column { grid-template-columns: 1fr; } .side-column { grid-column: auto; } .context-warning { grid-template-columns: auto minmax(0,1fr); } .context-warning .btn { grid-column: 1 / -1; } }
@media (max-width: 540px) { .mode-grid, .target-row, .changeset-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
