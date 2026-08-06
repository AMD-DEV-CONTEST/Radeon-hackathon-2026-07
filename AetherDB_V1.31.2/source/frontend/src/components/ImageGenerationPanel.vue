<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Image,
  Link2,
  RefreshCw,
  RotateCcw,
  Square,
  WandSparkles,
} from "@lucide/vue";
import {
  cancelMediaGenerationTask,
  createMediaGenerationTask,
  getMediaGenerationStatus,
  getMediaGenerationTask,
  listMediaGenerationEvents,
  listMediaGenerationTasks,
  publishMediaGenerationTask,
  retryMediaGenerationTask,
} from "../api/mediaGeneration.js";
import { listMediaAssets } from "../api/mediaAssets.js";
import { listModelProfiles } from "../api/models.js";
import { useAppStore } from "../stores/app.js";

const emit = defineEmits(["open-assets"]);
const store = useAppStore();
const { locale, t } = useI18n();

const contract = ref(null);
const tasks = ref([]);
const selectedTask = ref(null);
const events = ref([]);
const imageAssets = ref([]);
const modelProfiles = ref([]);
const loading = ref(false);
const action = ref("");
const errorMessage = ref("");
const successMessage = ref("");
let pollTimer = null;

const form = ref({
  operation: "image.generate",
  prompt: "",
  negative_prompt: "",
  source_asset_id: "",
  model_profile_id: "",
  width: 768,
  height: 768,
  steps: 30,
  guidance_scale: 4,
  strength: 0.3,
  seed: "",
  requested_backend: "auto",
  allow_cloud_upload: false,
});

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const hasScope = computed(() => Boolean(databaseId.value && bookId.value));
const sourceRequired = computed(() => form.value.operation !== "image.generate");
const selectedModel = computed(() => (
  modelProfiles.value.find((item) => item.id === form.value.model_profile_id) || null
));
const cloudConfirmationRequired = computed(() => (
  selectedModel.value
  && selectedModel.value.privacy_level !== "local_only"
));
const canCreate = computed(() => (
  hasScope.value
  && form.value.prompt.trim()
  && (!sourceRequired.value || form.value.source_asset_id)
  && (!cloudConfirmationRequired.value || form.value.allow_cloud_upload)
  && !action.value
));
const activeTasks = computed(() => (
  tasks.value.some((task) => ["queued", "running", "cancelling"].includes(task.status))
));
const canPublishSelected = computed(() => (
  selectedTask.value?.status === "completed"
  && selectedTask.value?.output_asset_id
  && store.activeChapter?.content_group_id
));

const OPERATION_LABELS = {
  "image.generate": "文生图",
  "image.img2img": "图生图",
  "image.enhance": "图像增强",
};
const STATUS_LABELS = {
  queued: "等待执行",
  running: "正在生成",
  cancelling: "正在取消",
  completed: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
};
const ERROR_LABELS = {
  INSTALL_REQUIRED: "所选图像模型包尚未安装，请先在 AI 设置与管理中完成安装。",
  PACKAGE_DISABLED: "所选图像模型包已停用。",
  MODEL_NOT_ENABLED: "所选图像模型未启用。",
  MODEL_UNAVAILABLE: "所选图像模型当前不可用。",
  MODEL_CAPABILITY_UNSUPPORTED: "所选模型尚未确认图像生成能力。",
  AMBIGUOUS_MODEL_ROUTE: "存在多个可用图像模型，请明确选择一个执行目标。",
  CLOUD_UPLOAD_CONFIRMATION_REQUIRED: "使用云端图像模型前必须明确允许上传提示词和源图。",
  SOURCE_IMAGE_REQUIRED: "当前生成方式需要选择一张已批准的源图像。",
};

function safeMessage(error, fallback) {
  const code = error?.detail?.code || error?.code;
  if (ERROR_LABELS[code]) return t(ERROR_LABELS[code]);
  return error?.detail?.message || error?.message || t(fallback);
}

function taskTone(status) {
  if (status === "completed") return "positive";
  if (status === "running") return "active";
  if (status === "queued" || status === "cancelling") return "warning";
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

async function refresh({ silent = false } = {}) {
  if (!hasScope.value) {
    tasks.value = [];
    imageAssets.value = [];
    return;
  }
  if (!silent) loading.value = true;
  errorMessage.value = "";
  const results = await Promise.allSettled([
    getMediaGenerationStatus(),
    listMediaGenerationTasks({
      database_id: databaseId.value,
      book_id: bookId.value,
      limit: 80,
    }),
    listMediaAssets({
      database_id: databaseId.value,
      book_id: bookId.value,
      modality: "image",
      lifecycle_status: "approved",
      limit: 200,
    }),
    listModelProfiles(),
  ]);
  if (results[0].status === "fulfilled") contract.value = results[0].value;
  if (results[1].status === "fulfilled") tasks.value = results[1].value?.tasks || [];
  else errorMessage.value = safeMessage(results[1].reason, "图像任务加载失败");
  if (results[2].status === "fulfilled") imageAssets.value = results[2].value?.assets || [];
  if (results[3].status === "fulfilled") {
    modelProfiles.value = (results[3].value?.model_profiles || []).filter((item) => (
      item.enabled
      && ["image", "image_generation", "multimodal_generation"].includes(item.model_type)
    ));
  }
  if (selectedTask.value?.task_id) {
    const current = tasks.value.find((task) => task.task_id === selectedTask.value.task_id);
    if (current) await openTask(current, { silent: true });
  }
  loading.value = false;
}

async function createTask() {
  if (!canCreate.value) return;
  action.value = "create";
  errorMessage.value = "";
  successMessage.value = "";
  try {
    const payload = {
      database_id: databaseId.value,
      book_id: bookId.value,
      operation: form.value.operation,
      prompt: form.value.prompt.trim(),
      negative_prompt: form.value.negative_prompt.trim(),
      parameters: {
        width: Number(form.value.width),
        height: Number(form.value.height),
        steps: Number(form.value.steps),
        guidance_scale: Number(form.value.guidance_scale),
        strength: Number(form.value.strength),
      },
      seed: form.value.seed === "" ? null : Number(form.value.seed),
      source_asset_id: sourceRequired.value ? form.value.source_asset_id : null,
      model_profile_id: form.value.model_profile_id || null,
      requested_backend: form.value.requested_backend,
      allow_cloud_upload: Boolean(form.value.allow_cloud_upload),
    };
    const response = await createMediaGenerationTask(payload);
    selectedTask.value = response.task;
    successMessage.value = t("图像生成任务已创建");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "图像生成任务创建失败");
  } finally {
    action.value = "";
  }
}

async function openTask(task, { silent = false } = {}) {
  if (!silent) action.value = `detail:${task.task_id}`;
  try {
    const [taskResponse, eventResponse] = await Promise.all([
      getMediaGenerationTask(task.task_id, databaseId.value),
      listMediaGenerationEvents(task.task_id, databaseId.value),
    ]);
    selectedTask.value = taskResponse.task;
    events.value = eventResponse.events || [];
  } catch (error) {
    if (!silent) errorMessage.value = safeMessage(error, "图像任务详情加载失败");
  } finally {
    if (!silent) action.value = "";
  }
}

async function cancelTask(task) {
  action.value = `cancel:${task.task_id}`;
  try {
    selectedTask.value = (await cancelMediaGenerationTask(task.task_id, databaseId.value)).task;
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "图像任务取消失败");
  } finally {
    action.value = "";
  }
}

async function retryTask(task) {
  action.value = `retry:${task.task_id}`;
  try {
    selectedTask.value = (await retryMediaGenerationTask(task.task_id, databaseId.value)).task;
    successMessage.value = t("图像重试任务已创建");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "图像任务重试失败");
  } finally {
    action.value = "";
  }
}

async function publishOutput(task) {
  if (!task?.task_id || !store.activeChapter?.content_group_id) return;
  action.value = `publish:${task.task_id}`;
  errorMessage.value = "";
  successMessage.value = "";
  try {
    await publishMediaGenerationTask(task.task_id, databaseId.value, {
      book_id: bookId.value,
      target_type: "content_group",
      target_id: store.activeChapter.content_group_id,
      binding_type: "chapter_illustration",
    });
    successMessage.value = t("图像已批准并绑定到当前章节组");
    await openTask(task, { silent: true });
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "图像发布失败");
  } finally {
    action.value = "";
  }
}

watch([databaseId, bookId], () => refresh(), { immediate: true });
watch(() => form.value.operation, (operation) => {
  if (operation === "image.generate") form.value.source_asset_id = "";
});
watch(() => form.value.width, (size) => {
  form.value.height = size;
});
watch(() => form.value.model_profile_id, () => {
  if (!cloudConfirmationRequired.value) form.value.allow_cloud_upload = false;
});

onMounted(() => {
  pollTimer = window.setInterval(() => {
    if (activeTasks.value && document.visibilityState === "visible") refresh({ silent: true });
  }, 2200);
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<template>
  <section class="generation-panel">
    <header class="panel-heading">
      <div>
        <span class="heading-icon"><WandSparkles :size="20" /></span>
        <div><h2>{{ t("图像生成") }}</h2><p>{{ t("生成结果进入临时资产，批准后才能绑定章节") }}</p></div>
      </div>
      <button class="icon-button" type="button" :title="t('刷新')" :disabled="loading" @click="refresh()">
        <RefreshCw :size="16" :class="{ spinning: loading }" />
      </button>
    </header>

    <div v-if="!hasScope" class="empty-state">{{ t("请先选择世界库和作品") }}</div>
    <div v-else class="generation-layout">
      <form class="generation-form" @submit.prevent="createTask">
        <label>
          <span>{{ t("生成方式") }}</span>
          <select v-model="form.operation">
            <option value="image.generate">{{ t("文生图") }}</option>
            <option value="image.img2img">{{ t("图生图") }}</option>
            <option value="image.enhance">{{ t("图像增强") }}</option>
          </select>
        </label>
        <label v-if="sourceRequired">
          <span>{{ t("源图像") }}</span>
          <select v-model="form.source_asset_id" required>
            <option value="">{{ t("选择已批准图像") }}</option>
            <option v-for="asset in imageAssets" :key="asset.asset_id" :value="asset.asset_id">
              {{ asset.original_filename }}
            </option>
          </select>
        </label>
        <label class="wide-field">
          <span>{{ t("画面描述") }}</span>
          <textarea v-model="form.prompt" maxlength="6000" rows="5" required />
        </label>
        <label class="wide-field">
          <span>{{ t("排除内容") }}</span>
          <textarea v-model="form.negative_prompt" maxlength="3000" rows="2" />
        </label>
        <label>
          <span>{{ t("图像尺寸") }}</span>
          <select v-model.number="form.width">
            <option :value="512">512 × 512</option>
            <option :value="768">768 × 768</option>
            <option :value="1024">1024 × 1024</option>
          </select>
        </label>
        <label>
          <span>{{ t("执行目标") }}</span>
          <select v-model="form.model_profile_id">
            <option value="">{{ t("自动路由 / 默认本地包") }}</option>
            <option v-for="profile in modelProfiles" :key="profile.id" :value="profile.id">
              {{ profile.display_name }} · {{ profile.provider_model_name }}
            </option>
          </select>
        </label>
        <label>
          <span>{{ t("硬件后端") }}</span>
          <select v-model="form.requested_backend">
            <option value="auto">{{ t("自动选择") }}</option>
            <option value="rocm_pytorch">ROCm / PyTorch</option>
            <option value="cuda">CUDA</option>
          </select>
        </label>
        <label>
          <span>{{ t("随机种子") }}</span>
          <input v-model="form.seed" type="number" min="0" step="1" :placeholder="t('自动')" />
        </label>
        <label class="range-field">
          <span>{{ t("采样步数") }} <b>{{ form.steps }}</b></span>
          <input v-model.number="form.steps" type="range" min="1" max="100" step="1" />
        </label>
        <label class="range-field">
          <span>{{ t("引导强度") }} <b>{{ form.guidance_scale }}</b></span>
          <input v-model.number="form.guidance_scale" type="range" min="1" max="20" step="0.5" />
        </label>
        <label v-if="sourceRequired" class="range-field wide-field">
          <span>{{ t("源图影响") }} <b>{{ form.strength }}</b></span>
          <input v-model.number="form.strength" type="range" min="0.05" max="1" step="0.05" />
        </label>
        <label v-if="cloudConfirmationRequired" class="consent-field wide-field">
          <input v-model="form.allow_cloud_upload" type="checkbox" />
          <span>{{ t("允许将提示词和源图发送到所选云端模型") }}</span>
        </label>
        <p v-if="contract?.default_native_package" class="package-state wide-field">
          {{ contract.default_native_package.display_name || contract.default_native_package.package_id }}
          · {{ t(contract.default_native_package.installation_status || "未知状态") }}
        </p>
        <p v-if="errorMessage" class="feedback danger wide-field"><AlertTriangle :size="14" />{{ errorMessage }}</p>
        <p v-if="successMessage" class="feedback positive wide-field"><CheckCircle2 :size="14" />{{ successMessage }}</p>
        <button class="create-button wide-field" type="submit" :disabled="!canCreate">
          <WandSparkles :size="16" />{{ t(action === "create" ? "正在创建任务" : "开始生成") }}
        </button>
      </form>

      <div class="task-column">
        <div class="task-list">
          <button
            v-for="task in tasks"
            :key="task.task_id"
            type="button"
            :class="{ selected: selectedTask?.task_id === task.task_id }"
            @click="openTask(task)"
          >
            <span><strong>{{ t(OPERATION_LABELS[task.operation] || task.operation) }}</strong><small>{{ formatTime(task.created_at) }}</small></span>
            <span class="progress"><i :style="{ width: `${Math.round((task.progress || 0) * 100)}%` }"></i></span>
            <em :class="taskTone(task.status)">{{ t(STATUS_LABELS[task.status] || task.status) }}</em>
          </button>
          <div v-if="!tasks.length && !loading" class="empty-state compact">{{ t("尚无图像生成任务") }}</div>
        </div>

        <aside v-if="selectedTask" class="task-detail">
          <header>
            <div><small>{{ t("任务详情") }}</small><strong>{{ t(OPERATION_LABELS[selectedTask.operation] || selectedTask.operation) }}</strong></div>
            <em :class="taskTone(selectedTask.status)">{{ t(STATUS_LABELS[selectedTask.status] || selectedTask.status) }}</em>
          </header>
          <dl>
            <div><dt>{{ t("进度") }}</dt><dd>{{ Math.round((selectedTask.progress || 0) * 100) }}%</dd></div>
            <div><dt>{{ t("执行目标") }}</dt><dd>{{ selectedTask.provider_model_name || selectedTask.package_id || t("自动路由") }}</dd></div>
            <div><dt>{{ t("请求后端") }}</dt><dd>{{ selectedTask.requested_backend }}</dd></div>
            <div><dt>{{ t("实际后端") }}</dt><dd>{{ selectedTask.effective_backend || t("尚未确定") }}</dd></div>
          </dl>
          <p v-if="selectedTask.error_code" class="task-error">
            <strong>{{ selectedTask.error_code }}</strong><span>{{ selectedTask.error_message }}</span>
          </p>
          <div v-if="events.length" class="event-list">
            <small>{{ t("任务事件") }}</small>
            <span v-for="event in events.slice(-6)" :key="event.sequence">
              {{ event.sequence }} · {{ event.event }}
            </span>
          </div>
          <div class="detail-actions">
            <button
              v-if="['queued','running','cancelling'].includes(selectedTask.status)"
              type="button"
              class="secondary-button danger"
              @click="cancelTask(selectedTask)"
            ><Square :size="14" />{{ t("取消任务") }}</button>
            <button
              v-if="['failed','cancelled'].includes(selectedTask.status)"
              type="button"
              class="secondary-button"
              @click="retryTask(selectedTask)"
            ><RotateCcw :size="14" />{{ t("重试") }}</button>
            <button
              v-if="selectedTask.output_asset_id"
              type="button"
              class="secondary-button"
              :disabled="!canPublishSelected || action === `publish:${selectedTask.task_id}`"
              @click="publishOutput(selectedTask)"
            ><Link2 :size="14" />{{ t(action === `publish:${selectedTask.task_id}` ? "正在发布" : "批准并绑定章节组") }}</button>
            <button
              v-if="selectedTask.output_asset_id"
              type="button"
              class="secondary-button"
              @click="emit('open-assets')"
            ><ExternalLink :size="14" />{{ t("前往资产审批") }}</button>
          </div>
        </aside>
        <div v-else class="detail-placeholder"><Image :size="28" />{{ t("选择任务查看进度和结果") }}</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.generation-panel { min-height: 610px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); }
.panel-heading, .panel-heading > div, .feedback, .detail-actions { display: flex; align-items: center; }
.panel-heading { min-height: 58px; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding: 9px 12px; }
.panel-heading > div { gap: 10px; min-width: 0; }
.heading-icon { width: 36px; height: 36px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: var(--accent-soft); color: var(--accent); }
.panel-heading h2 { margin: 0 0 3px; font-size: 14px; }
.panel-heading p { margin: 0; color: var(--text-muted); font-size: 10px; }
.icon-button { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.generation-layout { display: grid; grid-template-columns: minmax(320px,.8fr) minmax(340px,1.2fr); min-height: 550px; }
.generation-form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-content: start; gap: 11px; border-right: 1px solid var(--border); padding: 14px; }
.generation-form label { min-width: 0; display: grid; gap: 5px; color: var(--text-secondary); font-size: 10px; }
.generation-form label > span { display: flex; justify-content: space-between; gap: 8px; }
.generation-form input:not([type="range"],[type="checkbox"]), .generation-form select, .generation-form textarea { width: 100%; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-primary); padding: 8px 9px; font: inherit; resize: vertical; }
.generation-form input:focus, .generation-form select:focus, .generation-form textarea:focus { outline: 2px solid rgba(91,72,208,.16); border-color: var(--accent); }
.wide-field { grid-column: 1 / -1; }
.range-field input { width: 100%; accent-color: var(--accent); }
.consent-field { grid-template-columns: auto minmax(0,1fr); align-items: center; }
.consent-field input { accent-color: var(--accent); }
.package-state { margin: 0; border-radius: 7px; background: var(--bg-secondary); color: var(--text-muted); padding: 8px 10px; font-size: 10px; }
.feedback { gap: 6px; margin: 0; border-radius: 7px; padding: 8px 10px; font-size: 10px; }
.feedback.danger, .task-error { background: #fff0f0; color: #a33f3f; }
.feedback.positive { background: #edf9f3; color: #167251; }
.create-button, .secondary-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 34px; border-radius: 7px; cursor: pointer; font-size: 11px; font-weight: 700; }
.create-button { border: 1px solid var(--accent); background: var(--accent); color: #fff; }
.create-button:disabled { opacity: .5; cursor: not-allowed; }
.task-column { min-width: 0; display: grid; grid-template-columns: minmax(0,1fr) minmax(240px,.72fr); align-items: start; }
.task-list { max-height: 700px; overflow: auto; border-right: 1px solid var(--border); }
.task-list > button { width: 100%; min-height: 66px; display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 8px 10px; border: 0; border-bottom: 1px solid var(--border); background: #fff; color: inherit; padding: 10px; text-align: left; cursor: pointer; }
.task-list > button:hover, .task-list > button.selected { background: var(--accent-soft); }
.task-list button > span:first-child { min-width: 0; display: grid; gap: 3px; }
.task-list strong, .task-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-list strong { font-size: 10px; }
.task-list small { color: var(--text-muted); font-size: 9px; }
.progress { grid-column: 1 / -1; height: 5px; overflow: hidden; border-radius: 99px; background: #e5e5ea; }
.progress i { display: block; height: 100%; background: var(--accent); }
.task-list em, .task-detail em { width: max-content; border-radius: 999px; padding: 4px 7px; font-size: 9px; font-style: normal; font-weight: 700; white-space: nowrap; }
em.positive { background: #e7f8f0; color: #15704f; }
em.active { background: #e8f0fa; color: #326398; }
em.warning { background: #fff6e5; color: #95651b; }
em.danger { background: #fff0f0; color: #a33f3f; }
em.muted { background: #f0eef4; color: var(--text-secondary); }
.task-detail { min-width: 0; display: grid; gap: 11px; padding: 13px; }
.task-detail header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.task-detail header div { min-width: 0; display: grid; gap: 3px; }
.task-detail header small, .event-list > small { color: var(--text-muted); font-size: 9px; }
.task-detail header strong { font-size: 12px; }
.task-detail dl { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 7px; margin: 0; }
.task-detail dl div { min-width: 0; display: grid; gap: 3px; border-radius: 6px; background: var(--bg-secondary); padding: 8px; }
.task-detail dt { color: var(--text-muted); font-size: 8px; }
.task-detail dd { overflow: hidden; margin: 0; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.task-error, .event-list { display: grid; gap: 4px; margin: 0; border-radius: 7px; padding: 9px; font-size: 9px; }
.event-list { background: var(--bg-secondary); color: var(--text-secondary); }
.detail-actions { flex-wrap: wrap; gap: 7px; }
.secondary-button { border: 1px solid var(--border); background: #fff; color: var(--text-secondary); padding: 6px 9px; }
.secondary-button.danger { color: #a33f3f; }
.detail-placeholder, .empty-state { min-height: 220px; display: grid; place-items: center; align-content: center; gap: 8px; color: var(--text-muted); padding: 20px; text-align: center; font-size: 10px; }
.empty-state.compact { min-height: 120px; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) {
  .generation-layout, .task-column { grid-template-columns: 1fr; }
  .generation-form, .task-list { border-right: 0; border-bottom: 1px solid var(--border); }
  .task-list { max-height: 260px; }
}
@media (max-width: 620px) {
  .generation-form { grid-template-columns: 1fr; }
  .wide-field { grid-column: auto; }
  .task-detail dl { grid-template-columns: 1fr; }
}
</style>
