<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { AlertTriangle, FolderOpen, LoaderCircle, Power, RefreshCw, Server } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import App from "../App.vue";
import { configureApiClient } from "../api/client.js";

const { t } = useI18n();
const desktop = Boolean(window.__TAURI_INTERNALS__);
const ready = ref(!desktop);
const startedOnce = ref(!desktop);
const starting = ref(desktop);
const status = ref(null);
const failure = ref(null);
const stageIndex = ref(0);
let monitorTimer = null;
let stageTimer = null;
let missedHealthChecks = 0;
let automaticRestartUsed = false;
let recoveryInFlight = false;
const expectedBuildId = __BUILD_ID__;

const stages = [
  "正在启动本地后台服务",
  "正在初始化本地数据库",
  "正在验证 AetherDB 服务身份",
];

const stageLabel = computed(() => t(stages[Math.min(stageIndex.value, stages.length - 1)]));
const failureCode = computed(() => failure.value?.code || "BACKEND_START_FAILED");
const failureMessage = computed(() => {
  if (failure.value?.message) return failure.value.message;
  if (failureCode.value === "BACKEND_PORT_IN_USE") {
    return t("本地端口已被其他程序占用，AetherDB 无法启动后台服务。");
  }
  if (failureCode.value === "BACKEND_TIMEOUT") {
    return t("本地后台服务没有及时完成启动，请重试或查看日志。");
  }
  if (failureCode.value === "BACKEND_UNAVAILABLE") {
    return t("本地后台服务已经停止，数据库与 AI 功能暂时不可用。");
  }
  return t("本地后台服务启动失败，数据库与 AI 功能暂时不可用。");
});

function normalizeFailure(error) {
  if (error && typeof error === "object") return error;
  if (typeof error === "string") {
    try {
      const parsed = JSON.parse(error);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      return { code: "BACKEND_START_FAILED", reason: error };
    }
  }
  return { code: "BACKEND_START_FAILED", reason: String(error || "Unknown startup error") };
}

function beginStages() {
  stageIndex.value = 0;
  window.clearInterval(stageTimer);
  stageTimer = window.setInterval(() => {
    stageIndex.value = Math.min(stageIndex.value + 1, stages.length - 1);
  }, 3500);
}

function finishStages() {
  window.clearInterval(stageTimer);
  stageTimer = null;
}

function acceptBackend(nextStatus) {
  if (
    !nextStatus?.available
    || !nextStatus?.managed
    || !nextStatus?.databaseReady
    || !nextStatus?.baseUrl
    || !nextStatus?.ownerToken
    || !nextStatus?.instanceId
    || !nextStatus?.buildId
  ) {
    throw nextStatus?.error || {
      code: "BACKEND_UNAVAILABLE",
      message: t("本地后台服务未通过身份与数据库健康检查。"),
    };
  }
  if (nextStatus.buildId !== expectedBuildId) {
    throw {
      code: "BACKEND_BUILD_MISMATCH",
      message: t("桌面客户端与本地后端不是同一次构建，请重新安装完整发行包。"),
      expectedBuildId,
      actualBuildId: nextStatus.buildId,
    };
  }
  configureApiClient({
    baseUrl: `${nextStatus.baseUrl}/api`,
    apiKey: nextStatus.ownerToken,
  });
  status.value = nextStatus;
  failure.value = null;
  missedHealthChecks = 0;
  ready.value = true;
  startedOnce.value = true;
}

async function invokeBackend(command) {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke(command);
}

async function startBackend(command = "start_backend") {
  if (!desktop || starting.value) return;
  starting.value = true;
  failure.value = null;
  beginStages();
  try {
    acceptBackend(await invokeBackend(command));
    if (command === "restart_backend") automaticRestartUsed = false;
  } catch (error) {
    ready.value = false;
    failure.value = normalizeFailure(error);
  } finally {
    finishStages();
    starting.value = false;
  }
}

async function recheckBackend() {
  if (starting.value) return;
  starting.value = true;
  failure.value = null;
  beginStages();
  try {
    const nextStatus = await invokeBackend("backend_status");
    if (nextStatus?.available) acceptBackend(nextStatus);
    else acceptBackend(await invokeBackend("start_backend"));
    automaticRestartUsed = false;
  } catch (error) {
    ready.value = false;
    failure.value = normalizeFailure(error);
  } finally {
    finishStages();
    starting.value = false;
  }
}

async function recoverBackendOnce() {
  if (!desktop || starting.value || recoveryInFlight || automaticRestartUsed) return;
  recoveryInFlight = true;
  ready.value = false;
  failure.value = {
    code: "BACKEND_UNAVAILABLE",
    message: t("本地后台服务已停止，AetherDB 正在尝试恢复。"),
  };
  try {
    const currentStatus = await invokeBackend("backend_status");
    if (currentStatus?.available && currentStatus?.databaseReady) {
      acceptBackend(currentStatus);
      return;
    }
    automaticRestartUsed = true;
    acceptBackend(await invokeBackend("restart_backend"));
  } catch (error) {
    ready.value = false;
    failure.value = normalizeFailure(error);
  } finally {
    recoveryInFlight = false;
  }
}

function handleBackendUnavailable() {
  ready.value = false;
  recoverBackendOnce();
}

async function monitorBackend() {
  if (!desktop || starting.value || !startedOnce.value) return;
  try {
    const nextStatus = await invokeBackend("backend_status");
    if (nextStatus?.available && nextStatus?.databaseReady) {
      acceptBackend(nextStatus);
      return;
    }
    missedHealthChecks += 1;
    if (missedHealthChecks >= 2) {
      ready.value = false;
      status.value = nextStatus;
      failure.value = nextStatus?.error || {
        code: "BACKEND_UNAVAILABLE",
        message: t("本地后台服务已经停止，数据库与 AI 功能暂时不可用。"),
      };
      recoverBackendOnce();
    }
  } catch (error) {
    missedHealthChecks += 1;
    if (missedHealthChecks >= 2) {
      ready.value = false;
      failure.value = normalizeFailure(error);
      recoverBackendOnce();
    }
  }
}

async function openLogs() {
  try {
    await invokeBackend("open_backend_logs");
  } catch (error) {
    failure.value = normalizeFailure(error);
  }
}

async function exitApplication() {
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().close();
}

onMounted(() => {
  if (desktop) {
    window.addEventListener("aetherdb:backend-unavailable", handleBackendUnavailable);
    starting.value = false;
    recheckBackend();
    monitorTimer = window.setInterval(monitorBackend, 3000);
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("aetherdb:backend-unavailable", handleBackendUnavailable);
  window.clearInterval(monitorTimer);
  finishStages();
});
</script>

<template>
  <App v-if="startedOnce" />

  <div v-if="!ready" class="backend-gate" :class="{ overlay: startedOnce }" role="alert">
    <section class="backend-status-panel">
      <div class="status-icon" :class="{ error: !starting }">
        <LoaderCircle v-if="starting" :size="30" class="spinning" />
        <AlertTriangle v-else :size="30" />
      </div>

      <div class="status-copy">
        <p class="product-label"><Server :size="15" /> AetherDB</p>
        <h1>{{ starting ? t("正在准备本地服务") : t("AetherDB 未能完整启动") }}</h1>
        <p v-if="starting">{{ stageLabel }}</p>
        <template v-else>
          <p>{{ failureMessage }}</p>
          <dl class="diagnostic-summary">
            <div><dt>{{ t("错误类型") }}</dt><dd>{{ failureCode }}</dd></div>
            <div v-if="failure?.port || status?.port">
              <dt>{{ t("本地端口") }}</dt><dd>{{ failure?.port || status?.port }}</dd>
            </div>
            <div v-if="failure?.exitCode !== undefined && failure?.exitCode !== null">
              <dt>{{ t("退出码") }}</dt><dd>{{ failure.exitCode }}</dd>
            </div>
          </dl>
        </template>
      </div>

      <div v-if="!starting" class="gate-actions">
        <button class="btn btn-primary" type="button" @click="recheckBackend">
          <RefreshCw :size="16" />{{ t("重新检测") }}
        </button>
        <button class="btn btn-secondary" type="button" @click="startBackend('restart_backend')">
          <Server :size="16" />{{ t("重新启动后台服务") }}
        </button>
        <button class="btn btn-secondary" type="button" @click="openLogs">
          <FolderOpen :size="16" />{{ t("打开日志目录") }}
        </button>
        <button class="btn btn-quiet" type="button" @click="exitApplication">
          <Power :size="16" />{{ t("退出应用") }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.backend-gate {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: grid;
  place-items: center;
  padding: 28px;
  background: var(--bg-app, #f5f5f7);
}

.backend-gate.overlay {
  background: rgba(245, 245, 247, 0.96);
}

.backend-status-panel {
  width: min(680px, 100%);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 18px 20px;
  border: 1px solid var(--border, #dddde3);
  border-radius: 8px;
  background: #fff;
  padding: 26px;
  box-shadow: 0 18px 48px rgba(35, 35, 42, 0.12);
}

.status-icon {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: #eef3ff;
  color: #5068b8;
}

.status-icon.error {
  background: #fff0f0;
  color: #a33f3f;
}

.status-copy {
  min-width: 0;
}

.product-label {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0 0 8px;
  color: var(--text-secondary, #656570);
  font-size: 12px;
}

.status-copy h1 {
  margin: 0 0 9px;
  font-size: 24px;
  font-weight: 650;
  letter-spacing: 0;
}

.status-copy > p {
  margin: 0;
  color: var(--text-secondary, #656570);
  line-height: 1.65;
}

.diagnostic-summary {
  display: grid;
  gap: 7px;
  margin: 16px 0 0;
}

.diagnostic-summary div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
}

.diagnostic-summary dt {
  color: var(--text-muted, #8a8a94);
}

.diagnostic-summary dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--text-primary, #24242a);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.gate-actions {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  padding-top: 4px;
}

.gate-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
}

.btn-quiet {
  border: 0;
  background: transparent;
  color: var(--text-secondary, #656570);
}

.spinning {
  animation: backend-spin 1s linear infinite;
}

@keyframes backend-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 560px) {
  .backend-gate { padding: 16px; }
  .backend-status-panel { grid-template-columns: 1fr; padding: 20px; }
  .gate-actions { grid-column: 1; }
  .gate-actions button { width: 100%; }
}
</style>
