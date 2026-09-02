<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import {
  AlertTriangle,
  ArrowRight,
  BookOpenText,
  CalendarClock,
  CheckCircle2,
  GitBranch,
  History,
  Plus,
  RefreshCw,
  Save,
  Search,
} from "@lucide/vue";
import { getEntities } from "../api/entities.js";
import {
  createEntityStateSegment,
  createTemporalAnchor,
  createTemporalRelation,
  createTimeline,
  getEntityStateHistory,
  getResolvedEntityState,
  listTemporalAnchors,
  listTemporalRelations,
  listTimelines,
} from "../api/temporal.js";
import { ENTITY_TYPE_LABELS, entityPreview, normalizeEntityList } from "../domain/entities.js";
import { temporalLabel, timelineLabel } from "../domain/temporal.js";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();
const mode = ref("entity");
const entities = ref([]);
const timelines = ref([]);
const anchors = ref([]);
const relations = ref([]);
const parentAnchors = ref([]);
const selectedEntityId = ref("");
const selectedTimelineId = ref("");
const resolvedAnchorId = ref("");
const resolvedState = ref(null);
const stateHistory = ref([]);
const query = ref("");
const typeFilter = ref("all");
const loading = ref(false);
const temporalLoading = ref(false);
const stateLoading = ref(false);
const saving = ref("");
const error = ref("");
const notice = ref("");

const timelineForm = reactive({
  name: "",
  status: "active",
  parent_timeline_id: "",
  divergence_anchor_id: "",
});
const anchorForm = reactive({
  label: "",
  anchor_type: "order_only",
  absolute_time: "",
  order_hint: "",
  confidence: "confirmed",
});
const relationForm = reactive({
  source_anchor_id: "",
  relation_type: "before",
  target_anchor_id: "",
  confidence: "confirmed",
});
const stateForm = reactive({
  state_type: "location",
  field_name: "description",
  field_value: "",
  valid_from_anchor_id: "",
  valid_to_anchor_id: "",
  confidence: "confirmed",
  supersedes_segment_id: "",
});

const databaseId = computed(() => store.activeDatabase?.database_id || "");
const bookId = computed(() => store.activeBook?.book_id || "");
const canManage = computed(() => store.hasCapability("manage_temporal"));
const selectedEntity = computed(() => entities.value.find((item) => item.id === selectedEntityId.value) || null);
const selectedTimeline = computed(() => timelines.value.find((item) => item.id === selectedTimelineId.value) || null);
const typeOptions = computed(() => [
  { value: "all", label: "全部" },
  ...Object.entries(ENTITY_TYPE_LABELS).map(([value, label]) => ({ value, label })),
]);
const filteredEntities = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return entities.value.filter((entity) => {
    const matchesType = typeFilter.value === "all" || entity.type === typeFilter.value;
    const matchesText = !needle
      || entity.title.toLowerCase().includes(needle)
      || entity.content.toLowerCase().includes(needle);
    return matchesType && matchesText;
  });
});
const activeHistory = computed(() => stateHistory.value.filter((item) => !item.superseded_by));
const resolvedFields = computed(() => Object.entries(resolvedState.value?.fields || {}));

const anchorTypes = ["order_only", "unknown", "relative", "exact", "range"];
const relationTypes = [
  "before",
  "after",
  "simultaneous",
  "overlaps",
  "approximately_before",
  "approximately_after",
  "unknown",
];
const confidenceOptions = ["confirmed", "inferred", "uncertain"];
const stateTypes = [
  "physical",
  "realm",
  "location",
  "identity",
  "faction",
  "injury",
  "equipment",
  "ownership",
  "relationship",
  "psychological",
  "behavior_logic",
  "knowledge",
  "goal",
  "life_status",
];

function scopeParams(extra = {}) {
  return {
    database_id: databaseId.value,
    book_id: bookId.value,
    ...extra,
  };
}

function showNotice(message) {
  notice.value = message;
  error.value = "";
}

function anchorLabel(anchorId) {
  return anchors.value.find((item) => item.id === anchorId)?.label || anchorId || t("未指定");
}

function payloadSummary(payload) {
  if (!payload || typeof payload !== "object") return String(payload || "");
  return Object.entries(payload).map(([key, value]) => `${key}: ${String(value)}`).join(" · ");
}

function enumLabel(value) {
  return temporalLabel(t, value);
}

function displayTimeline(timeline) {
  return timelineLabel(t, timeline);
}

async function loadTimelineData() {
  if (!selectedTimelineId.value) {
    anchors.value = [];
    relations.value = [];
    return;
  }
  temporalLoading.value = true;
  error.value = "";
  try {
    const [anchorResponse, relationResponse] = await Promise.all([
      listTemporalAnchors(scopeParams({ timeline_id: selectedTimelineId.value })),
      listTemporalRelations(scopeParams({ timeline_id: selectedTimelineId.value })),
    ]);
    anchors.value = anchorResponse?.anchors || [];
    relations.value = relationResponse?.relations || [];
    if (resolvedAnchorId.value && !anchors.value.some((item) => item.id === resolvedAnchorId.value)) {
      resolvedAnchorId.value = "";
    }
  } catch (err) {
    error.value = err?.message || t("时间线数据加载失败");
  } finally {
    temporalLoading.value = false;
  }
}

async function refreshEntityState() {
  if (!selectedEntityId.value || !selectedTimelineId.value) {
    resolvedState.value = null;
    stateHistory.value = [];
    return;
  }
  stateLoading.value = true;
  error.value = "";
  try {
    const params = scopeParams({
      timeline_id: selectedTimelineId.value,
      anchor_id: resolvedAnchorId.value || undefined,
    });
    const [resolved, history] = await Promise.all([
      getResolvedEntityState(selectedEntityId.value, params),
      getEntityStateHistory(selectedEntityId.value, scopeParams({ timeline_id: selectedTimelineId.value })),
    ]);
    resolvedState.value = resolved;
    stateHistory.value = history?.segments || [];
  } catch (err) {
    error.value = err?.message || t("实体时间状态加载失败");
  } finally {
    stateLoading.value = false;
  }
}

async function loadScope() {
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    if (!store.databases.length) await store.fetchDashboard();
    if (!store.authStatus) await store.loadAuthStatus();
    if (!databaseId.value || !bookId.value) {
      entities.value = [];
      timelines.value = [];
      return;
    }
    const [entityResponse, timelineResponse] = await Promise.all([
      getEntities({ book_id: bookId.value, limit: 200 }),
      listTimelines(scopeParams()),
    ]);
    entities.value = normalizeEntityList(entityResponse);
    timelines.value = timelineResponse?.timelines || [];
    if (!entities.value.some((item) => item.id === selectedEntityId.value)) {
      selectedEntityId.value = entities.value[0]?.id || "";
    }
    if (!timelines.value.some((item) => item.id === selectedTimelineId.value)) {
      selectedTimelineId.value = timelines.value[0]?.id || "";
    }
    await loadTimelineData();
    await refreshEntityState();
  } catch (err) {
    error.value = err?.message || t("作品时间数据加载失败");
  } finally {
    loading.value = false;
  }
}

async function selectEntity(entityId) {
  selectedEntityId.value = entityId;
  await refreshEntityState();
}

async function selectTimeline(timelineId) {
  selectedTimelineId.value = timelineId;
  resolvedAnchorId.value = "";
  await loadTimelineData();
  await refreshEntityState();
}

async function loadParentAnchors() {
  timelineForm.divergence_anchor_id = "";
  if (!timelineForm.parent_timeline_id) {
    parentAnchors.value = [];
    return;
  }
  try {
    const response = await listTemporalAnchors(scopeParams({ timeline_id: timelineForm.parent_timeline_id }));
    parentAnchors.value = response?.anchors || [];
  } catch (err) {
    error.value = err?.message || t("分歧锚点加载失败");
  }
}

async function addTimeline() {
  if (!timelineForm.name.trim() || !canManage.value) return;
  if (timelineForm.parent_timeline_id && !timelineForm.divergence_anchor_id) {
    error.value = t("子时间线必须选择分歧锚点");
    return;
  }
  saving.value = "timeline";
  error.value = "";
  try {
    const response = await createTimeline(scopeParams({
      name: timelineForm.name.trim(),
      status: timelineForm.status,
      parent_timeline_id: timelineForm.parent_timeline_id || null,
      divergence_anchor_id: timelineForm.divergence_anchor_id || null,
    }));
    timelineForm.name = "";
    timelineForm.parent_timeline_id = "";
    timelineForm.divergence_anchor_id = "";
    parentAnchors.value = [];
    const timelineResponse = await listTimelines(scopeParams());
    timelines.value = timelineResponse?.timelines || [];
    await selectTimeline(response?.timeline?.id || timelines.value.at(-1)?.id || "");
    showNotice(t("时间线已创建"));
  } catch (err) {
    error.value = err?.message || t("时间线创建失败");
  } finally {
    saving.value = "";
  }
}

async function addAnchor() {
  if (!anchorForm.label.trim() || !selectedTimelineId.value || !canManage.value) return;
  if (["exact", "range"].includes(anchorForm.anchor_type) && !anchorForm.absolute_time.trim()) {
    error.value = t("精确或范围锚点必须填写故事内时间");
    return;
  }
  saving.value = "anchor";
  error.value = "";
  try {
    await createTemporalAnchor(scopeParams({
      timeline_id: selectedTimelineId.value,
      anchor_type: anchorForm.anchor_type,
      label: anchorForm.label.trim(),
      absolute_time: anchorForm.absolute_time.trim() || null,
      order_hint: anchorForm.order_hint === "" ? null : Number(anchorForm.order_hint),
      confidence: anchorForm.confidence,
    }));
    anchorForm.label = "";
    anchorForm.absolute_time = "";
    anchorForm.order_hint = "";
    await loadTimelineData();
    showNotice(t("时间锚点已创建"));
  } catch (err) {
    error.value = err?.message || t("时间锚点创建失败");
  } finally {
    saving.value = "";
  }
}

async function addRelation() {
  if (
    !relationForm.source_anchor_id
    || !relationForm.target_anchor_id
    || relationForm.source_anchor_id === relationForm.target_anchor_id
    || !canManage.value
  ) return;
  saving.value = "relation";
  error.value = "";
  try {
    const response = await createTemporalRelation(scopeParams({
      timeline_id: selectedTimelineId.value,
      source_anchor_id: relationForm.source_anchor_id,
      relation_type: relationForm.relation_type,
      target_anchor_id: relationForm.target_anchor_id,
      confidence: relationForm.confidence,
    }));
    relationForm.source_anchor_id = "";
    relationForm.target_anchor_id = "";
    await loadTimelineData();
    const relation = response?.relation;
    showNotice(t(relation?.requires_confirmation ? "关系形成循环，已保存为待确认冲突" : "时间关系已创建"));
  } catch (err) {
    error.value = err?.message || t("时间关系创建失败");
  } finally {
    saving.value = "";
  }
}

async function addStateSegment() {
  if (
    !selectedEntityId.value
    || !selectedTimelineId.value
    || !stateForm.field_name.trim()
    || !stateForm.field_value.trim()
    || !canManage.value
  ) return;
  saving.value = "state";
  error.value = "";
  try {
    const response = await createEntityStateSegment(scopeParams({
      entity_id: selectedEntityId.value,
      timeline_id: selectedTimelineId.value,
      state_type: stateForm.state_type,
      state_payload: { [stateForm.field_name.trim()]: stateForm.field_value.trim() },
      valid_from_anchor_id: stateForm.valid_from_anchor_id || null,
      valid_to_anchor_id: stateForm.valid_to_anchor_id || null,
      confidence: stateForm.confidence,
      supersedes_segment_id: stateForm.supersedes_segment_id || null,
    }));
    stateForm.field_value = "";
    stateForm.supersedes_segment_id = "";
    await refreshEntityState();
    showNotice(t(
      response?.segment?.confidence === "uncertain"
        ? "状态区间无法完全排序，已按不确定状态保存"
        : "实体状态段已保存",
    ));
  } catch (err) {
    error.value = err?.message || t("实体状态段保存失败");
  } finally {
    saving.value = "";
  }
}

watch([databaseId, bookId], ([nextDatabase, nextBook], [previousDatabase, previousBook]) => {
  if (nextDatabase !== previousDatabase || nextBook !== previousBook) loadScope();
});

onMounted(loadScope);
</script>

<template>
  <div class="page-shell temporal-world-page">
    <header class="page-header">
      <div>
        <h1>{{ t("文档与实体") }}</h1>
        <p>{{ t("在作品范围内查看实体，并维护偏序时间、分支与可追溯状态。") }}</p>
      </div>
      <div class="scope-status">
        <span>{{ store.activeDatabase?.name || t("未选择数据库") }}</span>
        <ArrowRight :size="14" />
        <strong>{{ store.activeBook?.title || t("未选择作品") }}</strong>
        <button type="button" :title="t('刷新')" :disabled="loading" @click="loadScope">
          <RefreshCw :size="15" />
        </button>
      </div>
    </header>

    <div v-if="!databaseId || !bookId" class="empty-state scope-empty">
      <BookOpenText :size="28" />
      <strong>{{ t("请先在首页选择数据库和作品") }}</strong>
    </div>
    <template v-else>
      <nav class="view-tabs" :aria-label="t('实体与时间线视图')">
        <button :class="{ active: mode === 'entity' }" type="button" @click="mode = 'entity'">
          <BookOpenText :size="16" />{{ t("实体状态") }}
        </button>
        <button :class="{ active: mode === 'timeline' }" type="button" @click="mode = 'timeline'">
          <CalendarClock :size="16" />{{ t("时间线编排") }}
        </button>
        <label>
          <span>{{ t("当前时间线") }}</span>
          <select :value="selectedTimelineId" @change="selectTimeline($event.target.value)">
            <option v-for="timeline in timelines" :key="timeline.id" :value="timeline.id">
              {{ displayTimeline(timeline) }}{{ timeline.is_default ? ` · ${t("主线")}` : "" }}
            </option>
          </select>
        </label>
      </nav>

      <p v-if="error" class="page-message error"><AlertTriangle :size="15" />{{ error }}</p>
      <p v-else-if="notice" class="page-message success"><CheckCircle2 :size="15" />{{ notice }}</p>

      <div class="world-layout">
        <aside class="panel entity-browser">
          <header>
            <div><strong>{{ t("作品实体") }}</strong><small>{{ t("{count} 项", { count: filteredEntities.length }) }}</small></div>
            <Search :size="16" />
          </header>
          <input v-model="query" :placeholder="t('筛选标题或正文...')" />
          <div class="type-filter">
            <button
              v-for="option in typeOptions"
              :key="option.value"
              type="button"
              :class="{ active: typeFilter === option.value }"
              @click="typeFilter = option.value"
            >
              {{ t(option.label) }}
            </button>
          </div>
          <div v-if="loading" class="list-empty">{{ t("正在加载") }}</div>
          <div v-else-if="!filteredEntities.length" class="list-empty">{{ t("暂无匹配内容") }}</div>
          <div v-else class="entity-list">
            <button
              v-for="entity in filteredEntities"
              :key="entity.id"
              type="button"
              :class="{ active: selectedEntityId === entity.id }"
              @click="selectEntity(entity.id)"
            >
              <strong>{{ entity.title }}</strong>
              <small>{{ t(entity.typeLabel) }}</small>
              <span>{{ entityPreview(entity) }}</span>
            </button>
          </div>
        </aside>

        <main v-if="mode === 'entity'" class="panel entity-temporal">
          <header class="section-header">
            <div>
              <span>{{ selectedEntity ? t(selectedEntity.typeLabel) : t("实体") }}</span>
              <h2>{{ selectedEntity?.title || t("未选择实体") }}</h2>
              <p>{{ selectedEntity ? entityPreview(selectedEntity) : t("从左侧选择需要查看的实体") }}</p>
            </div>
            <label class="resolve-anchor">
              <span>{{ t("解析时间点") }}</span>
              <select v-model="resolvedAnchorId" :disabled="!selectedEntity" @change="refreshEntityState">
                <option value="">{{ t("当前开放状态") }}</option>
                <option v-for="anchor in anchors" :key="anchor.id" :value="anchor.id">{{ anchor.label }}</option>
              </select>
            </label>
          </header>

          <section class="resolved-section">
            <div class="subheading"><h3>{{ t("解析后的实体状态") }}</h3><span>{{ displayTimeline(selectedTimeline) }}</span></div>
            <div v-if="stateLoading" class="list-empty">{{ t("正在解析") }}</div>
            <div v-else-if="!resolvedFields.length" class="list-empty">{{ t("此时间点尚无状态记录") }}</div>
            <div v-else class="resolved-grid">
              <article v-for="[stateType, field] in resolvedFields" :key="stateType">
                <header><strong>{{ enumLabel(stateType) }}</strong><span :class="field.confidence">{{ enumLabel(field.confidence) }}</span></header>
                <p v-if="Array.isArray(field.value)">
                  {{ field.value.map(payloadSummary).join(" / ") }}
                </p>
                <p v-else>{{ payloadSummary(field.value) }}</p>
              </article>
            </div>
            <div v-if="resolvedState?.warnings?.length" class="warning-list">
              <AlertTriangle :size="16" />
              <div><span v-for="warning in resolvedState.warnings" :key="warning">{{ warning }}</span></div>
            </div>
          </section>

          <section class="state-editor">
            <div class="subheading">
              <div><h3>{{ t("新增实体状态段") }}</h3><p>{{ t("保存会新增一条可追溯记录，不会覆盖实体正文。") }}</p></div>
              <History :size="17" />
            </div>
            <form @submit.prevent="addStateSegment">
              <div class="form-grid">
                <div class="field-row">
                  <label>{{ t("状态类型") }}</label>
                  <select v-model="stateForm.state_type">
                    <option v-for="stateType in stateTypes" :key="stateType" :value="stateType">{{ enumLabel(stateType) }}</option>
                  </select>
                </div>
                <div class="field-row">
                  <label>{{ t("字段名称") }}</label>
                  <input v-model="stateForm.field_name" maxlength="100" :placeholder="t('例如：current_location')" />
                </div>
                <div class="field-row wide">
                  <label>{{ t("状态内容") }}</label>
                  <input v-model="stateForm.field_value" maxlength="1000" :placeholder="t('输入在该时间区间内成立的事实')" />
                </div>
                <div class="field-row">
                  <label>{{ t("起始锚点") }}</label>
                  <select v-model="stateForm.valid_from_anchor_id">
                    <option value="">{{ t("未指定") }}</option>
                    <option v-for="anchor in anchors" :key="anchor.id" :value="anchor.id">{{ anchor.label }}</option>
                  </select>
                </div>
                <div class="field-row">
                  <label>{{ t("结束锚点（不含）") }}</label>
                  <select v-model="stateForm.valid_to_anchor_id">
                    <option value="">{{ t("持续有效") }}</option>
                    <option v-for="anchor in anchors" :key="anchor.id" :value="anchor.id">{{ anchor.label }}</option>
                  </select>
                </div>
                <div class="field-row">
                  <label>{{ t("可信度") }}</label>
                  <select v-model="stateForm.confidence">
                    <option v-for="confidence in confidenceOptions" :key="confidence" :value="confidence">{{ enumLabel(confidence) }}</option>
                  </select>
                </div>
                <div class="field-row">
                  <label>{{ t("替代旧状态") }}</label>
                  <select v-model="stateForm.supersedes_segment_id">
                    <option value="">{{ t("不替代") }}</option>
                    <option v-for="segment in activeHistory" :key="segment.id" :value="segment.id">
                      {{ enumLabel(segment.state_type) }} · {{ payloadSummary(segment.state_payload) }}
                    </option>
                  </select>
                </div>
              </div>
              <footer>
                <span v-if="!canManage">{{ t("当前会话只能查看时间数据") }}</span>
                <button type="submit" :disabled="saving === 'state' || !selectedEntity || !stateForm.field_value.trim() || !canManage">
                  <Save :size="15" />{{ t(saving === "state" ? "保存中" : "保存状态段") }}
                </button>
              </footer>
            </form>
          </section>

          <section class="history-section">
            <div class="subheading"><h3>{{ t("状态历史") }}</h3><span>{{ t("{count} 条", { count: stateHistory.length }) }}</span></div>
            <div v-if="!stateHistory.length" class="list-empty">{{ t("尚无状态历史") }}</div>
            <div v-else class="history-list">
              <article v-for="segment in stateHistory" :key="segment.id" :class="{ superseded: segment.superseded_by }">
                <div><strong>{{ enumLabel(segment.state_type) }}</strong><span>{{ payloadSummary(segment.state_payload) }}</span></div>
                <small>{{ anchorLabel(segment.valid_from_anchor_id) }} → {{ anchorLabel(segment.valid_to_anchor_id) }}</small>
                <em>{{ segment.superseded_by ? t("已被替代") : enumLabel(segment.confidence) }}</em>
              </article>
            </div>
          </section>
        </main>

        <main v-else class="panel timeline-builder">
          <header class="section-header">
            <div>
              <span><GitBranch :size="14" />{{ t("偏序时间") }}</span>
              <h2>{{ displayTimeline(selectedTimeline) }}</h2>
              <p>{{ t("只记录可以确认的先后关系；未知顺序不会被强制换算为日期。") }}</p>
            </div>
            <strong class="timeline-status">{{ enumLabel(selectedTimeline?.status) }}</strong>
          </header>

          <section class="timeline-create">
            <div class="subheading"><h3>{{ t("新建时间线或分支") }}</h3><Plus :size="17" /></div>
            <form class="form-grid" @submit.prevent="addTimeline">
              <div class="field-row">
                <label>{{ t("时间线名称") }}</label>
                <input v-model="timelineForm.name" maxlength="200" :placeholder="t('例如：主线之外的可能历史')" />
              </div>
              <div class="field-row">
                <label>{{ t("状态") }}</label>
                <select v-model="timelineForm.status"><option value="active">{{ t("active") }}</option><option value="draft">{{ t("draft") }}</option></select>
              </div>
              <div class="field-row">
                <label>{{ t("父时间线") }}</label>
                <select v-model="timelineForm.parent_timeline_id" @change="loadParentAnchors">
                  <option value="">{{ t("无，创建独立时间线") }}</option>
                  <option v-for="timeline in timelines" :key="timeline.id" :value="timeline.id">{{ displayTimeline(timeline) }}</option>
                </select>
              </div>
              <div class="field-row">
                <label>{{ t("分歧锚点") }}</label>
                <select v-model="timelineForm.divergence_anchor_id" :disabled="!timelineForm.parent_timeline_id">
                  <option value="">{{ t("选择分歧发生的位置") }}</option>
                  <option v-for="anchor in parentAnchors" :key="anchor.id" :value="anchor.id">{{ anchor.label }}</option>
                </select>
              </div>
              <button class="inline-submit" type="submit" :disabled="saving === 'timeline' || !timelineForm.name.trim() || !canManage">
                <Plus :size="15" />{{ t(saving === "timeline" ? "创建中" : "创建时间线") }}
              </button>
            </form>
          </section>

          <section class="anchor-editor">
            <div class="subheading"><h3>{{ t("时间锚点") }}</h3><span>{{ t("{count} 个", { count: anchors.length }) }}</span></div>
            <form class="form-grid" @submit.prevent="addAnchor">
              <div class="field-row wide">
                <label>{{ t("锚点名称") }}</label>
                <input v-model="anchorForm.label" maxlength="300" :placeholder="t('描述作品内可辨认的时刻或阶段')" />
              </div>
              <div class="field-row">
                <label>{{ t("锚点类型") }}</label>
                <select v-model="anchorForm.anchor_type">
                  <option v-for="anchorType in anchorTypes" :key="anchorType" :value="anchorType">{{ enumLabel(anchorType) }}</option>
                </select>
              </div>
              <div class="field-row">
                <label>{{ t("故事内时间") }}</label>
                <input v-model="anchorForm.absolute_time" maxlength="160" :disabled="!['exact','range'].includes(anchorForm.anchor_type)" :placeholder="t('仅精确/范围锚点需要')" />
              </div>
              <div class="field-row">
                <label>{{ t("显示顺序提示") }}</label>
                <input v-model="anchorForm.order_hint" type="number" step="0.1" :placeholder="t('可选，不代表绝对时间')" />
              </div>
              <div class="field-row">
                <label>{{ t("可信度") }}</label>
                <select v-model="anchorForm.confidence">
                    <option v-for="confidence in confidenceOptions" :key="confidence" :value="confidence">{{ enumLabel(confidence) }}</option>
                </select>
              </div>
              <button class="inline-submit" type="submit" :disabled="saving === 'anchor' || !anchorForm.label.trim() || !canManage">
                <Plus :size="15" />{{ t(saving === "anchor" ? "创建中" : "创建锚点") }}
              </button>
            </form>
            <div v-if="temporalLoading" class="list-empty">{{ t("正在加载") }}</div>
            <div v-else class="anchor-list">
              <article v-for="anchor in anchors" :key="anchor.id">
                <span>{{ anchor.order_hint ?? "·" }}</span>
                <div><strong>{{ anchor.label }}</strong><small>{{ enumLabel(anchor.anchor_type) }} · {{ anchor.absolute_time || t("无绝对时间") }}</small></div>
                <em :class="anchor.confidence">{{ enumLabel(anchor.confidence) }}</em>
              </article>
            </div>
          </section>

          <section class="relation-editor">
            <div class="subheading"><h3>{{ t("锚点关系") }}</h3><span>{{ t("{count} 条", { count: relations.length }) }}</span></div>
            <form class="relation-form" @submit.prevent="addRelation">
              <select v-model="relationForm.source_anchor_id">
                <option value="">{{ t("起点锚点") }}</option>
                <option v-for="anchor in anchors" :key="anchor.id" :value="anchor.id">{{ anchor.label }}</option>
              </select>
              <select v-model="relationForm.relation_type">
                <option v-for="relationType in relationTypes" :key="relationType" :value="relationType">{{ enumLabel(relationType) }}</option>
              </select>
              <select v-model="relationForm.target_anchor_id">
                <option value="">{{ t("终点锚点") }}</option>
                <option v-for="anchor in anchors" :key="anchor.id" :value="anchor.id">{{ anchor.label }}</option>
              </select>
              <button type="submit" :title="t('创建关系')" :disabled="saving === 'relation' || !relationForm.source_anchor_id || !relationForm.target_anchor_id || relationForm.source_anchor_id === relationForm.target_anchor_id || !canManage">
                <Plus :size="16" />
              </button>
            </form>
            <div v-if="!relations.length" class="list-empty">{{ t("尚无锚点关系") }}</div>
            <div v-else class="relation-list">
              <article v-for="relation in relations" :key="relation.id" :class="{ conflict: relation.review_status === 'pending' || relation.confidence === 'conflicting' }">
                <span>{{ anchorLabel(relation.source_anchor_id) }}</span>
                <strong>{{ enumLabel(relation.relation_type) }}</strong>
                <span>{{ anchorLabel(relation.target_anchor_id) }}</span>
                <em>{{ relation.review_status === "pending" ? t("待确认冲突") : enumLabel(relation.confidence) }}</em>
              </article>
            </div>
          </section>
        </main>
      </div>
    </template>
  </div>
</template>

<style scoped>
.temporal-world-page { width: min(100%, 1680px); margin: 0 auto; }
.scope-status { min-width: 0; display: flex; align-items: center; gap: 7px; border: 1px solid var(--border); border-radius: 8px; background: #fff; padding: 6px 8px 6px 11px; color: var(--text-secondary); font-size: 11px; }
.scope-status span, .scope-status strong { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.scope-status button { width: 30px; height: 30px; display: grid; place-items: center; border: 0; border-left: 1px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer; }
.scope-empty { min-height: 420px; }
.view-tabs { min-height: 48px; display: flex; align-items: center; gap: 4px; margin-bottom: 12px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.92); padding: 6px; }
.view-tabs > button { min-height: 34px; display: inline-flex; align-items: center; gap: 6px; border: 0; border-radius: 6px; background: transparent; color: var(--text-secondary); cursor: pointer; padding: 6px 12px; font-size: 11px; }
.view-tabs > button.active { background: var(--accent); color: #fff; }
.view-tabs label { min-width: 280px; display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 8px; margin-left: auto; }
.view-tabs label span { color: var(--text-muted); font-size: 10px; }
.view-tabs select { min-height: 34px; padding: 5px 9px; font-size: 11px; }
.page-message { display: flex; align-items: center; gap: 7px; margin-bottom: 12px; border-radius: 7px; padding: 8px 11px; font-size: 11px; }
.page-message.error { background: #fff0f0; color: #a33b3b; }
.page-message.success { background: #edfbf5; color: #25775a; }
.world-layout { display: grid; grid-template-columns: 300px minmax(0,1fr); gap: 12px; align-items: start; }
.entity-browser { position: sticky; top: 12px; max-height: calc(100vh - 150px); display: grid; grid-template-rows: auto auto auto minmax(120px,1fr); gap: 10px; overflow: hidden; padding: 12px; }
.entity-browser > header { display: flex; align-items: center; justify-content: space-between; color: var(--text-secondary); }
.entity-browser > header div { min-width: 0; display: flex; align-items: baseline; gap: 7px; }
.entity-browser > header strong { color: var(--text-primary); font-size: 13px; }
.entity-browser > header small { color: var(--text-muted); font-size: 10px; }
.type-filter { display: flex; gap: 4px; overflow-x: auto; padding-bottom: 2px; }
.type-filter button { flex: 0 0 auto; border: 1px solid transparent; border-radius: 6px; background: var(--bg-secondary); color: var(--text-secondary); cursor: pointer; padding: 4px 7px; font-size: 9px; }
.type-filter button.active { border-color: #d5ccfb; background: var(--accent-soft); color: var(--accent); }
.entity-list { min-height: 0; display: grid; align-content: start; gap: 3px; overflow-y: auto; }
.entity-list button { min-width: 0; display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 3px 8px; border: 1px solid transparent; border-radius: 6px; background: transparent; cursor: pointer; padding: 8px; text-align: left; }
.entity-list button:hover { background: #faf9fd; }
.entity-list button.active { border-color: #d8cffd; background: var(--accent-soft); }
.entity-list strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.entity-list small { color: var(--accent); font-size: 9px; }
.entity-list span { grid-column: 1 / -1; overflow: hidden; color: var(--text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.list-empty { min-height: 62px; display: grid; place-items: center; color: var(--text-muted); font-size: 11px; text-align: center; }
.entity-temporal, .timeline-builder { min-width: 0; padding: 0; overflow: hidden; }
.section-header { min-height: 98px; display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; border-bottom: 1px solid var(--border); padding: 16px 18px; }
.section-header > div { min-width: 0; }
.section-header > div > span { display: flex; align-items: center; gap: 5px; color: var(--accent); font-size: 10px; font-weight: 700; }
.section-header h2 { margin-top: 4px; font-size: 18px; }
.section-header p { max-width: 720px; margin-top: 5px; overflow: hidden; color: var(--text-secondary); font-size: 11px; line-height: 1.55; text-overflow: ellipsis; white-space: nowrap; }
.resolve-anchor { min-width: 220px; display: grid; gap: 5px; }
.resolve-anchor span { color: var(--text-muted); font-size: 10px; }
.resolve-anchor select { font-size: 11px; }
.resolved-section, .state-editor, .history-section, .timeline-create, .anchor-editor, .relation-editor { padding: 16px 18px; }
.state-editor, .history-section, .anchor-editor, .relation-editor { border-top: 1px solid var(--border); }
.subheading { min-height: 26px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 11px; }
.subheading h3 { font-size: 13px; }
.subheading p, .subheading span { margin-top: 2px; color: var(--text-muted); font-size: 10px; }
.resolved-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.resolved-grid article { min-width: 0; border: 1px solid var(--border); border-radius: 7px; background: #fbfcfd; padding: 10px; }
.resolved-grid article header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.resolved-grid article strong { font-size: 11px; }
.resolved-grid article header span { border-radius: 5px; background: var(--bg-secondary); color: var(--text-secondary); padding: 2px 5px; font-size: 9px; }
.resolved-grid article header span.conflicting { background: #fff0f0; color: #a33b3b; }
.resolved-grid article header span.uncertain { background: #fff7e8; color: #94601d; }
.resolved-grid article p { margin-top: 7px; overflow-wrap: anywhere; color: var(--text-secondary); font-size: 10px; line-height: 1.55; }
.warning-list { display: flex; align-items: flex-start; gap: 8px; margin-top: 10px; border-left: 3px solid #d39a3b; color: #80541b; padding: 4px 0 4px 9px; font-size: 10px; }
.warning-list div { display: grid; gap: 3px; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }
.field-row.wide { grid-column: 1 / -1; }
.field-row input, .field-row select { min-height: 34px; padding: 6px 9px; font-size: 11px; }
.state-editor footer { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 12px; }
.state-editor footer span { margin-right: auto; color: var(--text-muted); font-size: 10px; }
.state-editor footer button, .inline-submit { min-height: 34px; display: inline-flex; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 7px; background: var(--accent); color: #fff; cursor: pointer; padding: 6px 11px; font-size: 10px; }
.state-editor button:disabled, .inline-submit:disabled, .relation-form button:disabled { cursor: not-allowed; opacity: .5; }
.history-list, .anchor-list, .relation-list { display: grid; gap: 4px; }
.history-list article { display: grid; grid-template-columns: minmax(0,1fr) minmax(160px,.6fr) auto; align-items: center; gap: 10px; border-bottom: 1px solid var(--border); padding: 8px 4px; }
.history-list article.superseded { opacity: .55; }
.history-list article div { min-width: 0; display: grid; gap: 3px; }
.history-list article strong { font-size: 10px; }
.history-list article span, .history-list article small { overflow: hidden; color: var(--text-secondary); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.history-list article em { color: var(--text-muted); font-size: 9px; font-style: normal; }
.timeline-status { border-radius: 6px; background: var(--bg-secondary); color: var(--text-secondary); padding: 4px 7px; font-size: 10px; }
.timeline-create .form-grid, .anchor-editor .form-grid { grid-template-columns: repeat(4,minmax(0,1fr)); align-items: end; }
.timeline-create .inline-submit, .anchor-editor .inline-submit { min-height: 34px; }
.anchor-editor .wide { grid-column: span 2; }
.anchor-list { margin-top: 14px; }
.anchor-list article { display: grid; grid-template-columns: 32px minmax(0,1fr) auto; align-items: center; gap: 9px; border-bottom: 1px solid var(--border); padding: 8px 4px; }
.anchor-list article > span { color: var(--accent); font-size: 10px; text-align: center; }
.anchor-list article div { min-width: 0; display: grid; gap: 2px; }
.anchor-list article strong { font-size: 10px; }
.anchor-list article small { overflow: hidden; color: var(--text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.anchor-list article em { border-radius: 5px; background: var(--bg-secondary); color: var(--text-secondary); padding: 2px 5px; font-size: 9px; font-style: normal; }
.relation-form { display: grid; grid-template-columns: minmax(0,1fr) 180px minmax(0,1fr) 36px; gap: 7px; }
.relation-form select { min-height: 34px; font-size: 10px; }
.relation-form button { min-height: 34px; display: grid; place-items: center; border: 0; border-radius: 7px; background: var(--accent); color: #fff; cursor: pointer; }
.relation-list { margin-top: 12px; }
.relation-list article { display: grid; grid-template-columns: minmax(0,1fr) 150px minmax(0,1fr) auto; align-items: center; gap: 8px; border-left: 3px solid #7dc2a5; background: #f8fcfa; padding: 8px 9px; font-size: 10px; }
.relation-list article.conflict { border-left-color: #d39a3b; background: #fff8ec; }
.relation-list article span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.relation-list article strong { color: var(--text-secondary); text-align: center; }
.relation-list article em { color: var(--text-muted); font-size: 9px; font-style: normal; }
@media (max-width: 1120px) {
  .world-layout { grid-template-columns: 250px minmax(0,1fr); }
  .timeline-create .form-grid, .anchor-editor .form-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
}
@media (max-width: 820px) {
  .temporal-world-page { padding: 16px; }
  .scope-status { width: 100%; }
  .view-tabs { align-items: stretch; flex-wrap: wrap; }
  .view-tabs label { width: 100%; min-width: 0; margin-left: 0; }
  .world-layout { grid-template-columns: 1fr; }
  .entity-browser { position: static; max-height: 360px; }
  .section-header { flex-direction: column; }
  .resolve-anchor { width: 100%; min-width: 0; }
  .resolved-grid, .form-grid { grid-template-columns: 1fr; }
  .field-row.wide { grid-column: auto; }
  .timeline-create .form-grid, .anchor-editor .form-grid { grid-template-columns: 1fr; }
  .anchor-editor .wide { grid-column: auto; }
  .relation-form { grid-template-columns: 1fr; }
  .relation-form button { min-height: 36px; }
  .relation-list article { grid-template-columns: minmax(0,1fr) auto minmax(0,1fr); }
  .relation-list article em { grid-column: 1 / -1; }
  .history-list article { grid-template-columns: minmax(0,1fr) auto; }
  .history-list article small { grid-column: 1 / -1; }
}
</style>
