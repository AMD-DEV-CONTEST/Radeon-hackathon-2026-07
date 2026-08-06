<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  ExternalLink,
  Images,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Square,
  Trash2,
} from "@lucide/vue";
import {
  activateMediaVisualSpace,
  cancelMediaVisualMigration,
  createMediaVisualSpace,
  garbageCollectMediaVisualSpace,
  getMediaVisionStatus,
  listMediaVisualMigrations,
  listMediaVisualSpaces,
  retryMediaVisualMigration,
  rollbackMediaVisualSpace,
  searchMediaVisionImage,
  searchMediaVisionText,
  validateMediaVisualSpace,
} from "../api/mediaVision.js";
import { listMediaAssets } from "../api/mediaAssets.js";
import { useAppStore } from "../stores/app.js";

const emit = defineEmits(["open-assets"]);
const store = useAppStore();
const { t } = useI18n();

const status = ref(null);
const spaces = ref([]);
const activeSpaceId = ref("");
const rollbackSpaceId = ref("");
const migrations = ref([]);
const imageAssets = ref([]);
const searchResults = ref([]);
const searchChannels = ref({});
const loading = ref(false);
const action = ref("");
const errorMessage = ref("");
const successMessage = ref("");
const gcTarget = ref(null);
const gcConfirmation = ref("");
let pollTimer = null;

const form = ref({
  mode: "text",
  query: "",
  query_asset_id: "",
  top_k: 12,
  requested_backend: "auto",
});

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const hasScope = computed(() => Boolean(databaseId.value && bookId.value));
const canManage = computed(() => store.isLocalOwner);
const activeMigrations = computed(() => (
  migrations.value.some((item) => ["queued", "running"].includes(item.status))
));
const canSearch = computed(() => (
  hasScope.value
  && !action.value
  && (
    (form.value.mode === "text" && form.value.query.trim())
    || (form.value.mode === "image" && form.value.query_asset_id)
  )
));

function safeMessage(error, fallback) {
  return error?.detail?.message || error?.message || t(fallback);
}

function tone(value) {
  if (["active", "validated", "completed"].includes(value)) return "positive";
  if (["building", "queued", "running"].includes(value)) return "active";
  if (["retired", "cancelled"].includes(value)) return "muted";
  if (["failed", "partial_failed"].includes(value)) return "danger";
  return "warning";
}

function progress(task) {
  if (!task?.total_items) return task?.status === "completed" ? 100 : 0;
  return Math.min(100, Math.round((Number(task.processed_items || 0) / task.total_items) * 100));
}

async function refresh({ silent = false } = {}) {
  if (!hasScope.value) {
    status.value = null;
    spaces.value = [];
    migrations.value = [];
    imageAssets.value = [];
    return;
  }
  if (!silent) loading.value = true;
  errorMessage.value = "";
  const results = await Promise.allSettled([
    getMediaVisionStatus(databaseId.value, bookId.value),
    listMediaVisualSpaces(databaseId.value),
    listMediaVisualMigrations(databaseId.value, null, 80),
    listMediaAssets({
      database_id: databaseId.value,
      book_id: bookId.value,
      modality: "image",
      lifecycle_status: "approved",
      limit: 200,
    }),
  ]);
  if (results[0].status === "fulfilled") status.value = results[0].value;
  else errorMessage.value = safeMessage(results[0].reason, "视觉检索状态加载失败");
  if (results[1].status === "fulfilled") {
    spaces.value = results[1].value?.spaces || [];
    activeSpaceId.value = results[1].value?.active_space_id || "";
    rollbackSpaceId.value = results[1].value?.rollback_space_id || "";
  }
  if (results[2].status === "fulfilled") migrations.value = results[2].value?.tasks || [];
  if (results[3].status === "fulfilled") imageAssets.value = results[3].value?.assets || [];
  loading.value = false;
}

async function runSearch() {
  if (!canSearch.value) return;
  action.value = "search";
  errorMessage.value = "";
  successMessage.value = "";
  try {
    const common = {
      book_id: bookId.value,
      top_k: Number(form.value.top_k),
      lifecycle_statuses: ["approved", "archived"],
    };
    const response = form.value.mode === "text"
      ? await searchMediaVisionText(databaseId.value, {
        ...common,
        query: form.value.query.trim(),
        requested_backend: form.value.requested_backend,
      })
      : await searchMediaVisionImage(databaseId.value, {
        ...common,
        query_asset_id: form.value.query_asset_id,
      });
    searchResults.value = response.results || [];
    searchChannels.value = response.channels || {};
    if (response.degraded) {
      successMessage.value = t("检索已完成，部分本地通道不可用，结果已标记降级");
    }
  } catch (error) {
    searchResults.value = [];
    errorMessage.value = safeMessage(error, "视觉检索失败");
  } finally {
    action.value = "";
  }
}

async function createSpace() {
  action.value = "create-space";
  errorMessage.value = "";
  try {
    await createMediaVisualSpace(databaseId.value, form.value.requested_backend);
    successMessage.value = t("新视觉空间和后台迁移任务已创建");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "视觉空间创建失败");
  } finally {
    action.value = "";
  }
}

async function runSpaceAction(kind, space) {
  action.value = `${kind}:${space.space_id}`;
  errorMessage.value = "";
  try {
    if (kind === "validate") {
      await validateMediaVisualSpace(space.space_id, databaseId.value);
      successMessage.value = t("视觉空间验证完成");
    } else {
      await activateMediaVisualSpace(space.space_id, databaseId.value);
      successMessage.value = t("活动指针已原子切换，旧空间保留用于回滚");
    }
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "视觉空间操作失败");
  } finally {
    action.value = "";
  }
}

async function rollbackSpace() {
  action.value = "rollback";
  try {
    await rollbackMediaVisualSpace(databaseId.value);
    successMessage.value = t("视觉空间已通过活动指针回滚");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "视觉空间回滚失败");
  } finally {
    action.value = "";
  }
}

async function confirmGarbageCollect() {
  if (!gcTarget.value || gcConfirmation.value !== gcTarget.value.space_id) return;
  action.value = `gc:${gcTarget.value.space_id}`;
  try {
    await garbageCollectMediaVisualSpace(gcTarget.value.space_id, databaseId.value);
    gcTarget.value = null;
    gcConfirmation.value = "";
    successMessage.value = t("未被活动、回滚或任务引用的视觉空间已清理");
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "视觉空间清理失败");
  } finally {
    action.value = "";
  }
}

async function runMigrationAction(kind, task) {
  action.value = `${kind}:${task.task_id}`;
  try {
    if (kind === "cancel") {
      await cancelMediaVisualMigration(task.task_id, databaseId.value);
    } else {
      await retryMediaVisualMigration(task.task_id, databaseId.value);
    }
    await refresh({ silent: true });
  } catch (error) {
    errorMessage.value = safeMessage(error, "视觉迁移操作失败");
  } finally {
    action.value = "";
  }
}

watch([databaseId, bookId], () => refresh(), { immediate: true });
onMounted(() => {
  pollTimer = window.setInterval(() => {
    if (activeMigrations.value && document.visibilityState === "visible") {
      refresh({ silent: true });
    }
  }, 2500);
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});
</script>

<template>
  <section class="vision-panel">
    <header class="vision-heading">
      <div>
        <span class="heading-icon"><Search :size="20" /></span>
        <div>
          <h2>{{ t("视觉检索") }}</h2>
          <p>{{ t("本地多语言图像发现与不可变视觉向量空间") }}</p>
        </div>
      </div>
      <button class="icon-button" type="button" :title="t('刷新视觉状态')" :disabled="loading" @click="refresh()">
        <RefreshCw :size="16" :class="{ spinning: loading }" />
      </button>
    </header>

    <div v-if="!hasScope" class="empty-state">{{ t("请先选择世界库和作品") }}</div>
    <template v-else>
      <div class="runtime-strip">
        <div>
          <Images :size="17" />
          <span><small>BGE-VL</small><strong>{{ status?.visual_runtime?.available ? t("视觉通道可用") : t("视觉通道不可用") }}</strong></span>
          <em :class="status?.visual_runtime?.available ? 'positive' : 'warning'">
            {{ status?.counts?.visual || 0 }}
          </em>
        </div>
        <div>
          <Database :size="17" />
          <span><small>BGE-M3</small><strong>{{ t("多语言标题通道") }}</strong></span>
          <em :class="status?.caption_runtime?.available ? 'positive' : 'warning'">
            {{ status?.counts?.caption || 0 }}
          </em>
        </div>
        <p v-if="status?.stale_visual" class="runtime-warning">
          <AlertTriangle :size="14" />{{ t("{count} 条视觉记录已过期", { count: status.stale_visual }) }}
        </p>
      </div>

      <form class="search-form" @submit.prevent="runSearch">
        <div class="segmented-control" role="group" :aria-label="t('视觉检索方式')">
          <button type="button" :class="{ active: form.mode === 'text' }" @click="form.mode = 'text'">{{ t("文本搜图") }}</button>
          <button type="button" :class="{ active: form.mode === 'image' }" @click="form.mode = 'image'">{{ t("以图搜图") }}</button>
        </div>
        <label v-if="form.mode === 'text'" class="query-field">
          <span>{{ t("检索文本") }}</span>
          <input v-model="form.query" maxlength="4000" :placeholder="t('输入任意语言的角色、场景或物件描述')" />
        </label>
        <label v-else class="query-field">
          <span>{{ t("查询图像") }}</span>
          <select v-model="form.query_asset_id">
            <option value="">{{ t("选择已批准且已索引的图像") }}</option>
            <option v-for="asset in imageAssets" :key="asset.asset_id" :value="asset.asset_id">
              {{ asset.original_filename }}
            </option>
          </select>
        </label>
        <label>
          <span>{{ t("结果数") }}</span>
          <input v-model.number="form.top_k" type="number" min="1" max="100" />
        </label>
        <label>
          <span>{{ t("硬件后端") }}</span>
          <select v-model="form.requested_backend" :disabled="form.mode === 'image'">
            <option value="auto">{{ t("自动选择") }}</option>
            <option value="cpu">CPU</option>
            <option value="rocm_pytorch">ROCm / PyTorch</option>
            <option value="cuda">CUDA</option>
          </select>
        </label>
        <button class="primary-button" type="submit" :disabled="!canSearch">
          <Search :size="15" />{{ t(action === "search" ? "正在检索" : "开始检索") }}
        </button>
      </form>

      <p v-if="errorMessage" class="feedback danger"><AlertTriangle :size="14" />{{ errorMessage }}</p>
      <p v-if="successMessage" class="feedback positive"><CheckCircle2 :size="14" />{{ successMessage }}</p>

      <div v-if="Object.keys(searchChannels).length" class="channel-summary">
        <span v-for="(channel, name) in searchChannels" :key="name" :class="channel.used ? 'positive' : 'warning'">
          {{ name }} · {{ t(channel.used ? "已使用" : "降级") }}
        </span>
      </div>
      <div v-if="searchResults.length" class="result-table">
        <button v-for="item in searchResults" :key="item.asset_id" type="button" @click="emit('open-assets')">
          <Images :size="16" />
          <span><strong>{{ item.original_filename }}</strong><small>{{ item.mime_type }} · {{ item.lifecycle_status }}</small></span>
          <em>{{ Math.round((item.score || 0) * 100) }}%</em>
          <ExternalLink :size="14" />
        </button>
      </div>

      <section class="space-section">
        <header>
          <div><Database :size="17" /><strong>{{ t("视觉向量空间") }}</strong></div>
          <div class="space-actions">
            <button
              v-if="canManage && rollbackSpaceId"
              class="secondary-button"
              type="button"
              :disabled="Boolean(action)"
              @click="rollbackSpace"
            ><RotateCcw :size="14" />{{ t("回滚") }}</button>
            <button
              v-if="canManage"
              class="primary-button"
              type="button"
              :disabled="Boolean(action)"
              @click="createSpace"
            ><Play :size="14" />{{ t("新建并迁移") }}</button>
          </div>
        </header>
        <div class="space-list">
          <article v-for="space in spaces" :key="space.space_id">
            <div>
              <strong>{{ space.space_id }}</strong>
              <small>{{ space.model_id }} · {{ space.model_revision }}</small>
            </div>
            <dl>
              <div><dt>{{ t("记录") }}</dt><dd>{{ space.record_count }} / {{ space.vector_count }}</dd></div>
              <div><dt>{{ t("来源资产") }}</dt><dd>{{ space.source_asset_count }}</dd></div>
            </dl>
            <em :class="tone(space.status)">
              {{ space.space_id === activeSpaceId ? t("活动") : space.space_id === rollbackSpaceId ? t("可回滚") : space.status }}
            </em>
            <div class="row-actions" v-if="canManage">
              <button v-if="space.status === 'building'" class="icon-button" type="button" :title="t('验证空间')" @click="runSpaceAction('validate', space)">
                <CheckCircle2 :size="14" />
              </button>
              <button v-if="space.status === 'validated'" class="icon-button" type="button" :title="t('切换为活动空间')" @click="runSpaceAction('activate', space)">
                <Play :size="14" />
              </button>
              <button
                v-if="space.status === 'retired' && ![activeSpaceId, rollbackSpaceId].includes(space.space_id)"
                class="icon-button danger"
                type="button"
                :title="t('垃圾回收')"
                @click="gcTarget = space; gcConfirmation = ''"
              ><Trash2 :size="14" /></button>
            </div>
          </article>
        </div>
      </section>

      <section v-if="migrations.length" class="migration-section">
        <strong>{{ t("视觉迁移任务") }}</strong>
        <div v-for="task in migrations.slice(0, 8)" :key="task.task_id" class="migration-row">
          <span><b>{{ task.target_space_id }}</b><small>{{ task.status }} · {{ task.successful_items }}/{{ task.total_items }}</small></span>
          <div class="progress-track"><i :style="{ width: `${progress(task)}%` }"></i></div>
          <em :class="tone(task.status)">{{ progress(task) }}%</em>
          <button v-if="['queued','running'].includes(task.status)" class="icon-button" type="button" :title="t('取消迁移')" @click="runMigrationAction('cancel', task)">
            <Square :size="14" />
          </button>
          <button v-else-if="['failed','partial_failed','cancelled'].includes(task.status)" class="icon-button" type="button" :title="t('重试迁移')" @click="runMigrationAction('retry', task)">
            <RotateCcw :size="14" />
          </button>
        </div>
      </section>
    </template>

    <div v-if="gcTarget" class="dialog-backdrop" @click.self="gcTarget = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="gc-title">
        <AlertTriangle :size="25" />
        <h3 id="gc-title">{{ t("清理视觉空间") }}</h3>
        <p>{{ t("只有未被活动指针、回滚指针或运行中任务引用的空间才能清理。请输入完整空间 ID。") }}</p>
        <code>{{ gcTarget.space_id }}</code>
        <input v-model="gcConfirmation" autocomplete="off" />
        <div>
          <button class="secondary-button" type="button" @click="gcTarget = null">{{ t("取消") }}</button>
          <button class="danger-button" type="button" :disabled="gcConfirmation !== gcTarget.space_id" @click="confirmGarbageCollect">
            <Trash2 :size="14" />{{ t("确认清理") }}
          </button>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.vision-panel { min-height: 610px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); }
.vision-heading, .vision-heading > div, .runtime-strip > div, .runtime-warning, .feedback, .space-section > header, .space-section > header > div, .space-actions { display: flex; align-items: center; }
.vision-heading { min-height: 58px; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding: 9px 12px; }
.vision-heading > div { gap: 10px; min-width: 0; }
.heading-icon { width: 36px; height: 36px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: #e8f2f4; color: #287080; }
.vision-heading h2 { margin: 0 0 3px; font-size: 14px; }
.vision-heading p { margin: 0; color: var(--text-muted); font-size: 10px; }
.icon-button { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.icon-button.danger { color: #a33f3f; }
.runtime-strip { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; border-bottom: 1px solid var(--border); padding: 10px 12px; }
.runtime-strip > div { min-width: 0; gap: 8px; border-radius: 7px; background: var(--bg-secondary); padding: 9px; }
.runtime-strip span { min-width: 0; display: grid; gap: 2px; }
.runtime-strip small { color: var(--text-muted); font-size: 8px; }
.runtime-strip strong { font-size: 10px; }
.runtime-strip em, .channel-summary span, .space-list em, .migration-row em { width: max-content; margin-left: auto; border-radius: 999px; padding: 4px 7px; font-size: 8px; font-style: normal; font-weight: 700; }
.runtime-warning { grid-column: 1/-1; gap: 6px; margin: 0; color: #95651b; font-size: 9px; }
.positive { background: #e7f8f0; color: #15704f; }
.active { background: #e8f0fa; color: #326398; }
.warning { background: #fff6e5; color: #95651b; }
.danger { background: #fff0f0; color: #a33f3f; }
.muted { background: #f0eef4; color: var(--text-secondary); }
.search-form { display: grid; grid-template-columns: auto minmax(240px,1fr) 90px 150px auto; gap: 8px; align-items: end; border-bottom: 1px solid var(--border); padding: 11px 12px; }
.search-form label { min-width: 0; display: grid; gap: 4px; color: var(--text-secondary); font-size: 9px; }
.search-form input, .search-form select, .confirm-dialog input { width: 100%; border: 1px solid var(--border); border-radius: 7px; background: #fff; padding: 7px 8px; font: inherit; }
.segmented-control { display: inline-grid; grid-template-columns: repeat(2,1fr); overflow: hidden; border: 1px solid var(--border); border-radius: 7px; }
.segmented-control button { min-height: 32px; border: 0; border-right: 1px solid var(--border); background: #fff; color: var(--text-secondary); padding: 5px 9px; font-size: 10px; cursor: pointer; }
.segmented-control button:last-child { border-right: 0; }
.segmented-control button.active { background: var(--accent-soft); color: var(--accent); font-weight: 700; }
.primary-button, .secondary-button, .danger-button { min-height: 32px; display: inline-flex; align-items: center; justify-content: center; gap: 5px; border-radius: 7px; padding: 6px 9px; cursor: pointer; font-size: 10px; }
.primary-button { border: 1px solid var(--accent); background: var(--accent); color: #fff; }
.secondary-button { border: 1px solid var(--border); background: #fff; color: var(--text-secondary); }
.danger-button { border: 1px solid #a33f3f; background: #a33f3f; color: #fff; }
button:disabled { opacity: .5; cursor: not-allowed; }
.feedback { gap: 6px; margin: 9px 12px 0; border-radius: 7px; padding: 8px 10px; font-size: 9px; }
.feedback.danger { background: #fff0f0; color: #a33f3f; }
.feedback.positive { background: #edf9f3; color: #167251; }
.channel-summary { display: flex; flex-wrap: wrap; gap: 5px; padding: 9px 12px 0; }
.result-table { display: grid; grid-template-columns: repeat(auto-fit,minmax(230px,1fr)); gap: 7px; padding: 9px 12px 0; }
.result-table button { min-width: 0; display: grid; grid-template-columns: 18px minmax(0,1fr) auto 16px; align-items: center; gap: 7px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: inherit; padding: 8px; text-align: left; cursor: pointer; }
.result-table span { min-width: 0; display: grid; gap: 2px; }
.result-table strong, .result-table small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-table strong { font-size: 10px; }
.result-table small { color: var(--text-muted); font-size: 8px; }
.result-table em { color: #287080; font-size: 9px; font-style: normal; font-weight: 700; }
.space-section, .migration-section { display: grid; gap: 8px; border-top: 1px solid var(--border); margin-top: 10px; padding: 10px 12px; }
.space-section > header { justify-content: space-between; gap: 8px; }
.space-section > header > div { gap: 6px; }
.space-section > header strong, .migration-section > strong { font-size: 11px; }
.space-actions { gap: 6px; }
.space-list { display: grid; gap: 6px; }
.space-list article { min-width: 0; display: grid; grid-template-columns: minmax(180px,1.4fr) minmax(160px,.8fr) auto auto; align-items: center; gap: 8px; border: 1px solid var(--border); border-radius: 7px; padding: 8px; }
.space-list article > div:first-child, .migration-row > span { min-width: 0; display: grid; gap: 2px; }
.space-list strong, .space-list small, .migration-row b, .migration-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.space-list strong, .migration-row b { font-size: 9px; }
.space-list small, .migration-row small { color: var(--text-muted); font-size: 8px; }
.space-list dl { display: grid; grid-template-columns: repeat(2,1fr); gap: 5px; margin: 0; }
.space-list dl div { display: grid; gap: 1px; }
.space-list dt { color: var(--text-muted); font-size: 7px; }
.space-list dd { margin: 0; font-size: 9px; }
.row-actions { display: flex; gap: 4px; }
.migration-row { display: grid; grid-template-columns: minmax(180px,.8fr) minmax(120px,1fr) 46px 34px; align-items: center; gap: 8px; }
.progress-track { height: 7px; overflow: hidden; border-radius: 999px; background: #e9e6ef; }
.progress-track i { display: block; height: 100%; background: #347d8a; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(28,25,44,.42); }
.confirm-dialog { width: min(460px,100%); display: grid; gap: 11px; border-radius: 8px; background: #fff; box-shadow: 0 24px 70px rgba(28,25,44,.22); padding: 20px; }
.confirm-dialog h3, .confirm-dialog p { margin: 0; }
.confirm-dialog p { color: var(--text-secondary); font-size: 11px; line-height: 1.6; }
.confirm-dialog code { overflow-wrap: anywhere; font-size: 10px; }
.confirm-dialog > div { display: flex; justify-content: flex-end; gap: 7px; }
.empty-state { min-height: 180px; display: grid; place-items: center; color: var(--text-muted); padding: 18px; font-size: 9px; }
.spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) {
  .search-form { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .query-field { grid-column: 1/-1; }
  .space-list article { grid-template-columns: 1fr auto; }
  .space-list dl { grid-column: 1/-1; }
}
@media (max-width: 600px) {
  .vision-heading, .space-section > header { align-items: flex-start; flex-direction: column; }
  .runtime-strip, .search-form { grid-template-columns: 1fr; }
  .query-field { grid-column: auto; }
  .space-actions { width: 100%; }
  .space-actions button { flex: 1; }
  .space-list article, .migration-row { grid-template-columns: 1fr; }
  .space-list em { margin-left: 0; }
}
</style>
