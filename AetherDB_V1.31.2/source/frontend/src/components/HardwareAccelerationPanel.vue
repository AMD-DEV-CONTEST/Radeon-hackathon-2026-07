<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { Activity, AlertTriangle, CheckCircle2, Cpu, Gauge, RefreshCw } from "@lucide/vue";
import { useAiManagementStore } from "../stores/aiManagement.js";

const store = useAiManagementStore();
const { t } = useI18n();

const status = computed(() => store.hardwareAcceleration?.status || (store.hardwareError ? "error" : "loading"));
const runtime = computed(() => store.hardwareAcceleration?.runtime || {});
const hardware = computed(() => store.hardwareAcceleration?.hardware || {});
const statusMeta = computed(() => ({
  active: { label: "GPU 加速已启动", tone: "positive", icon: CheckCircle2 },
  available: { label: "GPU 加速可用，尚未启用", tone: "warning", icon: Activity },
  fallback: { label: "已回退到 CPU 推理", tone: "warning", icon: AlertTriangle },
  cold: { label: "运行时待启动", tone: "neutral", icon: Gauge },
  unsupported: { label: "当前环境未启用 GPU 加速", tone: "neutral", icon: Cpu },
  error: { label: "硬件加速检测异常", tone: "danger", icon: AlertTriangle },
  loading: { label: "正在检测硬件状态", tone: "neutral", icon: Gauge },
}[status.value]));

const STATUS_MESSAGES = {
  active: "BGE-M3 本地向量运行时已启用 GPU 加速。",
  available: "检测到兼容 GPU 后端，但当前 BGE-M3 运行时尚未使用。",
  fallback: "GPU 初始化失败，BGE-M3 已明确回退到 CPU 推理。",
  cold: "BGE-M3 本地运行时已就绪，执行后端将在首个任务启动后确定。",
  unsupported: "当前运行时未启用 GPU 加速，BGE-M3 使用 CPU 推理。",
  error: "BGE-M3 本地向量运行时不可用。",
  loading: "正在读取本地向量运行时与硬件信息。",
};

const message = computed(() => {
  if (store.hardwareError) return store.hardwareError;
  return t(STATUS_MESSAGES[status.value] || STATUS_MESSAGES.loading);
});
</script>

<template>
  <section class="hardware-section" :class="`tone-${statusMeta.tone}`">
    <header class="hardware-heading">
      <div class="heading-copy">
        <span class="hardware-icon"><component :is="statusMeta.icon" :size="20" /></span>
        <div>
          <h2>{{ t("硬件加速") }}</h2>
          <p>{{ t("检测 ROCm、CUDA 与本地 BGE-M3 向量运行时；不可用时会明确显示 CPU 回退状态。") }}</p>
        </div>
      </div>
      <div class="heading-actions">
        <span class="acceleration-state" :class="statusMeta.tone">
          <span class="state-dot"></span>{{ t(statusMeta.label) }}
        </span>
        <button class="icon-button" type="button" :title="t('重新检测硬件加速')" :disabled="store.hardwareLoading" @click="store.refreshHardwareAcceleration()">
          <RefreshCw :size="16" :class="{ spinning: store.hardwareLoading }" />
        </button>
      </div>
    </header>

    <p class="hardware-message">{{ message }}</p>

    <div class="hardware-metrics">
      <article><small>{{ t("显卡") }}</small><strong>{{ hardware.gpu_name || (hardware.detected ? "AMD GPU" : t("未检测到")) }}</strong></article>
      <article><small>{{ t("驱动版本") }}</small><strong>{{ hardware.driver_version || t("暂无数据") }}</strong></article>
      <article><small>{{ t("显存规模") }}</small><strong>{{ hardware.vram_human || t("暂无数据") }}</strong></article>
      <article><small>{{ t("计算单元") }}</small><strong>{{ hardware.compute_units ? `${hardware.compute_units} CU` : t("暂无数据") }}</strong></article>
      <article><small>{{ t("向量模型") }}</small><strong>{{ runtime.model_id || "BAAI/bge-m3" }}</strong></article>
      <article><small>{{ t("当前执行方式") }}</small><strong>{{ runtime.execution_provider || (runtime.available ? t("任务启动后确定") : t("未初始化")) }}</strong></article>
    </div>

    <div v-if="status === 'active'" class="acceleration-note positive-note">
      <Gauge :size="17" /><span>{{ t("BGE-M3 向量生成正在使用 {backend} 加速。", { backend: store.hardwareAcceleration?.acceleration_backend === "cuda" ? "CUDA" : "ROCm/MIGraphX" }) }}</span>
    </div>
    <div v-else-if="status === 'fallback' || runtime.execution_provider === 'CPUExecutionProvider'" class="acceleration-note warning-note">
      <Cpu :size="17" /><span>{{ t("当前向量任务使用 CPU 推理，功能保持可用，但生成速度可能较慢。") }}</span>
    </div>
  </section>
</template>

<style scoped>
.hardware-section { display: grid; gap: 14px; border: 1px solid var(--border); border-left: 4px solid #a7a2b4; border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); padding: 17px; }
.hardware-section.tone-positive { border-left-color: #24a474; }
.hardware-section.tone-warning { border-left-color: #d6a13e; }
.hardware-section.tone-danger { border-left-color: #c95858; }
.hardware-heading, .heading-copy, .heading-actions, .acceleration-state, .acceleration-note { display: flex; align-items: center; }
.hardware-heading { justify-content: space-between; gap: 16px; }
.heading-copy { gap: 11px; min-width: 0; }
.heading-copy > div { min-width: 0; }
.hardware-icon { width: 38px; height: 38px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: var(--accent-soft); color: var(--accent); }
.hardware-heading h2 { margin-bottom: 4px; font-size: 16px; }
.hardware-heading p, .hardware-message { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.heading-actions { gap: 8px; flex: 0 0 auto; }
.acceleration-state { gap: 7px; min-height: 30px; border-radius: 999px; background: #f0eef4; color: var(--text-secondary); padding: 5px 10px; font-size: 11px; font-weight: 700; }
.acceleration-state.positive { background: #e7f8f0; color: #15704f; }
.acceleration-state.warning { background: #fff6e5; color: #95651b; }
.acceleration-state.danger { background: #fff0f0; color: #a33f3f; }
.state-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.icon-button { width: 34px; height: 34px; display: inline-grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.hardware-metrics { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 8px; }
.hardware-metrics article { display: grid; gap: 5px; min-width: 0; border-radius: 8px; background: var(--bg-secondary); padding: 11px; }
.hardware-metrics small { color: var(--text-muted); font-size: 10px; }
.hardware-metrics strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.acceleration-note { gap: 8px; border-radius: 8px; padding: 10px 12px; font-size: 11px; }
.positive-note { background: #edf9f3; color: #167251; }
.warning-note { background: #fff7e9; color: #8c621f; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .hardware-heading { align-items: flex-start; flex-direction: column; } .heading-actions { width: 100%; justify-content: space-between; } }
@media (max-width: 620px) { .hardware-metrics { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
