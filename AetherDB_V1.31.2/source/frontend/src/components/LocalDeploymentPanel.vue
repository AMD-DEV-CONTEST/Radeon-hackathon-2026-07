<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  Activity,
  CheckCircle2,
  CircleX,
  Download,
  HardDrive,
  LoaderCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Server,
  ShieldCheck,
  Square,
  Trash2,
} from "@lucide/vue";
import { useAiManagementStore } from "../stores/aiManagement.js";

const props = defineProps({ providerId: { type: String, default: null } });
const store = useAiManagementStore();
const { t } = useI18n();
const modelName = ref("");
const showInstallInfo = ref(false);
const deleteTarget = ref(null);
const deleteConfirmation = ref("");
const compatibleRuntimeStates = new Set(["compatible", "tested_target", "backward_compatible_api"]);
const activeExecutionStates = new Set(["queued", "admitted", "running", "cancel_requested"]);

const statusKind = computed(() => {
  if (store.ollamaLoading) return "loading";
  if (!store.ollama) return "unavailable";
  if (!store.ollama.installed) return "not-installed";
  if (!store.ollama.running) return "stopped";
  if (!compatibleRuntimeStates.has(store.ollama.compatibility)) return "incompatible";
  return "ready";
});

const statusCopy = computed(() => ({
  loading: [t("正在检查本地运行时"), t("正在读取 Ollama 与模型状态。")],
  unavailable: [t("无法读取本地部署状态"), store.ollamaError || t("请确认 AetherDB 后端和管理员凭据可用。")],
  "not-installed": [t("未检测到 Ollama"), t("可以通过受校验的官方安装包完成本地安装。")],
  stopped: [t("Ollama 已安装但未运行"), t("可以由 AetherDB 启动当前已安装的本地运行时。")],
  incompatible: [t("运行时版本需要确认"), t("当前 {current}，目标 {target}。", { current: store.ollama?.version || t("未知"), target: store.ollama?.target_version || t("未提供") })],
  ready: [t("本地运行时可用"), t("Ollama {version} 已连接。", { version: store.ollama?.version || "" })],
})[statusKind.value]);

const installOperation = computed(() => store.installOperation);
const installProgress = computed(() => Math.round((installOperation.value?.progress || 0) * 100));
const installBusy = computed(() => [
  "checking",
  "downloading",
  "verifying",
  "launching_installer",
  "waiting_for_installer",
  "rediscovering",
  "service_starting",
  "api_verifying",
  "provider_registering",
].includes(installOperation.value?.status));
const runtimeManaged = computed(() => Boolean(store.ollama?.managed));
const externalOccupancy = computed(() => store.ollama?.external_occupancy || []);
const activeExecutions = computed(() => (
  store.ollamaExecutions.filter((item) => activeExecutionStates.has(item.status))
));

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 MB";
  return `${(bytes / (1024 ** 3)).toFixed(2)} GB`;
}

async function openInstall() {
  showInstallInfo.value = true;
  try { await store.prepareOllamaInstall(); } catch { /* store exposes the error */ }
}

async function confirmInstallDownload() {
  if (!installOperation.value?.id) return;
  try { await store.confirmOllamaInstallDownload(installOperation.value.id); } catch { /* store exposes the error */ }
}

async function launchInstaller() {
  if (!installOperation.value?.id || !store.installPlan?.version) return;
  try {
    await store.launchOllamaInstall(installOperation.value.id, store.installPlan.version);
  } catch { /* store exposes the error */ }
}

async function cancelInstall() {
  if (!installOperation.value?.id) return;
  try { await store.cancelOllamaInstall(installOperation.value.id); } catch { /* store exposes the error */ }
}

async function startRuntime() {
  try { await store.startRuntime(props.providerId); } catch { /* store exposes the error */ }
}

async function stopRuntime() {
  try { await store.stopRuntime(props.providerId); } catch { /* store exposes the error */ }
}

async function pullModel() {
  const name = modelName.value.trim();
  if (!name) return;
  try {
    await store.pullModel(name, props.providerId);
    modelName.value = "";
  } catch { /* store exposes the error */ }
}

async function toggleModel(model) {
  if (!runtimeManaged.value) return;
  try {
    if (model.loaded) await store.unloadModel(model.name, props.providerId);
    else await store.loadModel(model.name, props.providerId);
  } catch { /* store exposes the error */ }
}

async function cancelExecution(execution) {
  try { await store.cancelExecution(execution.execution_id, props.providerId); } catch { /* store exposes the error */ }
}

async function reconcileDrift() {
  try { await store.reconcileRuntimeDrift(props.providerId); } catch { /* store exposes the error */ }
}

async function confirmDelete() {
  if (!deleteTarget.value || deleteConfirmation.value !== deleteTarget.value.name) return;
  try {
    await store.deleteModel(deleteTarget.value.name, deleteConfirmation.value, props.providerId);
    deleteTarget.value = null;
    deleteConfirmation.value = "";
  } catch { /* store exposes the error */ }
}

onBeforeUnmount(() => {
  store.stopOperationPolling();
  store.stopInstallPolling();
});
</script>

<template>
  <section class="local-deploy">
    <header class="section-heading">
      <div>
        <span class="eyebrow">{{ t("高级设置") }}</span>
        <h3>{{ t("Ollama 本地部署") }}</h3>
        <p>{{ t("本地运行时由 AetherDB 后端统一检测和管理，前端不会直接执行安装程序。") }}</p>
      </div>
      <button class="icon-button" type="button" :title="t('刷新本地运行时状态')" :disabled="store.ollamaLoading" @click="store.refreshOllama(providerId)">
        <RefreshCw :size="17" :class="{ spinning: store.ollamaLoading }" />
      </button>
    </header>

    <div class="runtime-status" :class="statusKind">
      <LoaderCircle v-if="statusKind === 'loading'" :size="22" class="spinning" />
      <CheckCircle2 v-else-if="statusKind === 'ready'" :size="22" />
      <Server v-else-if="statusKind === 'stopped'" :size="22" />
      <AlertTriangle v-else :size="22" />
      <div>
        <strong>{{ statusCopy[0] }}</strong>
        <span>{{ statusCopy[1] }}</span>
      </div>
      <button v-if="statusKind === 'not-installed'" class="btn btn-primary" type="button" @click="openInstall">
        <Download :size="16" /> {{ t("安装 Ollama") }}
      </button>
      <button v-else-if="statusKind === 'stopped'" class="btn btn-primary" type="button" :disabled="store.busyAction === 'ollama:start'" @click="startRuntime">
        <Play :size="16" /> {{ t("启动运行时") }}
      </button>
      <button
        v-else-if="statusKind === 'ready' && runtimeManaged"
        class="btn btn-secondary"
        type="button"
        :disabled="store.busyAction === 'ollama:stop'"
        @click="stopRuntime"
      ><Square :size="15" />{{ t("停止运行时") }}</button>
      <span v-else-if="statusKind === 'ready'" class="ownership-badge">
        <ShieldCheck :size="14" />{{ t("外部实例 · 只观察") }}
      </span>
    </div>

    <div v-if="store.ollamaError" class="inline-notice error">{{ store.ollamaError }}</div>

    <div v-if="store.ollama?.installed" class="runtime-metrics">
      <div><span>{{ t("安装版本") }}</span><strong>{{ store.ollama.version || t("未运行") }}</strong></div>
      <div><span>{{ t("兼容状态") }}</span><strong>{{ store.ollama.compatibility || t("未知") }}</strong></div>
      <div><span>{{ t("已安装模型") }}</span><strong>{{ store.ollama.installed_model_count || 0 }}</strong></div>
      <div><span>{{ t("已加载模型") }}</span><strong>{{ store.ollama.loaded_model_count || 0 }}</strong></div>
      <div><span>{{ t("资源所有权") }}</span><strong>{{ t(runtimeManaged ? "AetherDB 管理" : "外部管理") }}</strong></div>
    </div>

    <template v-if="store.ollama?.running">
      <div v-if="!runtimeManaged" class="ownership-notice">
        <ShieldCheck :size="17" />
        <p>
          <strong>{{ t("AetherDB 不接管外部 Ollama") }}</strong>
          <span>{{ t("仅记录资源占用并暂停冲突任务；不会停止实例、卸载模型或删除外部模型文件。") }}</span>
        </p>
      </div>
      <form class="pull-form" @submit.prevent="pullModel">
        <div class="field-row">
          <label for="ollama-model-name">{{ t("下载模型") }}</label>
          <input id="ollama-model-name" v-model="modelName" :placeholder="t('例如 deepseek-r1:8b')" autocomplete="off" />
        </div>
        <button class="btn btn-primary" type="submit" :disabled="!modelName.trim() || store.busyAction === 'ollama:pull'">
          <Download :size="16" /> {{ t("添加模型") }}
        </button>
      </form>

      <div class="model-list">
        <article v-for="model in store.ollama.models || []" :key="model.name" class="model-row">
          <HardDrive :size="19" />
          <div class="model-copy">
            <strong>{{ model.name }}</strong>
            <span>{{ model.parameter_size || t("参数未知") }} · {{ model.quantization_level || t("量化未知") }}</span>
          </div>
          <span class="state-badge" :class="{ positive: model.loaded }">{{ t(model.loaded ? "已加载" : "未加载") }}</span>
          <button
            class="btn btn-secondary compact"
            type="button"
            :disabled="!runtimeManaged"
            :title="t(runtimeManaged ? (model.loaded ? '卸载模型' : '加载模型') : '外部模型只允许观察')"
            @click="toggleModel(model)"
          >{{ t(runtimeManaged ? (model.loaded ? "卸载" : "加载") : "只观察") }}</button>
          <button
            class="icon-button danger"
            type="button"
            :disabled="!runtimeManaged"
            :title="t(runtimeManaged ? '删除模型文件' : '外部模型文件不由 AetherDB 删除')"
            @click="deleteTarget = model; deleteConfirmation = ''"
          >
            <Trash2 :size="16" />
          </button>
        </article>
        <div v-if="!(store.ollama.models || []).length" class="small-empty">{{ t("尚未安装本地模型。") }}</div>
      </div>
    </template>

    <section v-if="externalOccupancy.length" class="occupancy-section">
      <h4><Activity :size="15" />{{ t("外部资源占用") }}</h4>
      <div v-for="item in externalOccupancy" :key="`${item.runtime_id}:${item.model_name}`" class="occupancy-row">
        <span><strong>{{ item.model_name }}</strong><small>{{ item.resource_id }} · {{ item.size_vram_mb || 0 }} MB VRAM</small></span>
        <em>{{ t("外部占用") }}</em>
      </div>
    </section>

    <section v-if="activeExecutions.length || store.ollamaExecutions.length" class="execution-section">
      <h4><Activity :size="15" />{{ t("AetherDB 模型任务") }}</h4>
      <div v-for="execution in store.ollamaExecutions.slice(0, 8)" :key="execution.execution_id" class="execution-row">
        <span>
          <strong>{{ execution.model_name || execution.provider_model_name || execution.task_id }}</strong>
          <small>{{ execution.status }} · {{ execution.task_type }}</small>
        </span>
        <button
          v-if="activeExecutionStates.has(execution.status)"
          class="icon-button"
          type="button"
          :title="t('取消本项目任务')"
          @click="cancelExecution(execution)"
        ><CircleX :size="15" /></button>
      </div>
    </section>

    <section v-if="store.modelRuntimeDrift.length" class="drift-section">
      <header>
        <h4><AlertTriangle :size="15" />{{ t("资源状态漂移") }}</h4>
        <button class="btn btn-secondary compact" type="button" @click="reconcileDrift">
          <RefreshCw :size="14" />{{ t("重新计算") }}
        </button>
      </header>
      <p>{{ t("只会释放 AetherDB 自己持有的失效租约，并重新计算外部占用。") }}</p>
      <div v-for="event in store.modelRuntimeDrift.slice(0, 5)" :key="event.id || event.drift_id">
        <span>{{ event.reason_code || event.kind || event.status }}</span>
        <small>{{ event.resource_id || event.lease_id }}</small>
      </div>
    </section>

    <div v-if="store.operations.length" class="operations">
      <h4>{{ t("最近模型任务") }}</h4>
      <div v-for="operation in store.operations.slice(0, 6)" :key="operation.id" class="operation-row">
        <div>
          <strong>{{ operation.model_name }}</strong>
          <span>{{ operation.status_message || operation.status }}</span>
        </div>
        <div class="progress-track"><i :style="{ width: `${Math.round((operation.progress || 0) * 100)}%` }"></i></div>
        <span>{{ Math.round((operation.progress || 0) * 100) }}%</span>
        <button v-if="operation.status === 'failed'" class="icon-button" type="button" :title="t('重试下载')" @click="store.retryOperation(operation.id, providerId)">
          <RotateCcw :size="15" />
        </button>
        <button v-else-if="['queued', 'running'].includes(operation.status)" class="icon-button" type="button" :title="t('取消下载')" @click="store.cancelOperation(operation.id, providerId)">
          <CircleX :size="15" />
        </button>
      </div>
    </div>

    <div v-if="showInstallInfo" class="dialog-backdrop" @click.self="showInstallInfo = false">
      <section class="dialog-card compact-dialog" role="dialog" aria-modal="true" aria-labelledby="install-title">
        <Server :size="28" />
        <h3 id="install-title">{{ t("安装 Ollama") }}</h3>
        <p v-if="store.installPlan">
          {{ t("官方稳定版 {version} · {platform} / {architecture} · {size}", { version: store.installPlan.version, platform: store.installPlan.platform, architecture: store.installPlan.architecture, size: formatBytes(installOperation?.total_bytes) }) }}
        </p>
        <p v-else>{{ t("正在读取当前系统的受信任安装计划。") }}</p>
        <div v-if="installOperation" class="inline-notice">
          {{ installOperation.status_message || installOperation.status }}
        </div>
        <div v-if="installBusy || installOperation?.status === 'ready_to_launch'" class="install-progress">
          <div class="progress-track"><i :style="{ width: `${installProgress}%` }"></i></div>
          <span>{{ installProgress }}%</span>
        </div>
        <p class="install-boundary">{{ t("安装包由后端固定清单下载并完成大小、SHA-256 和平台签名校验。Ollama 仍是独立运行时，不会进入 AetherDB 安装包。") }}</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" type="button" @click="showInstallInfo = false">{{ t("关闭") }}</button>
          <button
            v-if="installOperation?.status === 'awaiting_confirmation'"
            class="btn btn-primary"
            type="button"
            :disabled="store.busyAction === 'ollama-install:download'"
            @click="confirmInstallDownload"
          ><Download :size="16" /> {{ t("确认下载") }}</button>
          <button
            v-else-if="installOperation?.status === 'ready_to_launch'"
            class="btn btn-primary"
            type="button"
            :disabled="store.busyAction === 'ollama-install:launch'"
            @click="launchInstaller"
          ><Play :size="16" /> {{ t("确认安装 {version}", { version: store.installPlan?.version }) }}</button>
          <button
            v-else-if="installBusy"
            class="btn btn-secondary"
            type="button"
            :disabled="store.busyAction === 'ollama-install:cancel'"
            @click="cancelInstall"
          >{{ t("取消等待") }}</button>
          <button
            v-else-if="['failed', 'cancelled'].includes(installOperation?.status)"
            class="btn btn-primary"
            type="button"
            @click="openInstall"
          ><RotateCcw :size="16" /> {{ t("重新准备") }}</button>
        </div>
      </section>
    </div>

    <div v-if="deleteTarget" class="dialog-backdrop" @click.self="deleteTarget = null">
      <section class="dialog-card compact-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-model-title">
        <AlertTriangle :size="28" class="danger-text" />
        <h3 id="delete-model-title">{{ t("删除模型文件") }}</h3>
        <p>{{ t("此操作会删除本地文件。请输入完整模型名 {name} 进行确认。", { name: deleteTarget.name }) }}</p>
        <input v-model="deleteConfirmation" autocomplete="off" />
        <div class="dialog-actions">
          <button class="btn btn-secondary" type="button" @click="deleteTarget = null">{{ t("取消") }}</button>
          <button class="btn danger-button" type="button" :disabled="deleteConfirmation !== deleteTarget.name" @click="confirmDelete">{{ t("确认删除") }}</button>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.local-deploy { display: grid; gap: 14px; }
.install-progress { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.install-boundary { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.section-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.section-heading h3 { margin: 3px 0 5px; font-size: 17px; }
.section-heading p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.eyebrow { color: var(--accent); font-size: 11px; }
.icon-button { width: 34px; height: 34px; display: inline-grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.icon-button:hover { color: var(--accent); border-color: #cfc5ff; }
.icon-button.danger, .danger-text { color: #b54545; }
.runtime-status { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 12px; border: 1px solid var(--border); border-radius: 8px; padding: 14px; background: #f8f8fc; color: #686478; }
.runtime-status.ready { background: #eefaf5; color: #167251; }
.runtime-status.stopped, .runtime-status.not-installed { background: #fff8ed; color: #996018; }
.runtime-status div { display: grid; gap: 3px; }
.runtime-status span { font-size: 12px; line-height: 1.5; }
.ownership-badge { display: inline-flex !important; align-items: center; gap: 5px; border-radius: 999px; background: #fff6e5; color: #95651b; padding: 5px 8px; font-size: 10px !important; font-weight: 700; }
.inline-notice { border-radius: 8px; padding: 10px 12px; background: #f4f1ff; color: #625690; font-size: 12px; line-height: 1.6; }
.inline-notice.error { background: #fff0f0; color: #a33f3f; }
.runtime-metrics { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 8px; }
.runtime-metrics div { display: grid; gap: 5px; padding: 11px; border-radius: 8px; background: var(--bg-secondary); }
.runtime-metrics span, .model-copy span, .operation-row span { color: var(--text-secondary); font-size: 11px; }
.runtime-metrics strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.pull-form { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 10px; align-items: end; }
.ownership-notice { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: start; gap: 9px; border: 1px solid #eed9a9; border-radius: 8px; background: #fff9ed; color: #8b621e; padding: 10px; }
.ownership-notice p { display: grid; gap: 3px; margin: 0; }
.ownership-notice strong { font-size: 12px; }
.ownership-notice span { font-size: 11px; line-height: 1.5; }
.model-list, .operations { display: grid; gap: 8px; }
.model-row { display: grid; grid-template-columns: auto minmax(0,1fr) auto auto auto; align-items: center; gap: 10px; border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.model-copy { display: grid; gap: 3px; min-width: 0; }
.model-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.state-badge { border-radius: 999px; padding: 3px 8px; background: #f1eff5; color: var(--text-secondary); font-size: 11px; }
.state-badge.positive { background: #e8f8f1; color: #167251; }
.model-row button:disabled { opacity: .52; cursor: not-allowed; }
.compact { min-height: 32px; padding: 5px 10px; font-size: 12px; }
.small-empty { min-height: 70px; display: grid; place-items: center; border: 1px dashed var(--border); border-radius: 8px; color: var(--text-muted); font-size: 12px; }
.operations h4 { font-size: 13px; }
.occupancy-section, .execution-section, .drift-section { display: grid; gap: 7px; border-top: 1px solid var(--border); padding-top: 12px; }
.occupancy-section h4, .execution-section h4, .drift-section h4 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 13px; }
.occupancy-row, .execution-row { display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: 7px; padding: 8px; }
.occupancy-row > span, .execution-row > span { min-width: 0; display: grid; gap: 2px; }
.occupancy-row strong, .execution-row strong, .occupancy-row small, .execution-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.occupancy-row strong, .execution-row strong { font-size: 11px; }
.occupancy-row small, .execution-row small, .drift-section small { color: var(--text-muted); font-size: 9px; }
.occupancy-row em { border-radius: 999px; background: #fff6e5; color: #95651b; padding: 4px 7px; font-size: 9px; font-style: normal; font-weight: 700; }
.drift-section header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.drift-section > p { margin: 0; color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
.drift-section > div { display: flex; justify-content: space-between; gap: 8px; border-bottom: 1px solid var(--border); padding: 4px 0; font-size: 10px; }
.operation-row { display: grid; grid-template-columns: minmax(130px,.8fr) minmax(120px,1fr) 40px 34px; gap: 10px; align-items: center; }
.operation-row > div:first-child { display: grid; gap: 2px; min-width: 0; }
.operation-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.progress-track { height: 7px; border-radius: 999px; overflow: hidden; background: #e9e6ef; }
.progress-track i { display: block; height: 100%; background: var(--accent); }
.dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(28,25,44,.42); }
.dialog-card { width: min(640px,100%); max-height: calc(100vh - 40px); overflow-y: auto; border-radius: 8px; background: #fff; box-shadow: 0 24px 70px rgba(28,25,44,.22); padding: 22px; }
.compact-dialog { width: min(460px,100%); display: grid; gap: 13px; }
.compact-dialog p { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.danger-button { background: #b54545; color: #fff; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) {
  .runtime-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .runtime-status, .model-row, .operation-row, .pull-form { grid-template-columns: 1fr; }
}
</style>
