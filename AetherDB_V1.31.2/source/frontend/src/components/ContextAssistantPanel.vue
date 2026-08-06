<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  Bot,
  Check,
  CloudUpload,
  FileSearch,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  Square,
  Trash2,
} from "@lucide/vue";
import {
  approveContextCandidates,
  buildEvidencePack,
  createContextMap,
} from "../api/context.js";
import {
  confirmModelDataManifest,
  confirmModelRecovery,
  createModelDataManifest,
  executeModelStream,
} from "../api/models.js";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();

const taskTypes = [
  { value: "creative_assist", label: "创作辅助" },
  { value: "world_consistency", label: "设定一致性" },
  { value: "rag_answer", label: "资料问答" },
];

const phase = ref("context");
const taskType = ref("creative_assist");
const query = ref("");
const prompt = ref("");
const taskId = ref("");
const candidates = ref([]);
const selectedIds = ref([]);
const evidencePack = ref(null);
const evidenceTokenLimit = ref(3072);
const mapping = ref(false);
const approving = ref(false);
const generating = ref(false);
const status = ref("idle");
const errorMessage = ref("");
const errorCode = ref("");
const thinkingText = ref("");
const finalText = ref("");
const previousPartial = ref("");
const usage = ref(null);
const routeInfo = ref(null);
const recoveryTicket = ref("");
const recoveryCandidates = ref([]);
const recoveryKind = ref("");
const confirmingModelId = ref("");
const executionPayload = ref(null);
const dataManifest = ref(null);
const pendingExecutionPayload = ref(null);
const confirmingManifest = ref(false);
let streamController = null;

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const chapterId = computed(() => store.activeChapter?.chapter_id || "");
const canMap = computed(() => Boolean(databaseId.value && bookId.value && query.value.trim()));
const canReview = computed(() => candidates.value.length > 0 && !approving.value);
const canExecute = computed(() => (
  !store.authStatus || store.hasCapability("execute_creation_assistance")
));
const canGenerate = computed(() => Boolean(
  evidencePack.value
  && prompt.value.trim()
  && canExecute.value
  && !generating.value
  && !pendingExecutionPayload.value
));
const selectedCount = computed(() => selectedIds.value.length);
const evidenceCount = computed(() => evidencePack.value?.items?.length || 0);
const statusLabel = computed(() => {
  const labels = {
    idle: "等待生成",
    routing: "正在解析唯一模型",
    running: "正在生成",
    done: "生成完成",
    cancelled: "生成已取消",
    error: "生成中断",
    selection: "等待选择模型",
    cloud_confirmation: "等待确认云端发送",
  };
  return t(labels[status.value] || "等待生成");
});

function safeMessage(error, fallback) {
  return error?.detail?.message || error?.message || t(fallback);
}

function defaultPrompt() {
  return t("请基于已审批资料续写当前章节，并保持人物、时间与世界设定一致。");
}

function clearRecovery() {
  recoveryTicket.value = "";
  recoveryCandidates.value = [];
  recoveryKind.value = "";
  confirmingModelId.value = "";
}

function clearOutput() {
  thinkingText.value = "";
  finalText.value = "";
  previousPartial.value = "";
  usage.value = null;
  routeInfo.value = null;
  errorMessage.value = "";
  errorCode.value = "";
  status.value = "idle";
  executionPayload.value = null;
  dataManifest.value = null;
  pendingExecutionPayload.value = null;
  confirmingManifest.value = false;
  clearRecovery();
}

function cancelGeneration() {
  streamController?.abort();
  streamController = null;
  if (generating.value) {
    status.value = "cancelled";
    generating.value = false;
  }
}

function resetWorkflow() {
  cancelGeneration();
  phase.value = "context";
  taskId.value = "";
  candidates.value = [];
  selectedIds.value = [];
  evidencePack.value = null;
  errorMessage.value = "";
  errorCode.value = "";
  clearOutput();
}

function toggleCandidate(candidateId) {
  selectedIds.value = selectedIds.value.includes(candidateId)
    ? selectedIds.value.filter((item) => item !== candidateId)
    : [...selectedIds.value, candidateId];
}

async function mapContext() {
  if (!canMap.value) return;
  cancelGeneration();
  mapping.value = true;
  errorMessage.value = "";
  errorCode.value = "";
  evidencePack.value = null;
  clearOutput();
  try {
    const response = await createContextMap({
      task_type: taskType.value,
      database_id: databaseId.value,
      book_id: bookId.value,
      chapter_id: chapterId.value || null,
      language_code: store.chapterLanguageCode || "zh-CN",
      include_future_knowledge: false,
      needs: [
        {
          context_type: "mentioned_entities",
          query: query.value.trim(),
          reason: "Resolve entities explicitly approved by the author.",
          required: true,
        },
        {
          context_type: "recent_chapter_summary",
          query: query.value.trim(),
          reason: "Retrieve chapter context in the active content language.",
          required: false,
        },
        {
          context_type: "timeline_constraints",
          query: query.value.trim(),
          reason: "Check temporal constraints without exposing future knowledge.",
          required: false,
        },
      ],
    });
    taskId.value = response?.task_id || "";
    candidates.value = response?.candidates || [];
    selectedIds.value = candidates.value
      .filter((item) => Boolean(item.approved))
      .map((item) => item.candidate_id);
    phase.value = "review";
  } catch (error) {
    errorMessage.value = safeMessage(error, "上下文检索失败");
  } finally {
    mapping.value = false;
  }
}

function evidenceBudget() {
  const reservedEvidence = Math.max(256, Math.min(Number(evidenceTokenLimit.value) || 3072, 6144));
  evidenceTokenLimit.value = reservedEvidence;
  return {
    total_context_tokens: 16384,
    reserved_instruction: 512,
    reserved_current_text: 4096,
    reserved_evidence: reservedEvidence,
    reserved_output: 4096,
  };
}

async function approveAndBuild() {
  if (!canReview.value || !taskId.value) return;
  approving.value = true;
  errorMessage.value = "";
  try {
    const selected = new Set(selectedIds.value);
    await approveContextCandidates(
      taskId.value,
      databaseId.value,
      candidates.value.map((item) => ({
        candidate_id: item.candidate_id,
        approved: selected.has(item.candidate_id),
      })),
    );
    evidencePack.value = await buildEvidencePack(
      taskId.value,
      databaseId.value,
      evidenceBudget(),
    );
    phase.value = "generate";
  } catch (error) {
    errorMessage.value = safeMessage(error, "证据包构建失败");
  } finally {
    approving.value = false;
  }
}

function newExecutionId() {
  const suffix = globalThis.crypto?.randomUUID?.().replaceAll("-", "")
    || `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `ui_${suffix.slice(0, 48)}`;
}

function buildExecutionPayload() {
  const currentText = String(store.draftContent || "").trim();
  const content = currentText
    ? `${prompt.value.trim()}\n\n[CURRENT CHAPTER]\n${currentText.slice(-12000)}`
    : prompt.value.trim();
  return {
    task_id: newExecutionId(),
    task_type: taskType.value,
    database_id: databaseId.value,
    book_id: bookId.value,
    messages: [{ role: "user", content }],
    requires_json: false,
    context_task_id: taskId.value,
    evidence_budget: evidenceBudget(),
  };
}

function applyStreamEvent(event) {
  const payload = event?.payload || {};
  if (event.event === "routing_resolved") {
    routeInfo.value = payload;
    status.value = payload.status === "resolved" ? "running" : "selection";
    if (payload.recovery_ticket) {
      recoveryTicket.value = payload.recovery_ticket;
      recoveryCandidates.value = payload.candidates || [];
      recoveryKind.value = "ambiguous_selection";
    }
  } else if (event.event === "thinking_delta") {
    thinkingText.value += String(payload.delta || "");
  } else if (event.event === "final_delta") {
    finalText.value += String(payload.delta || "");
  } else if (event.event === "usage_update") {
    usage.value = payload.usage || null;
  } else if (event.event === "fallback_required") {
    recoveryTicket.value = payload.recovery_ticket || "";
    recoveryCandidates.value = payload.candidates || [];
    recoveryKind.value = "fallback_confirmation";
    errorCode.value = payload.error_code || "";
    status.value = "selection";
  } else if (event.event === "stream_error") {
    errorCode.value = payload.error_code || "MODEL_STREAM_ERROR";
    errorMessage.value = t("模型执行未完成，请检查路由状态或选择可用模型。");
    status.value = recoveryCandidates.value.length ? "selection" : "error";
  } else if (event.event === "task_done") {
    status.value = "done";
  } else if (event.event === "task_cancelled") {
    status.value = "cancelled";
  }
}

async function executePreparedPayload(payload) {
  streamController = new AbortController();
  status.value = "running";
  await executeModelStream(payload, {
    signal: streamController.signal,
    onEvent: applyStreamEvent,
  });
}

async function runGeneration(recovery = null) {
  if ((!canGenerate.value && !recovery) || generating.value) return;
  if (!recovery) {
    clearOutput();
    executionPayload.value = buildExecutionPayload();
  }
  const payload = {
    ...executionPayload.value,
    ...(recovery || {}),
  };
  delete payload.data_manifest_id;
  generating.value = true;
  status.value = "routing";
  errorMessage.value = "";
  errorCode.value = "";
  try {
    const response = await createModelDataManifest(payload);
    dataManifest.value = response.manifest;
    const preparedPayload = {
      ...payload,
      data_manifest_id: response.manifest.data_manifest_id,
    };
    executionPayload.value = preparedPayload;
    if (
      response.manifest.cloud_confirmation_required
      && response.manifest.status === "pending"
    ) {
      pendingExecutionPayload.value = preparedPayload;
      status.value = "cloud_confirmation";
      return;
    }
    await executePreparedPayload(preparedPayload);
  } catch (error) {
    if (error?.code === "REQUEST_CANCELLED") {
      status.value = "cancelled";
    } else if (
      error?.code === "MODEL_ROUTE_AMBIGUOUS"
      && error?.detail?.candidates?.length
    ) {
      recoveryCandidates.value = error.detail.candidates;
      recoveryKind.value = "initial_selection";
      status.value = "selection";
    } else {
      status.value = "error";
      errorCode.value = error?.code || "MODEL_EXECUTION_PREPARE_FAILED";
      errorMessage.value = safeMessage(error, "模型执行准备失败");
    }
  } finally {
    generating.value = false;
    streamController = null;
  }
}

async function confirmCloudManifest() {
  if (
    !dataManifest.value?.data_manifest_id
    || !pendingExecutionPayload.value
    || confirmingManifest.value
  ) return;
  confirmingManifest.value = true;
  generating.value = true;
  errorMessage.value = "";
  try {
    const response = await confirmModelDataManifest(dataManifest.value.data_manifest_id);
    dataManifest.value = response.manifest;
    const payload = pendingExecutionPayload.value;
    pendingExecutionPayload.value = null;
    await executePreparedPayload(payload);
  } catch (error) {
    status.value = "error";
    errorCode.value = error?.code || "DATA_MANIFEST_CONFIRM_FAILED";
    errorMessage.value = safeMessage(error, "云端发送清单确认失败");
  } finally {
    confirmingManifest.value = false;
    generating.value = false;
    streamController = null;
  }
}

function cancelCloudManifest() {
  pendingExecutionPayload.value = null;
  dataManifest.value = null;
  status.value = "idle";
}

async function chooseRecoveryModel(candidate) {
  if (!candidate?.available || confirmingModelId.value) return;
  confirmingModelId.value = candidate.model_profile_id;
  errorMessage.value = "";
  try {
    if (recoveryKind.value === "initial_selection") {
      clearRecovery();
      await runGeneration({
        user_selected_model_id: candidate.model_profile_id,
      });
      return;
    }
    if (!recoveryTicket.value) return;
    await confirmModelRecovery(recoveryTicket.value, candidate.model_profile_id);
    if (finalText.value) previousPartial.value = finalText.value;
    thinkingText.value = "";
    finalText.value = "";
    usage.value = null;
    const ticket = recoveryTicket.value;
    clearRecovery();
    await runGeneration({
      recovery_ticket: ticket,
      user_selected_model_id: candidate.model_profile_id,
    });
  } catch (error) {
    errorMessage.value = safeMessage(error, "模型选择确认失败");
    status.value = "selection";
  } finally {
    confirmingModelId.value = "";
  }
}

watch(
  () => [databaseId.value, bookId.value, chapterId.value],
  () => {
    resetWorkflow();
    query.value = store.chapterTitle && store.activeChapter ? store.chapterTitle : "";
    prompt.value = defaultPrompt();
  },
  { immediate: true },
);

onBeforeUnmount(cancelGeneration);
</script>

<template>
  <section class="context-assistant">
    <header class="assistant-heading">
      <div>
        <span><Bot :size="18" /></span>
        <div>
          <h2>{{ t("作者审批上下文") }}</h2>
          <p>{{ t("本地检索、证据审批与模型生成") }}</p>
        </div>
      </div>
      <button type="button" :title="t('重置工作流')" :disabled="mapping || approving || generating" @click="resetWorkflow">
        <RefreshCw :size="16" />
      </button>
    </header>

    <nav class="workflow-tabs" :aria-label="t('上下文工作流')">
      <button type="button" :class="{ active: phase === 'context', complete: taskId }" @click="phase = 'context'">
        <span>1</span>{{ t("检索") }}
      </button>
      <button type="button" :class="{ active: phase === 'review', complete: evidencePack }" :disabled="!taskId" @click="phase = 'review'">
        <span>2</span>{{ t("审批") }}
      </button>
      <button type="button" :class="{ active: phase === 'generate' }" :disabled="!evidencePack" @click="phase = 'generate'">
        <span>3</span>{{ t("生成") }}
      </button>
    </nav>

    <div v-if="phase === 'context'" class="phase-body">
      <div class="task-segments" role="group" :aria-label="t('任务类型')">
        <button
          v-for="option in taskTypes"
          :key="option.value"
          type="button"
          :class="{ active: taskType === option.value }"
          @click="taskType = option.value"
        >
          {{ t(option.label) }}
        </button>
      </div>
      <label class="field">
        <span>{{ t("检索主题") }}</span>
        <input v-model.trim="query" type="text" maxlength="200" :placeholder="t('输入人物、地点、事件或章节主题')" @keyup.enter="mapContext" />
      </label>
      <div class="scope-line">
        <span>{{ t("作品") }} · {{ store.activeBook?.title || t("未选择") }}</span>
        <span>{{ t("语言") }} · {{ store.chapterLanguageCode || "zh-CN" }}</span>
        <span>{{ t("未来知识") }} · {{ t("关闭") }}</span>
      </div>
      <button class="primary-action" type="button" :disabled="!canMap || mapping" @click="mapContext">
        <LoaderCircle v-if="mapping" :size="16" class="spinning" />
        <FileSearch v-else :size="16" />
        {{ t(mapping ? "正在检索" : "检索候选资料") }}
      </button>
    </div>

    <div v-else-if="phase === 'review'" class="phase-body review-phase">
      <header class="phase-summary">
        <div>
          <strong>{{ t("候选资料") }}</strong>
          <small>{{ t("已选择 {selected} / {total}", { selected: selectedCount, total: candidates.length }) }}</small>
        </div>
        <label>
          <span>{{ t("证据预算") }}</span>
          <input v-model.number="evidenceTokenLimit" type="number" min="256" max="6144" step="256" />
        </label>
      </header>

      <div v-if="candidates.length" class="candidate-list">
        <label
          v-for="candidate in candidates"
          :key="candidate.candidate_id"
          class="candidate-row"
          :class="{ selected: selectedIds.includes(candidate.candidate_id) }"
        >
          <input
            type="checkbox"
            :checked="selectedIds.includes(candidate.candidate_id)"
            @change="toggleCandidate(candidate.candidate_id)"
          />
          <span class="candidate-check"><Check :size="13" /></span>
          <span class="candidate-content">
            <span>
              <strong>{{ candidate.title || candidate.source_id }}</strong>
              <small>{{ t(candidate.priority === 0 ? "必需候选" : "可选候选") }} · {{ candidate.source_type }} · {{ candidate.estimated_tokens || 0 }} tokens</small>
            </span>
            <p>{{ candidate.summary || t("无摘要") }}</p>
            <span v-if="candidate.risk_flags?.length" class="risk-line">
              <AlertTriangle :size="12" />{{ candidate.risk_flags.join(", ") }}
            </span>
          </span>
        </label>
      </div>
      <div v-else class="empty-state">
        <FileSearch :size="24" />
        <strong>{{ t("未找到候选资料") }}</strong>
        <button type="button" @click="phase = 'context'">{{ t("调整检索主题") }}</button>
      </div>

      <button v-if="candidates.length" class="primary-action" type="button" :disabled="!canReview" @click="approveAndBuild">
        <LoaderCircle v-if="approving" :size="16" class="spinning" />
        <ShieldCheck v-else :size="16" />
        {{ t(approving ? "正在构建证据包" : "提交审批并构建证据包") }}
      </button>
    </div>

    <div v-else class="phase-body generate-phase">
      <div class="evidence-summary">
        <ShieldCheck :size="18" />
        <span>
          <strong>{{ t("证据包已锁定") }}</strong>
          <small>{{ t("{count} 项资料 · {tokens} tokens", { count: evidenceCount, tokens: evidencePack?.used_tokens || 0 }) }}</small>
        </span>
        <button type="button" @click="phase = 'review'">{{ t("重新审批") }}</button>
      </div>

      <label class="field prompt-field">
        <span>{{ t("创作请求") }}</span>
        <textarea v-model.trim="prompt" maxlength="5000" :placeholder="t('输入希望模型完成的创作任务')"></textarea>
      </label>

      <section v-if="pendingExecutionPayload && dataManifest" class="cloud-manifest">
        <header>
          <CloudUpload :size="18" />
          <span>
            <strong>{{ t("确认云端发送清单") }}</strong>
            <small>{{ t("摘要由服务端根据实际请求生成，确认前不会发送到云端。") }}</small>
          </span>
        </header>
        <dl>
          <div><dt>{{ t("任务标识") }}</dt><dd>{{ dataManifest.task_id }}</dd></div>
          <div><dt>{{ t("供应商") }}</dt><dd>{{ dataManifest.provider_id }}</dd></div>
          <div><dt>{{ t("模型") }}</dt><dd>{{ dataManifest.model_id }}</dd></div>
          <div><dt>{{ t("正文指纹") }}</dt><dd>{{ dataManifest.selected_text_hash }}</dd></div>
          <div><dt>{{ t("预计载荷") }}</dt><dd>{{ dataManifest.estimated_payload_size }} bytes</dd></div>
          <div><dt>{{ t("创建时间") }}</dt><dd>{{ dataManifest.created_at }}</dd></div>
          <div><dt>{{ t("有效期") }}</dt><dd>{{ dataManifest.expires_at }}</dd></div>
          <div><dt>{{ t("状态") }}</dt><dd>{{ dataManifest.status }}</dd></div>
          <div><dt>{{ t("包含正文") }}</dt><dd>{{ t(dataManifest.contains_original_text ? "是" : "否") }}</dd></div>
          <div><dt>{{ t("包含媒体") }}</dt><dd>{{ t(dataManifest.contains_media ? "是" : "否") }}</dd></div>
          <div><dt>{{ t("审批上下文") }}</dt><dd>{{ dataManifest.approved_context_ids?.length || 0 }}</dd></div>
          <div><dt>{{ t("已选资产") }}</dt><dd>{{ dataManifest.selected_asset_ids?.length || 0 }}</dd></div>
        </dl>
        <code>{{ dataManifest.data_manifest_id }}</code>
        <div>
          <button type="button" class="stop-action" :disabled="confirmingManifest" @click="cancelCloudManifest">
            <Square :size="14" />{{ t("取消发送") }}
          </button>
          <button type="button" class="primary-action" :disabled="confirmingManifest" @click="confirmCloudManifest">
            <LoaderCircle v-if="confirmingManifest" :size="15" class="spinning" />
            <ShieldCheck v-else :size="15" />
            {{ t("确认清单并发送") }}
          </button>
        </div>
      </section>

      <div class="generation-actions">
        <button v-if="!generating" class="primary-action" type="button" :disabled="!canGenerate" @click="runGeneration()">
          <Play :size="16" />{{ t(finalText ? "重新生成" : "开始生成") }}
        </button>
        <button v-else class="stop-action" type="button" @click="cancelGeneration">
          <Square :size="14" />{{ t("停止生成") }}
        </button>
        <span class="generation-status" :class="status">
          <LoaderCircle v-if="generating" :size="14" class="spinning" />
          <Check v-else-if="status === 'done'" :size="14" />
          <AlertTriangle v-else-if="['error', 'selection'].includes(status)" :size="14" />
          {{ statusLabel }}
        </span>
      </div>

      <section v-if="recoveryCandidates.length" class="recovery-panel">
        <header>
          <strong>{{ t(recoveryKind === "fallback_confirmation" ? "确认备用模型" : "选择唯一模型") }}</strong>
          <small>{{ t("每次只会执行一个模型") }}</small>
        </header>
        <button
          v-for="candidate in recoveryCandidates"
          :key="candidate.model_profile_id"
          type="button"
          :disabled="!candidate.available || Boolean(confirmingModelId)"
          @click="chooseRecoveryModel(candidate)"
        >
          <span>
            <strong>{{ candidate.display_name }}</strong>
            <small>{{ candidate.provider?.display_name }} · {{ t(candidate.provider?.is_local ? "本地" : "云端") }}</small>
          </span>
          <LoaderCircle v-if="confirmingModelId === candidate.model_profile_id" :size="15" class="spinning" />
          <span v-else>{{ candidate.available ? t("选择") : t("不可用") }}</span>
        </button>
      </section>

      <div v-if="errorMessage" class="error-state">
        <AlertTriangle :size="16" />
        <span><strong>{{ errorCode || t("执行失败") }}</strong><small>{{ errorMessage }}</small></span>
      </div>

      <section v-if="thinkingText" class="stream-section thinking-output">
        <header><strong>{{ t("思考过程") }}</strong></header>
        <pre>{{ thinkingText }}</pre>
      </section>

      <section v-if="previousPartial" class="stream-section partial-output">
        <header>
          <strong>{{ t("上一轮已保留内容") }}</strong>
          <button type="button" :title="t('清除')" @click="previousPartial = ''"><Trash2 :size="14" /></button>
        </header>
        <pre>{{ previousPartial }}</pre>
      </section>

      <section v-if="finalText" class="stream-section final-output">
        <header>
          <strong>{{ t("生成结果") }}</strong>
          <span v-if="usage">{{ t("用量") }} · {{ usage.total_tokens || usage.output_tokens || 0 }} tokens</span>
          <button type="button" :title="t('清除')" @click="finalText = ''"><Trash2 :size="14" /></button>
        </header>
        <pre>{{ finalText }}</pre>
      </section>

      <div v-if="!canExecute" class="permission-state">
        <AlertTriangle :size="16" />{{ t("当前会话没有创作辅助执行权限") }}
      </div>
    </div>

    <p v-if="errorMessage && phase !== 'generate'" class="phase-error">
      <AlertTriangle :size="14" />{{ errorMessage }}
    </p>
  </section>
</template>

<style scoped>
.context-assistant {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,.96);
  box-shadow: var(--soft-shadow);
}
.assistant-heading {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--border);
  padding: 8px 14px;
}
.assistant-heading > div { min-width: 0; display: flex; align-items: center; gap: 10px; }
.assistant-heading > div > span {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border-radius: 7px;
  background: #29253b;
  color: #fff;
}
.assistant-heading h2 { margin: 0; color: var(--text-primary); font-size: 14px; letter-spacing: 0; }
.assistant-heading p { margin: 3px 0 0; color: var(--text-muted); font-size: 10px; }
.assistant-heading > button {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: #fff;
  color: var(--text-secondary);
  cursor: pointer;
}
.assistant-heading > button:disabled { opacity: .45; cursor: not-allowed; }
.workflow-tabs {
  min-height: 46px;
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  border-bottom: 1px solid var(--border);
  background: #fafafa;
}
.workflow-tabs button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 0;
  border-right: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 11px;
}
.workflow-tabs button:last-child { border-right: 0; }
.workflow-tabs button span {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border: 1px solid #cbc8d2;
  border-radius: 50%;
  font-size: 9px;
}
.workflow-tabs button.active { background: #fff; color: var(--accent); font-weight: 700; }
.workflow-tabs button.active span { border-color: var(--accent); background: var(--accent); color: #fff; }
.workflow-tabs button.complete:not(.active) span { border-color: #69ac8b; background: #eaf8f1; color: #157353; }
.workflow-tabs button:disabled { cursor: not-allowed; opacity: .48; }
.phase-body { display: grid; gap: 14px; padding: 18px; }
.task-segments {
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #f5f5f7;
  padding: 4px;
}
.task-segments button {
  min-height: 34px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
}
.task-segments button.active { background: #fff; color: var(--accent); box-shadow: 0 1px 4px rgba(30,25,50,.1); font-weight: 700; }
.field { min-width: 0; display: grid; gap: 6px; color: var(--text-secondary); font-size: 10px; font-weight: 700; }
.field input, .field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 7px;
  outline: none;
  background: #fff;
  color: var(--text-primary);
  padding: 10px 11px;
  font: inherit;
  font-weight: 400;
}
.field input:focus, .field textarea:focus { border-color: #a99ce5; box-shadow: 0 0 0 3px rgba(116,92,191,.1); }
.scope-line { display: flex; flex-wrap: wrap; gap: 7px; }
.scope-line span {
  border: 1px solid var(--border);
  border-radius: 5px;
  background: #f8f8f9;
  color: var(--text-muted);
  padding: 5px 7px;
  font-size: 9px;
}
.primary-action, .stop-action {
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 0;
  border-radius: 7px;
  cursor: pointer;
  padding: 7px 14px;
  font-size: 11px;
  font-weight: 700;
}
.primary-action { background: var(--accent); color: #fff; }
.primary-action:disabled { background: #aaa6b6; cursor: not-allowed; }
.stop-action { background: #a84040; color: #fff; }
.phase-summary { display: flex; align-items: end; justify-content: space-between; gap: 12px; }
.phase-summary > div { display: grid; gap: 3px; }
.phase-summary strong { font-size: 13px; }
.phase-summary small { color: var(--text-muted); font-size: 10px; }
.phase-summary label { display: grid; grid-template-columns: auto 86px; align-items: center; gap: 7px; color: var(--text-muted); font-size: 9px; }
.phase-summary input { min-width: 0; border: 1px solid var(--border); border-radius: 6px; padding: 6px; font-size: 10px; }
.candidate-list { max-height: 470px; display: grid; gap: 7px; overflow: auto; padding-right: 3px; }
.candidate-row {
  min-width: 0;
  display: grid;
  grid-template-columns: auto minmax(0,1fr);
  gap: 9px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #fff;
  cursor: pointer;
  padding: 10px;
}
.candidate-row > input { position: absolute; opacity: 0; pointer-events: none; }
.candidate-row.selected { border-color: #9ad2b6; background: #f4fcf8; }
.candidate-check {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border: 1px solid #c9c6d0;
  border-radius: 5px;
  color: transparent;
}
.candidate-row.selected .candidate-check { border-color: #2e9b70; background: #2e9b70; color: #fff; }
.candidate-content { min-width: 0; display: grid; gap: 6px; }
.candidate-content > span:first-child { min-width: 0; display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.candidate-content strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.candidate-content small { flex: 0 0 auto; color: var(--text-muted); font-size: 9px; }
.candidate-content p { margin: 0; color: var(--text-secondary); overflow-wrap: anywhere; font-size: 10px; line-height: 1.55; }
.risk-line { display: inline-flex; align-items: center; gap: 4px; color: #9a5b18; font-size: 9px; }
.empty-state { min-height: 220px; display: grid; place-items: center; align-content: center; gap: 9px; color: var(--text-muted); }
.empty-state strong { font-size: 12px; }
.empty-state button { border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: 10px; }
.evidence-summary {
  display: grid;
  grid-template-columns: auto minmax(0,1fr) auto;
  align-items: center;
  gap: 9px;
  border-left: 3px solid #2e9b70;
  background: #f0faf5;
  color: #157353;
  padding: 10px 12px;
}
.evidence-summary > span { min-width: 0; display: grid; gap: 2px; }
.evidence-summary strong { font-size: 11px; }
.evidence-summary small { font-size: 9px; opacity: .78; }
.evidence-summary button { border: 0; background: transparent; color: #157353; cursor: pointer; font-size: 9px; }
.prompt-field textarea { min-height: 92px; resize: vertical; line-height: 1.55; }
.cloud-manifest { display: grid; gap: 10px; border-top: 1px solid #dfc98d; border-bottom: 1px solid #dfc98d; background: #fffbef; padding: 12px 0; }
.cloud-manifest > header { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: start; gap: 8px; color: #8b621e; padding-inline: 11px; }
.cloud-manifest > header > span { min-width: 0; display: grid; gap: 3px; }
.cloud-manifest > header strong { font-size: 11px; }
.cloud-manifest > header small { font-size: 9px; line-height: 1.5; }
.cloud-manifest dl { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 6px; margin: 0; padding-inline: 11px; }
.cloud-manifest dl div { min-width: 0; display: grid; gap: 2px; }
.cloud-manifest dt { color: var(--text-muted); font-size: 8px; }
.cloud-manifest dd { overflow: hidden; margin: 0; text-overflow: ellipsis; white-space: nowrap; font-size: 9px; }
.cloud-manifest code { overflow-wrap: anywhere; background: rgba(255,255,255,.7); padding: 7px 11px; font-size: 9px; }
.cloud-manifest > div { display: flex; justify-content: flex-end; gap: 7px; padding-inline: 11px; }
.generation-actions { display: flex; align-items: center; gap: 10px; }
.generation-actions > button { flex: 0 0 auto; min-width: 130px; }
.generation-status { min-width: 0; display: inline-flex; align-items: center; gap: 5px; color: var(--text-muted); font-size: 10px; }
.generation-status.done { color: #157353; }
.generation-status.error, .generation-status.selection, .generation-status.cloud_confirmation { color: #9a5b18; }
.recovery-panel { display: grid; gap: 6px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 12px 0; }
.recovery-panel header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.recovery-panel header strong { font-size: 11px; }
.recovery-panel header small { color: var(--text-muted); font-size: 9px; }
.recovery-panel > button {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0,1fr) auto;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #fff;
  cursor: pointer;
  padding: 9px 10px;
  text-align: left;
}
.recovery-panel > button:disabled { background: #f5f5f6; cursor: not-allowed; opacity: .65; }
.recovery-panel > button > span:first-child { min-width: 0; display: grid; gap: 2px; }
.recovery-panel > button strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.recovery-panel > button small, .recovery-panel > button > span:last-child { color: var(--text-muted); font-size: 9px; }
.error-state, .permission-state {
  display: grid;
  grid-template-columns: auto minmax(0,1fr);
  align-items: start;
  gap: 8px;
  background: #fff6e9;
  color: #9a5b18;
  padding: 9px 11px;
}
.error-state span { min-width: 0; display: grid; gap: 2px; }
.error-state strong { font-size: 10px; }
.error-state small { overflow-wrap: anywhere; font-size: 9px; line-height: 1.45; }
.stream-section { min-width: 0; border-top: 1px solid var(--border); padding-top: 11px; }
.stream-section header { min-height: 26px; display: flex; align-items: center; gap: 9px; }
.stream-section header strong { font-size: 11px; }
.stream-section header span { margin-left: auto; color: var(--text-muted); font-size: 9px; }
.stream-section header button {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  margin-left: auto;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}
.stream-section header span + button { margin-left: 0; }
.stream-section pre {
  max-height: 420px;
  margin: 0;
  overflow: auto;
  border-left: 3px solid #b8b4c3;
  background: #f8f8f9;
  color: var(--text-secondary);
  padding: 10px 12px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  font: inherit;
  font-size: 11px;
  line-height: 1.65;
}
.thinking-output pre { border-left-color: #d2a34f; background: #fffbf2; }
.final-output pre { border-left-color: #2e9b70; background: #f4fbf7; color: var(--text-primary); }
.partial-output pre { border-left-color: #8c82bb; background: #f8f6ff; }
.phase-error { display: flex; align-items: center; gap: 6px; margin: 0 18px 18px; background: #fff0f0; color: #a84040; padding: 8px 10px; font-size: 10px; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) {
  .phase-body { padding: 13px; }
  .task-segments { grid-template-columns: 1fr; }
  .phase-summary { align-items: stretch; flex-direction: column; }
  .phase-summary label { grid-template-columns: minmax(0,1fr) 96px; }
  .candidate-content > span:first-child { align-items: start; flex-direction: column; gap: 3px; }
  .candidate-content small { flex: 1 1 auto; }
  .cloud-manifest dl { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .cloud-manifest > div { flex-direction: column-reverse; }
  .cloud-manifest > div button { width: 100%; }
  .generation-actions { align-items: stretch; flex-direction: column; }
  .generation-actions > button { width: 100%; }
}
</style>
