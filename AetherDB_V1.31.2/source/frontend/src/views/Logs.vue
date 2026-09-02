<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { AlertTriangle, Clipboard, FileText, RefreshCw } from "@lucide/vue";
import { getLogStats, getLogs } from "../api/logs.js";

const { t } = useI18n();
const logType = ref("app");
const level = ref("");
const keyword = ref("");
const lineLimit = ref(200);
const lines = ref([]);
const stats = ref({});
const loading = ref(false);
const copying = ref(false);
const copied = ref(false);
const error = ref("");

const logTypes = [
  { key: "app", label: "应用日志", file: "app.log" },
  { key: "error", label: "错误日志", file: "error.log" },
  { key: "access", label: "访问日志", file: "access.log" },
];
const levels = [
  { key: "", label: "全部等级" },
  { key: "ERROR", label: "ERROR" },
  { key: "WARNING", label: "WARNING" },
  { key: "INFO", label: "INFO" },
  { key: "DEBUG", label: "DEBUG" },
];

const activeLog = computed(() => logTypes.find((item) => item.key === logType.value) || logTypes[0]);
const logText = computed(() => lines.value.join("\n"));
const activeStats = computed(() => stats.value?.[activeLog.value.file] || {});

async function loadLogs() {
  loading.value = true;
  error.value = "";
  copied.value = false;
  try {
    const [logResponse, statsResponse] = await Promise.all([
      getLogs({
        log_type: logType.value,
        lines: lineLimit.value,
        level: level.value,
        keyword: keyword.value.trim(),
      }),
      getLogStats(),
    ]);
    lines.value = logResponse?.lines || [];
    stats.value = statsResponse?.items || {};
  } catch (err) {
    lines.value = [];
    error.value = err?.message || t("无法读取日志");
  } finally {
    loading.value = false;
  }
}

async function copyLogs() {
  if (!logText.value || copying.value) return;
  copying.value = true;
  copied.value = false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(logText.value);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = logText.value;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    copied.value = true;
    window.setTimeout(() => { copied.value = false; }, 1800);
  } catch (err) {
    error.value = err?.message || t("复制失败");
  } finally {
    copying.value = false;
  }
}

function switchLogType(value) {
  logType.value = value;
  loadLogs();
}

onMounted(loadLogs);
</script>

<template>
  <div class="page-shell logs-page">
    <header class="page-header">
      <div>
        <h1>{{ t("日志") }}</h1>
        <p>{{ t("用于测试反馈和现场排错的只读日志视图。日志内容会在后端返回前再次脱敏。") }}</p>
      </div>
      <span class="status-pill">{{ activeLog.file }}</span>
    </header>

    <div v-if="error" class="error-notice">
      <AlertTriangle :size="16" />
      <span>{{ error }}</span>
    </div>

    <section class="log-toolbar">
      <div class="log-tabs" role="tablist" :aria-label="t('日志类型')">
        <button
          v-for="item in logTypes"
          :key="item.key"
          type="button"
          :class="{ active: item.key === logType }"
          @click="switchLogType(item.key)"
        >
          <FileText :size="15" />
          <span>{{ t(item.label) }}</span>
        </button>
      </div>
      <label>
        <span>{{ t("等级") }}</span>
        <select v-model="level" @change="loadLogs">
          <option v-for="item in levels" :key="item.key" :value="item.key">{{ item.label }}</option>
        </select>
      </label>
      <label>
        <span>{{ t("行数") }}</span>
        <select v-model.number="lineLimit" @change="loadLogs">
          <option :value="100">100</option>
          <option :value="200">200</option>
          <option :value="500">500</option>
          <option :value="1000">1000</option>
        </select>
      </label>
      <label class="keyword-field">
        <span>{{ t("关键词") }}</span>
        <input v-model="keyword" maxlength="120" :placeholder="t('错误码、任务 ID 或接口路径')" @keydown.enter="loadLogs" />
      </label>
      <button class="btn btn-secondary" type="button" :disabled="loading" @click="loadLogs">
        <RefreshCw :size="15" :class="{ spinning: loading }" />
        {{ t("刷新") }}
      </button>
      <button class="btn btn-primary" type="button" :disabled="!logText || copying" @click="copyLogs">
        <Clipboard :size="15" />
        {{ t(copied ? "已复制" : "复制日志") }}
      </button>
    </section>

    <section class="log-summary">
      <article><span>{{ t("文件大小") }}</span><strong>{{ activeStats.size_human || "0 B" }}</strong></article>
      <article><span>{{ t("总行数") }}</span><strong>{{ activeStats.lines || 0 }}</strong></article>
      <article><span>{{ t("当前显示") }}</span><strong>{{ lines.length }}</strong></article>
      <article><span>{{ t("筛选") }}</span><strong>{{ level || keyword.trim() ? t("已启用") : t("未启用") }}</strong></article>
    </section>

    <section class="log-viewer" aria-live="polite">
      <pre v-if="lines.length">{{ logText }}</pre>
      <div v-else class="empty-state">
        <FileText :size="28" />
        <strong>{{ t(loading ? "正在读取日志" : "暂无日志内容") }}</strong>
        <small>{{ t("可以切换日志类型，或调整行数和关键词后刷新。") }}</small>
      </div>
    </section>
  </div>
</template>

<style scoped>
.logs-page { max-width: 1500px; margin: 0 auto; }
.error-notice { display: flex; gap: 8px; align-items: center; margin-bottom: 14px; border-radius: 8px; background: #fff0f0; color: #a33f3f; padding: 10px 12px; font-size: 12px; }
.log-toolbar { display: grid; grid-template-columns: minmax(260px,1fr) 110px 95px minmax(180px,.8fr) auto auto; gap: 8px; align-items: end; margin-bottom: 12px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); padding: 10px; box-shadow: var(--soft-shadow); }
.log-tabs { min-width: 0; display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 5px; }
.log-tabs button { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; font-size: 10px; }
.log-tabs button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.log-toolbar label { min-width: 0; display: grid; gap: 4px; }
.log-toolbar label span { color: var(--text-muted); font-size: 9px; }
.log-toolbar select, .log-toolbar input { width: 100%; min-height: 34px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-primary); padding: 5px 7px; font: inherit; font-size: 11px; }
.log-summary { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 8px; margin-bottom: 12px; }
.log-summary article { display: grid; gap: 3px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-secondary); padding: 10px; }
.log-summary span { color: var(--text-muted); font-size: 9px; }
.log-summary strong { color: var(--text-primary); font-size: 14px; }
.log-viewer { min-height: 560px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: #181722; box-shadow: var(--soft-shadow); }
.log-viewer pre { max-height: calc(100vh - 280px); min-height: 560px; overflow: auto; margin: 0; color: #eeedf7; padding: 14px; font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: 11px; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.empty-state { min-height: 560px; display: grid; place-items: center; align-content: center; gap: 8px; color: #bdb8d0; text-align: center; }
.empty-state strong { color: #eeedf7; font-size: 13px; }
.empty-state small { font-size: 10px; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) { .log-toolbar { grid-template-columns: 1fr 1fr 1fr; } .log-tabs, .keyword-field { grid-column: 1 / -1; } }
@media (max-width: 640px) { .log-toolbar, .log-summary { grid-template-columns: 1fr; } .log-tabs { grid-template-columns: 1fr; } .log-viewer, .log-viewer pre, .empty-state { min-height: 430px; } }
</style>
