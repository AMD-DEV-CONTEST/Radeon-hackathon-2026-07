<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ListRestart,
  RefreshCw,
  RotateCcw,
  Square,
} from "@lucide/vue";
import {
  cancelVectorTask,
  getVectorIndexStatus,
  getVectorTask,
  listVectorTasks,
  rebuildVectorIndex,
  retryFailedVectorItems,
} from "../api/vectorIndex.js";
import {
  canRetryVectorTask,
  isActiveVectorTask,
  vectorTaskKindLabel,
  vectorTaskProgress,
  vectorTaskStatusLabel,
} from "../domain/vectorTasks.js";
import { useAppStore } from "../stores/app.js";
import { useAiManagementStore } from "../stores/aiManagement.js";

const appStore = useAppStore();
const aiStore = useAiManagementStore();
const { locale, t } = useI18n();

const scope = ref("book");
const scopeTouched = ref(false);
const indexStatus = ref(null);
const tasks = ref([]);
const selectedTask = ref(null);
const loading = ref(false);
const action = ref("");
const errorMessage = ref("");
const successMessage = ref("");
let pollTimer = null;

const databaseId = computed(() => appStore.activeDatabase?.database_id || "");
const activeBookId = computed(() => appStore.activeBook?.book_id || "");
const scopedBookId = computed(() => scope.value === "book" ? activeBookId.value : "");
const canManage = computed(() => appStore.hasCapability("manage_system"));
const runtime = computed(() => aiStore.hardwareAcceleration?.runtime || {});
const hasActiveTasks = computed(() => tasks.value.some(isActiveVectorTask));
const indexHealthy = computed(() => (
  runtime.value.available
  && indexStatus.value
  && !indexStatus.value.rebuild_required
  && Number(indexStatus.value.chunk_count || 0) === Number(indexStatus.value.vector_count || 0)
));
const failedItems = computed(() => (
  (selectedTask.value?.items || []).filter((item) => item.status === "failed").slice(0, 20)
));

function safeMessage(error, fallback) {
  return error?.detail?.message || error?.message || t(fallback);
}

function statusTone(status) {
  if (status === "completed") return "positive";
  if (status === "running") return "active";
  if (status === "queued") return "neutral";
  if (status === "partial_failed") return "warning";
  if (status === "failed") return "danger";
  return "muted";
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

function selectScope(value) {
  scopeTouched.value = true;
  scope.value = value;
}

async function refreshData({ silent = false } = {}) {
  if (!databaseId.value) {
    indexStatus.value = null;
    tasks.value = [];
    selectedTask.value = null;
    return;
  }
  if (!silent) loading.value = true;
  errorMessage.value = "";
  const [statusResult, tasksResult] = await Promise.allSettled([
    getVectorIndexStatus(databaseId.value),
    listVectorTasks({ database_id: databaseId.value, limit: 50 }),
  ]);
  if (statusResult.status === "fulfilled") indexStatus.value = statusResult.value;
  else indexStatus.value = null;
  if (tasksResult.status === "fulfilled") tasks.value = tasksResult.value?.tasks || [];
  else errorMessage.value = safeMessage(tasksResult.reason, "向量任务加载失败");

  if (selectedTask.value?.id) {
    const latest = tasks.value.find((task) => task.id === selectedTask.value.id);
    if (latest) {
      try {
        selectedTask.value = await getVectorTask(latest.id);
      } catch (error) {
        if (!silent) errorMessage.value = safeMessage(error, "向量任务详情加载失败");
      }
    }
  }
  if (statusResult.status === "rejected" && !errorMessage.value) {
    errorMessage.value = safeMessage(statusResult.reason, "向量索引状态加载失败");
  }
  loading.value = false;
}

async function startRebuild() {
  if (!databaseId.value || !canManage.value) return;
  action.value = "rebuild";
  errorMessage.value = "";
  successMessage.value = "";
  try {
    const created = await rebuildVectorIndex(databaseId.value, scopedBookId.value || null);
    selectedTask.value = created;
    successMessage.value = t("向量重建任务已创建");
    await refreshData({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "向量重建任务创建失败");
  } finally {
    action.value = "";
  }
}

async function openTask(task) {
  action.value = `detail:${task.id}`;
  errorMessage.value = "";
  try {
    selectedTask.value = await getVectorTask(task.id);
  } catch (error) {
    errorMessage.value = safeMessage(error, "向量任务详情加载失败");
  } finally {
    action.value = "";
  }
}

async function cancelTask(task) {
  action.value = `cancel:${task.id}`;
  errorMessage.value = "";
  try {
    selectedTask.value = await cancelVectorTask(task.id);
    successMessage.value = t("取消请求已提交");
    await refreshData({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "向量任务取消失败");
  } finally {
    action.value = "";
  }
}

async function retryTask(task) {
  action.value = `retry:${task.id}`;
  errorMessage.value = "";
  try {
    selectedTask.value = await retryFailedVectorItems(task.id);
    successMessage.value = t("失败项重试任务已创建");
    await refreshData({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "失败项重试创建失败");
  } finally {
    action.value = "";
  }
}

watch(databaseId, () => refreshData(), { immediate: true });
watch(activeBookId, (bookId) => {
  if (!bookId && scope.value === "book") scope.value = "database";
  else if (bookId && !scopeTouched.value) scope.value = "book";
}, { immediate: true });

onMounted(() => {
  pollTimer = window.setInterval(() => {
    if (hasActiveTasks.value && document.visibilityState === "visible") {
      refreshData({ silent: true });
    }
  }, 2500);
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<template>
  <section class="vector-section">
    <header class="vector-heading">
      <div class="heading-title">
        <span class="heading-icon"><Database :size="20" /></span>
        <div>
          <h2>{{ t("本地向量索引") }}</h2>
          <p>BAAI/bge-m3 · {{ t("AetherDB 本地运行时") }}</p>
        </div>
      </div>
      <div class="heading-actions">
        <span class="index-state" :class="indexHealthy ? 'positive' : 'warning'">
          <CheckCircle2 v-if="indexHealthy" :size="14" />
          <AlertTriangle v-else :size="14" />
          {{ t(indexHealthy ? "索引一致" : "需要检查") }}
        </span>
        <button
          class="icon-button"
          type="button"
          :title="t('刷新向量状态')"
          :disabled="loading"
          @click="refreshData()"
        >
          <RefreshCw :size="16" :class="{ spinning: loading }" />
        </button>
      </div>
    </header>

    <div v-if="!databaseId" class="vector-empty">
      <Database :size="22" />
      <span>{{ t("请先选择世界库") }}</span>
    </div>

    <template v-else>
      <div class="vector-metrics">
        <div><small>{{ t("文本分块") }}</small><strong>{{ indexStatus?.chunk_count ?? "—" }}</strong></div>
        <div><small>{{ t("向量记录") }}</small><strong>{{ indexStatus?.vector_count ?? "—" }}</strong></div>
        <div><small>{{ t("旧格式记录") }}</small><strong>{{ indexStatus?.legacy_embedding_count ?? "—" }}</strong></div>
        <div><small>{{ t("执行后端") }}</small><strong>{{ runtime.execution_provider || (runtime.available ? t("任务启动后确定") : t("未初始化")) }}</strong></div>
      </div>

      <div class="vector-toolbar">
        <div class="segmented-control" role="group" :aria-label="t('重建范围')">
          <button
            type="button"
            :class="{ active: scope === 'database' }"
            @click="selectScope('database')"
          >{{ t("当前世界库") }}</button>
          <button
            type="button"
            :class="{ active: scope === 'book' }"
            :disabled="!activeBookId"
            @click="selectScope('book')"
          >{{ t("当前作品") }}</button>
        </div>
        <button
          class="primary-action"
          type="button"
          :disabled="!canManage || !runtime.available || action === 'rebuild'"
          @click="startRebuild"
        >
          <ListRestart :size="16" />
          {{ t(action === "rebuild" ? "正在创建任务" : "重建向量索引") }}
        </button>
      </div>

      <p v-if="!runtime.available" class="runtime-warning">
        <AlertTriangle :size="14" />{{ t("BGE-M3 本地运行时不可用，无法开始新的向量任务。") }}
      </p>
      <p v-else-if="runtime.execution_provider === 'CPUExecutionProvider'" class="runtime-note">
        {{ t("当前使用 CPU；ROCm 与 CUDA 可在兼容环境中加速批量向量生成。") }}
      </p>
      <p v-if="!canManage" class="runtime-warning">
        <AlertTriangle :size="14" />{{ t("当前账户无权管理向量任务") }}
      </p>
      <p v-if="errorMessage" class="feedback danger"><AlertTriangle :size="14" />{{ errorMessage }}</p>
      <p v-if="successMessage" class="feedback positive"><CheckCircle2 :size="14" />{{ successMessage }}</p>

      <div class="task-layout">
        <div class="task-list" :aria-label="t('向量任务')">
          <button
            v-for="task in tasks"
            :key="task.id"
            class="task-row"
            :class="{ selected: selectedTask?.id === task.id }"
            type="button"
            @click="openTask(task)"
          >
            <span class="task-main">
              <strong>{{ t(vectorTaskKindLabel(task.task_kind)) }}</strong>
              <small>{{ formatTime(task.created_at) }} · {{ task.effective_backend || task.requested_backend }}</small>
            </span>
            <span class="task-progress">
              <span><i :style="{ width: `${vectorTaskProgress(task)}%` }"></i></span>
              <small>{{ task.processed_items || 0 }} / {{ task.total_items || 0 }}</small>
            </span>
            <span class="task-status" :class="statusTone(task.status)">
              {{ t(vectorTaskStatusLabel(task.status)) }}
            </span>
          </button>
          <div v-if="!tasks.length && !loading" class="task-empty">{{ t("尚无向量任务") }}</div>
        </div>

        <aside v-if="selectedTask" class="task-detail">
          <header>
            <div>
              <small>{{ t("任务详情") }}</small>
              <strong>{{ t(vectorTaskKindLabel(selectedTask.task_kind)) }}</strong>
            </div>
            <span class="task-status" :class="statusTone(selectedTask.status)">
              {{ t(vectorTaskStatusLabel(selectedTask.status)) }}
            </span>
          </header>
          <dl>
            <div><dt>{{ t("处理进度") }}</dt><dd>{{ selectedTask.processed_items || 0 }} / {{ selectedTask.total_items || 0 }}</dd></div>
            <div><dt>{{ t("成功") }}</dt><dd>{{ selectedTask.successful_items || 0 }}</dd></div>
            <div><dt>{{ t("失败") }}</dt><dd>{{ selectedTask.failed_items || 0 }}</dd></div>
            <div><dt>{{ t("跳过") }}</dt><dd>{{ selectedTask.skipped_items || 0 }}</dd></div>
            <div><dt>{{ t("模型") }}</dt><dd>{{ selectedTask.model_id || "BAAI/bge-m3" }}</dd></div>
            <div><dt>{{ t("执行后端") }}</dt><dd>{{ selectedTask.effective_backend || selectedTask.requested_backend }}</dd></div>
          </dl>
          <p v-if="selectedTask.backend_fallback_detected" class="runtime-warning">
            <AlertTriangle :size="14" />{{ t("检测到 GPU 回退，任务实际使用了其他执行后端。") }}
          </p>
          <p v-if="selectedTask.error_code" class="task-error">
            <strong>{{ selectedTask.error_code }}</strong>
            <span>{{ selectedTask.error_message }}</span>
          </p>
          <div v-if="failedItems.length" class="failed-items">
            <small>{{ t("失败项") }}</small>
            <span v-for="item in failedItems" :key="`${item.entity_id}:${item.operation}`">
              {{ item.entity_id }} · {{ item.error_code || t("未知错误") }}
            </span>
          </div>
          <div class="detail-actions">
            <button
              v-if="isActiveVectorTask(selectedTask)"
              class="secondary-action danger"
              type="button"
              :disabled="action === `cancel:${selectedTask.id}`"
              @click="cancelTask(selectedTask)"
            >
              <Square :size="14" />{{ t("取消任务") }}
            </button>
            <button
              v-if="canRetryVectorTask(selectedTask)"
              class="secondary-action"
              type="button"
              :disabled="action === `retry:${selectedTask.id}`"
              @click="retryTask(selectedTask)"
            >
              <RotateCcw :size="14" />{{ t("仅重试失败项") }}
            </button>
          </div>
        </aside>
      </div>
    </template>
  </section>
</template>

<style scoped>
.vector-section { display: grid; gap: 14px; border: 1px solid var(--border); border-left: 4px solid #397d6d; border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); padding: 17px; }
.vector-heading, .heading-title, .heading-actions, .index-state, .vector-toolbar, .runtime-warning, .feedback, .detail-actions { display: flex; align-items: center; }
.vector-heading { justify-content: space-between; gap: 16px; }
.heading-title { gap: 11px; min-width: 0; }
.heading-icon { width: 38px; height: 38px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: #e7f3ef; color: #236d5d; }
.heading-title h2 { margin: 0 0 4px; font-size: 16px; }
.heading-title p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.heading-actions { gap: 8px; }
.index-state { gap: 6px; border-radius: 999px; padding: 6px 10px; font-size: 11px; font-weight: 700; }
.index-state.positive { background: #e7f8f0; color: #15704f; }
.index-state.warning { background: #fff6e5; color: #95651b; }
.icon-button { width: 34px; height: 34px; display: inline-grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.vector-empty, .task-empty { min-height: 76px; display: grid; place-items: center; align-content: center; gap: 7px; color: var(--text-muted); font-size: 12px; }
.vector-metrics { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 8px; }
.vector-metrics div { min-width: 0; display: grid; gap: 5px; border-radius: 7px; background: var(--bg-secondary); padding: 11px; }
.vector-metrics small { color: var(--text-muted); font-size: 10px; }
.vector-metrics strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.vector-toolbar { justify-content: space-between; gap: 12px; }
.segmented-control { display: inline-grid; grid-template-columns: repeat(2,minmax(0,1fr)); border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.segmented-control button { min-height: 34px; border: 0; border-right: 1px solid var(--border); background: #fff; color: var(--text-secondary); padding: 6px 12px; cursor: pointer; font-size: 12px; }
.segmented-control button:last-child { border-right: 0; }
.segmented-control button.active { background: #e7f3ef; color: #236d5d; font-weight: 700; }
.segmented-control button:disabled { opacity: .45; cursor: not-allowed; }
.primary-action, .secondary-action { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 34px; border-radius: 7px; padding: 7px 12px; cursor: pointer; font-size: 12px; font-weight: 700; }
.primary-action { border: 1px solid #236d5d; background: #236d5d; color: #fff; }
.secondary-action { border: 1px solid var(--border); background: #fff; color: var(--text-secondary); }
.secondary-action.danger { color: #a33f3f; }
.primary-action:disabled, .secondary-action:disabled, .icon-button:disabled { opacity: .5; cursor: not-allowed; }
.runtime-warning, .runtime-note, .feedback { gap: 7px; margin: 0; border-radius: 7px; padding: 9px 11px; font-size: 11px; }
.runtime-warning, .feedback.danger { background: #fff6e5; color: #8c621f; }
.runtime-note { background: #eef4f8; color: #486271; }
.feedback.positive { background: #edf9f3; color: #167251; }
.task-layout { display: grid; grid-template-columns: minmax(0,1.45fr) minmax(260px,.8fr); gap: 12px; align-items: start; }
.task-list { min-width: 0; display: grid; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.task-row { width: 100%; min-height: 58px; display: grid; grid-template-columns: minmax(0,1fr) minmax(120px,.55fr) auto; align-items: center; gap: 12px; border: 0; border-bottom: 1px solid var(--border); background: #fff; padding: 10px 12px; color: inherit; text-align: left; cursor: pointer; }
.task-row:last-child { border-bottom: 0; }
.task-row:hover, .task-row.selected { background: #f5faf8; }
.task-main, .task-progress { min-width: 0; display: grid; gap: 5px; }
.task-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.task-main small, .task-progress small { color: var(--text-muted); font-size: 10px; }
.task-progress > span { height: 5px; overflow: hidden; border-radius: 999px; background: #e5e8e7; }
.task-progress i { display: block; height: 100%; border-radius: inherit; background: #397d6d; }
.task-status { width: max-content; max-width: 100%; border-radius: 999px; padding: 4px 8px; font-size: 10px; font-weight: 700; white-space: nowrap; }
.task-status.positive { background: #e7f8f0; color: #15704f; }
.task-status.active { background: #e8f0fa; color: #326398; }
.task-status.warning { background: #fff6e5; color: #95651b; }
.task-status.danger { background: #fff0f0; color: #a33f3f; }
.task-status.neutral, .task-status.muted { background: #f0eef4; color: var(--text-secondary); }
.task-detail { min-width: 0; display: grid; gap: 11px; border-left: 1px solid var(--border); padding-left: 13px; }
.task-detail header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.task-detail header div { min-width: 0; display: grid; gap: 3px; }
.task-detail header small, .failed-items > small { color: var(--text-muted); font-size: 10px; }
.task-detail header strong { font-size: 13px; }
.task-detail dl { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 7px; margin: 0; }
.task-detail dl div { min-width: 0; display: grid; gap: 3px; background: var(--bg-secondary); border-radius: 6px; padding: 8px; }
.task-detail dt { color: var(--text-muted); font-size: 9px; }
.task-detail dd { overflow: hidden; margin: 0; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.task-error, .failed-items { display: grid; gap: 4px; margin: 0; border-radius: 7px; background: #fff0f0; color: #a33f3f; padding: 9px; font-size: 10px; }
.failed-items span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-actions { gap: 8px; flex-wrap: wrap; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) {
  .vector-heading, .vector-toolbar { align-items: flex-start; flex-direction: column; }
  .heading-actions, .vector-toolbar, .segmented-control { width: 100%; }
  .heading-actions { justify-content: space-between; }
  .primary-action { width: 100%; }
  .task-layout { grid-template-columns: 1fr; }
  .task-detail { border-top: 1px solid var(--border); border-left: 0; padding-top: 13px; padding-left: 0; }
}
@media (max-width: 620px) {
  .vector-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .task-row { grid-template-columns: minmax(0,1fr) auto; }
  .task-progress { grid-column: 1 / -1; }
}
</style>
