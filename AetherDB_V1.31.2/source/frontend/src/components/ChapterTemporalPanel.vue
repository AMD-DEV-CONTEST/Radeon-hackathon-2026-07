<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { CalendarClock, Eye, EyeOff, RefreshCw, Save, ShieldAlert } from "@lucide/vue";
import { getEntities } from "../api/entities.js";
import {
  getChapterTemporalContext,
  listTemporalAnchors,
  listTimelines,
  setChapterTemporalContext,
} from "../api/temporal.js";
import { normalizeEntityList } from "../domain/entities.js";
import { temporalLabel, timelineLabel } from "../domain/temporal.js";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();
const timelines = ref([]);
const anchors = ref([]);
const entities = ref([]);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const savedMessage = ref("");
const syncing = ref(false);

const form = reactive({
  timeline_id: "",
  branch_id: "",
  anchor_id: "",
  phase_id: "",
  viewpoint_entity_id: "",
  include_future_knowledge: false,
});

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const chapterId = computed(() => store.activeChapter?.chapter_id || "");
const canManage = computed(() => store.hasCapability("manage_temporal"));
const hasScope = computed(() => Boolean(databaseId.value && bookId.value && chapterId.value));
const selectedAnchor = computed(() => anchors.value.find((item) => item.id === form.anchor_id));

function enumLabel(value) {
  return temporalLabel(t, value);
}

function displayTimeline(timeline) {
  return timelineLabel(t, timeline);
}

function resetForm() {
  form.timeline_id = "";
  form.branch_id = "";
  form.anchor_id = "";
  form.phase_id = "";
  form.viewpoint_entity_id = "";
  form.include_future_knowledge = false;
}

async function loadAnchors(timelineId = form.timeline_id) {
  if (!databaseId.value || !bookId.value || !timelineId) {
    anchors.value = [];
    return;
  }
  const response = await listTemporalAnchors({
    database_id: databaseId.value,
    book_id: bookId.value,
    timeline_id: timelineId,
    branch_id: form.branch_id || undefined,
  });
  anchors.value = response?.anchors || [];
  if (form.anchor_id && !anchors.value.some((item) => item.id === form.anchor_id)) {
    form.anchor_id = "";
  }
}

async function loadContext() {
  if (!hasScope.value) {
    resetForm();
    return;
  }
  loading.value = true;
  error.value = "";
  savedMessage.value = "";
  syncing.value = true;
  try {
    if (!store.authStatus) await store.loadAuthStatus();
    const [timelineResponse, entityResponse, contextResponse] = await Promise.all([
      listTimelines({ database_id: databaseId.value, book_id: bookId.value }),
      getEntities({ book_id: bookId.value, limit: 200 }),
      getChapterTemporalContext(chapterId.value, {
        database_id: databaseId.value,
        book_id: bookId.value,
      }),
    ]);
    timelines.value = timelineResponse?.timelines || [];
    entities.value = normalizeEntityList(entityResponse);
    const context = contextResponse?.context || {};
    form.timeline_id = context.timeline_id || timelines.value[0]?.id || "";
    form.branch_id = context.branch_id || "";
    form.anchor_id = context.anchor_id || "";
    form.phase_id = context.phase_id || "";
    form.viewpoint_entity_id = context.viewpoint_entity_id || "";
    form.include_future_knowledge = Boolean(context.include_future_knowledge);
    await loadAnchors();
  } catch (err) {
    error.value = err?.message || t("章节时间上下文加载失败");
  } finally {
    syncing.value = false;
    loading.value = false;
  }
}

async function saveContext() {
  if (!hasScope.value || !form.timeline_id || !canManage.value) return;
  saving.value = true;
  error.value = "";
  savedMessage.value = "";
  try {
    const response = await setChapterTemporalContext(chapterId.value, {
      database_id: databaseId.value,
      book_id: bookId.value,
      timeline_id: form.timeline_id,
      branch_id: form.branch_id || null,
      anchor_id: form.anchor_id || null,
      phase_id: form.phase_id.trim() || null,
      viewpoint_entity_id: form.viewpoint_entity_id || null,
      include_future_knowledge: Boolean(form.include_future_knowledge),
    });
    form.include_future_knowledge = Boolean(response?.context?.include_future_knowledge);
    savedMessage.value = t("章节时间上下文已保存");
    store.notifyAction(savedMessage.value);
  } catch (err) {
    error.value = err?.message || t("章节时间上下文保存失败");
  } finally {
    saving.value = false;
  }
}

watch(
  () => form.timeline_id,
  async (value, previous) => {
    if (!syncing.value && value && value !== previous) {
      form.anchor_id = "";
      await loadAnchors(value);
    }
  },
);
watch([databaseId, bookId, chapterId], loadContext);

onMounted(loadContext);
</script>

<template>
  <section class="chapter-temporal-panel">
    <header class="temporal-header">
      <div>
        <span><CalendarClock :size="16" />{{ t("章节时间上下文") }}</span>
        <p>{{ t("将当前章节绑定到故事时间与视角；未来知识默认不会进入检索证据。") }}</p>
      </div>
      <button class="icon-button" type="button" :title="t('刷新')" :disabled="loading" @click="loadContext">
        <RefreshCw :size="16" />
      </button>
    </header>

    <div v-if="!hasScope" class="temporal-empty">
      <CalendarClock :size="24" />
      <strong>{{ t("请先选择作品和章节") }}</strong>
    </div>
    <div v-else-if="loading" class="temporal-empty">
      <strong>{{ t("正在加载") }}</strong>
    </div>
    <form v-else class="temporal-form" @submit.prevent="saveContext">
      <div class="field-row">
        <label for="chapter-timeline">{{ t("故事时间线") }}</label>
        <select id="chapter-timeline" v-model="form.timeline_id" required>
          <option v-for="timeline in timelines" :key="timeline.id" :value="timeline.id">
            {{ displayTimeline(timeline) }}{{ timeline.is_default ? ` · ${t("主线")}` : "" }}
          </option>
        </select>
      </div>

      <div class="field-row">
        <label for="chapter-anchor">{{ t("当前时间锚点") }}</label>
        <select id="chapter-anchor" v-model="form.anchor_id">
          <option value="">{{ t("按章节顺序推断") }}</option>
          <option v-for="anchor in anchors" :key="anchor.id" :value="anchor.id">
            {{ anchor.label }} · {{ enumLabel(anchor.confidence) }}
          </option>
        </select>
        <small v-if="selectedAnchor">{{ t("锚点类型：{type}", { type: enumLabel(selectedAnchor.anchor_type) }) }}</small>
      </div>

      <div class="field-grid">
        <div class="field-row">
          <label for="chapter-viewpoint">{{ t("视角实体") }}</label>
          <select id="chapter-viewpoint" v-model="form.viewpoint_entity_id">
            <option value="">{{ t("未指定") }}</option>
            <option v-for="entity in entities" :key="entity.id" :value="entity.id">
              {{ entity.title }} · {{ t(entity.typeLabel) }}
            </option>
          </select>
        </div>
        <div class="field-row">
          <label for="chapter-phase">{{ t("阶段标识") }}</label>
          <input id="chapter-phase" v-model="form.phase_id" maxlength="128" :placeholder="t('可选，例如：围困第九日')" />
        </div>
      </div>

      <label class="future-toggle" :class="{ warning: form.include_future_knowledge }">
        <input v-model="form.include_future_knowledge" type="checkbox" :disabled="!canManage" />
        <component :is="form.include_future_knowledge ? Eye : EyeOff" :size="18" />
        <span>
          <strong>{{ t("允许未来知识") }}</strong>
          <small>{{ t(form.include_future_knowledge ? "当前章节可以检索当前锚点之后的资料。" : "当前章节只使用可证明属于过去或当前的资料。") }}</small>
        </span>
      </label>

      <div v-if="form.include_future_knowledge" class="future-warning">
        <ShieldAlert :size="16" />
        <span>{{ t("这可能让人物提前知道尚未发生的事件，请仅在倒叙、预知或明确需要时开启。") }}</span>
      </div>
      <p v-if="error" class="form-message error">{{ error }}</p>
      <p v-else-if="savedMessage" class="form-message success">{{ savedMessage }}</p>

      <footer>
        <span v-if="!canManage">{{ t("当前会话只能查看时间上下文") }}</span>
        <button class="save-button" type="submit" :disabled="saving || !form.timeline_id || !canManage">
          <Save :size="16" />{{ t(saving ? "保存中" : "保存时间上下文") }}
        </button>
      </footer>
    </form>
  </section>
</template>

<style scoped>
.chapter-temporal-panel { min-height: 520px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); }
.temporal-header { min-height: 64px; display: flex; align-items: center; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--border); padding: 12px 16px; }
.temporal-header > div { min-width: 0; }
.temporal-header span { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 700; }
.temporal-header p { margin-top: 4px; color: var(--text-secondary); font-size: 11px; }
.icon-button { width: 34px; height: 34px; flex: 0 0 auto; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.icon-button:disabled { cursor: not-allowed; opacity: .5; }
.temporal-empty { min-height: 360px; display: grid; place-items: center; align-content: center; gap: 9px; color: var(--text-muted); }
.temporal-empty strong { font-size: 13px; }
.temporal-form { width: min(100%, 880px); display: grid; gap: 18px; padding: 22px; }
.field-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 14px; }
.field-row small { color: var(--text-muted); font-size: 10px; }
.future-toggle { display: grid; grid-template-columns: auto auto minmax(0,1fr); align-items: center; gap: 10px; border: 1px solid var(--border); border-radius: 8px; background: #f8fafb; padding: 12px; cursor: pointer; }
.future-toggle.warning { border-color: #e8c17d; background: #fff8ec; color: #8c5918; }
.future-toggle input { width: 16px; height: 16px; }
.future-toggle span { display: grid; gap: 2px; }
.future-toggle strong { font-size: 12px; }
.future-toggle small { color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
.future-warning { display: flex; align-items: flex-start; gap: 8px; border-left: 3px solid #d39a3b; color: #80541b; padding: 3px 0 3px 10px; font-size: 11px; line-height: 1.55; }
.form-message { border-radius: 6px; padding: 8px 10px; font-size: 11px; }
.form-message.error { background: #fff0f0; color: #a33b3b; }
.form-message.success { background: #edfbf5; color: #25775a; }
.temporal-form footer { min-height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid var(--border); padding-top: 14px; }
.temporal-form footer > span { color: var(--text-muted); font-size: 10px; }
.save-button { min-height: 36px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 7px; background: var(--accent); color: #fff; cursor: pointer; padding: 7px 13px; font-size: 11px; }
.save-button:disabled { cursor: not-allowed; opacity: .5; }
@media (max-width: 680px) {
  .temporal-form { padding: 16px; }
  .field-grid { grid-template-columns: 1fr; }
  .temporal-form footer { align-items: stretch; flex-direction: column; }
  .save-button { width: 100%; }
}
</style>
