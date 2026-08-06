<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { Check, Languages, Save, ShieldAlert, X } from "@lucide/vue";
import {
  getEntities,
  getEntity,
  getEntityTranslations,
  reviewEntityTranslation,
  saveEntityTranslation,
} from "../api/entities.js";
import { ENTITY_TYPE_LABELS, entityPreview, normalizeEntity, normalizeEntityList } from "../domain/entities.js";
import { useAppStore } from "../stores/app.js";

const entities = ref([]);
const store = useAppStore();
const { t } = useI18n();
const selected = ref(null);
const loading = ref(true);
const detailLoading = ref(false);
const error = ref("");
const typeFilter = ref("all");
const query = ref("");
const entityTranslations = ref([]);
const translationLanguage = ref("en-US");
const translationTitle = ref("");
const translationContent = ref("");
const translationLoading = ref(false);
const translationError = ref("");

const languageOptions = [
  { value: "zh-CN", label: "简体中文" },
  { value: "en-US", label: "英语" },
];

const typeOptions = computed(() => [
  { key: "all", label: "全部" },
  ...Object.entries(ENTITY_TYPE_LABELS).map(([key, label]) => ({ key, label })),
]);

const filteredEntities = computed(() => {
  const q = query.value.trim().toLowerCase();
  return entities.value.filter((entity) => {
    const typeMatched = typeFilter.value === "all" || entity.type === typeFilter.value;
    const queryMatched = !q || entity.title.toLowerCase().includes(q) || entity.content.toLowerCase().includes(q);
    return typeMatched && queryMatched;
  });
});
const activeTranslation = computed(() => (
  entityTranslations.value.find((item) => item.language === translationLanguage.value) || null
));
const availableTranslationLanguages = computed(() => {
  const sourceLanguage = activeTranslation.value?.source_language_code
    || entityTranslations.value[0]?.source_language_code
    || "zh-CN";
  return languageOptions.filter((item) => item.value !== sourceLanguage);
});
const canManageTranslations = computed(() => store.hasCapability("manage_translations"));
const canApproveTranslation = computed(() => (
  activeTranslation.value?.translation_status === "draft"
  && Boolean(activeTranslation.value?.source_hash)
));

async function loadEntities() {
  loading.value = true;
  error.value = "";
  try {
    entities.value = normalizeEntityList(await getEntities({ limit: 120 }));
    if (entities.value.length) await selectEntity(entities.value[0]);
  } catch (err) {
    error.value = err.message || t("阅读数据加载失败");
  } finally {
    loading.value = false;
  }
}

async function selectEntity(entity) {
  selected.value = entity;
  detailLoading.value = true;
  translationError.value = "";
  try {
    if (entity.id) {
      selected.value = normalizeEntity(await getEntity(entity.id));
      await loadEntityTranslations();
    }
  } catch {
    selected.value = entity;
    entityTranslations.value = [];
    syncTranslationDraft();
  } finally {
    detailLoading.value = false;
  }
}

function languageLabel(code) {
  return t(languageOptions.find((item) => item.value === code)?.label || code);
}

function translationStatusLabel(status) {
  return t({
    draft: "草稿",
    approved: "已批准",
    rejected: "已拒绝",
    stale: "需要复核",
  }[status] || "尚无译文");
}

function syncTranslationDraft() {
  const translation = activeTranslation.value;
  translationTitle.value = translation?.title || "";
  translationContent.value = translation?.full_content || translation?.content || "";
}

async function loadEntityTranslations() {
  if (!selected.value?.id) {
    entityTranslations.value = [];
    syncTranslationDraft();
    return;
  }
  translationLoading.value = true;
  translationError.value = "";
  try {
    entityTranslations.value = await getEntityTranslations(selected.value.id);
    const available = availableTranslationLanguages.value.map((item) => item.value);
    if (!available.includes(translationLanguage.value)) {
      translationLanguage.value = available[0] || "en-US";
    }
    syncTranslationDraft();
  } catch (err) {
    entityTranslations.value = [];
    syncTranslationDraft();
    translationError.value = err?.message || t("实体译文读取失败");
  } finally {
    translationLoading.value = false;
  }
}

function changeTranslationLanguage(event) {
  translationLanguage.value = event.target.value;
  syncTranslationDraft();
}

async function saveTranslationDraft() {
  if (
    !selected.value?.id
    || !translationTitle.value.trim()
    || !translationContent.value.trim()
  ) return;
  translationLoading.value = true;
  translationError.value = "";
  try {
    const saved = await saveEntityTranslation(selected.value.id, {
      book_id: selected.value.bookId || null,
      language: translationLanguage.value,
      title: translationTitle.value.trim(),
      content: translationContent.value,
      full_content: translationContent.value,
      ai_summary: "",
    });
    await loadEntityTranslations();
    const current = entityTranslations.value.find((item) => item.id === saved.id);
    if (current) translationLanguage.value = current.language;
    syncTranslationDraft();
    store.notifyAction(t("实体译文草稿已保存"));
  } catch (err) {
    translationError.value = err?.message || t("实体译文保存失败");
  } finally {
    translationLoading.value = false;
  }
}

async function reviewTranslation(action) {
  const translation = activeTranslation.value;
  if (!translation?.id || !translation.source_hash) return;
  translationLoading.value = true;
  translationError.value = "";
  try {
    await reviewEntityTranslation(translation.id, {
      action,
      expected_source_hash: translation.source_hash,
    });
    await loadEntityTranslations();
    store.notifyAction(t(action === "approve" ? "实体译文已批准" : "实体译文已拒绝"));
  } catch (err) {
    translationError.value = err?.message || t("实体译文审核失败");
  } finally {
    translationLoading.value = false;
  }
}

onMounted(loadEntities);
</script>

<template>
  <div class="page-shell reader-page">
    <header class="page-header">
      <div>
        <h1>{{ t("阅读模式") }}</h1>
        <p>{{ t("以文档阅读方式查看实体、设定、摘要、标签和时间线信息。") }}</p>
      </div>
      <span class="status-pill">{{ t("{count} 项内容", { count: filteredEntities.length }) }}</span>
    </header>

    <div class="reader-layout">
      <aside class="panel reader-list">
        <h2 class="panel-title">{{ t("内容列表") }}</h2>
        <input v-model="query" :placeholder="t('筛选标题或正文...')" />
        <div class="type-filter">
          <button
            v-for="option in typeOptions"
            :key="option.key"
            type="button"
            :class="{ active: typeFilter === option.key }"
            @click="typeFilter = option.key"
          >
            {{ t(option.label) }}
          </button>
        </div>

        <div v-if="loading" class="empty-state compact">
          <strong>{{ t("正在加载") }}</strong>
        </div>
        <div v-else-if="error" class="empty-state compact">
          <strong>{{ error }}</strong>
        </div>
        <div v-else-if="!filteredEntities.length" class="empty-state compact">
          <strong>{{ t("暂无匹配内容") }}</strong>
        </div>
        <div v-else class="doc-list">
          <button
            v-for="entity in filteredEntities"
            :key="entity.id"
            type="button"
            :class="{ active: selected?.id === entity.id }"
            @click="selectEntity(entity)"
          >
            <strong>{{ entity.title }}</strong>
            <small>{{ t(entity.typeLabel) }} · {{ entity.updatedAt || t("未记录更新时间") }}</small>
          </button>
        </div>
      </aside>

      <main class="panel reader-detail">
        <div v-if="!selected" class="empty-state">
          <strong>{{ t("未选择内容") }}</strong>
          <small>{{ t("从左侧选择实体或设定后会在这里进入阅读视图。") }}</small>
        </div>
        <article v-else class="article">
          <div class="article-meta">
            <span class="status-pill">{{ t(selected.typeLabel) }}</span>
            <span v-if="detailLoading" class="muted">{{ t("正在刷新详情...") }}</span>
          </div>
          <h2>{{ selected.title }}</h2>
          <p class="summary">{{ entityPreview(selected) }}</p>
          <div class="tag-list">
            <span v-for="tag in selected.tags" :key="tag" class="tag">{{ tag }}</span>
          </div>
          <section>
            <h3>{{ t("正文") }}</h3>
            <p class="content">{{ selected.fullContent || selected.content || t("暂无正文内容。") }}</p>
          </section>
          <section
            v-if="canManageTranslations || entityTranslations.length"
            class="entity-translation"
          >
            <header>
              <span>
                <Languages :size="17" />
                <strong>{{ t("实体译文") }}</strong>
              </span>
              <span class="translation-status">
                {{ translationStatusLabel(activeTranslation?.translation_status) }}
              </span>
            </header>
            <div class="translation-fields">
              <label>
                <span>{{ t("目标语言") }}</span>
                <select
                  :value="translationLanguage"
                  :disabled="translationLoading"
                  @change="changeTranslationLanguage"
                >
                  <option
                    v-for="option in availableTranslationLanguages"
                    :key="option.value"
                    :value="option.value"
                  >
                    {{ languageLabel(option.value) }}
                  </option>
                </select>
              </label>
              <label>
                <span>{{ t("译文标题") }}</span>
                <input
                  v-model="translationTitle"
                  :readonly="!canManageTranslations"
                  :placeholder="t('输入译文标题')"
                />
              </label>
            </div>
            <label class="translation-content">
              <span>{{ t("译文正文") }}</span>
              <textarea
                v-model="translationContent"
                :readonly="!canManageTranslations"
                :placeholder="t('输入译文正文')"
              ></textarea>
            </label>
            <p v-if="translationError" class="translation-error">
              <ShieldAlert :size="15" />{{ translationError }}
            </p>
            <footer v-if="canManageTranslations">
              <button
                class="btn btn-secondary"
                type="button"
                :disabled="translationLoading || !translationTitle.trim() || !translationContent.trim()"
                @click="saveTranslationDraft"
              >
                <Save :size="14" />{{ t("保存译文草稿") }}
              </button>
              <button
                v-if="canApproveTranslation"
                class="btn btn-primary"
                type="button"
                :disabled="translationLoading"
                @click="reviewTranslation('approve')"
              >
                <Check :size="14" />{{ t("批准译文") }}
              </button>
              <button
                v-if="activeTranslation && activeTranslation.translation_status !== 'rejected'"
                class="btn btn-secondary"
                type="button"
                :disabled="translationLoading"
                @click="reviewTranslation('reject')"
              >
                <X :size="14" />{{ t("拒绝译文") }}
              </button>
            </footer>
          </section>
          <section class="facts">
            <div>
              <small>{{ t("时间线") }}</small>
              <strong>{{ selected.timelineEra || t("未设置") }} {{ selected.timelineYear || "" }}</strong>
            </div>
            <div>
              <small>{{ t("关系数量") }}</small>
              <strong>{{ selected.relationCount || selected.raw?.relations?.length || 0 }}</strong>
            </div>
            <div>
              <small>{{ t("重要度") }}</small>
              <strong>{{ selected.importance || 0 }}</strong>
            </div>
          </section>
        </article>
      </main>
    </div>
  </div>
</template>

<style scoped>
.reader-layout {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.reader-list {
  display: grid;
  gap: 12px;
  max-height: calc(100vh - 120px);
  overflow: auto;
}

.type-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.type-filter button {
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 5px 10px;
  font-size: 12px;
}

.type-filter button.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.doc-list {
  display: grid;
  gap: 8px;
}

.doc-list button {
  display: grid;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.66);
  cursor: pointer;
  text-align: left;
  padding: 10px;
}

.doc-list button.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.doc-list strong,
.doc-list small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-list small,
.muted {
  color: var(--text-muted);
  font-size: 12px;
}

.reader-detail {
  min-height: calc(100vh - 120px);
}

.article {
  display: grid;
  gap: 18px;
  max-width: 860px;
}

.article-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.article h2 {
  font-size: 30px;
  line-height: 1.2;
}

.summary {
  color: var(--text-secondary);
  line-height: 1.8;
}

.article h3 {
  margin-bottom: 8px;
  font-size: 16px;
}

.content {
  color: var(--text-primary);
  line-height: 2;
  white-space: pre-wrap;
}

.entity-translation {
  display: grid;
  gap: 12px;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: #fbfbfd;
  padding: 14px 0;
}

.entity-translation header,
.entity-translation header span,
.entity-translation footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.entity-translation header {
  justify-content: space-between;
}

.translation-status {
  color: var(--text-muted);
  font-size: 12px;
}

.translation-fields {
  display: grid;
  grid-template-columns: minmax(150px, .45fr) minmax(0, 1fr);
  gap: 10px;
}

.translation-fields label,
.translation-content {
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 12px;
}

.translation-fields input,
.translation-fields select,
.translation-content textarea {
  width: 100%;
}

.translation-content textarea {
  min-height: 180px;
  resize: vertical;
  line-height: 1.75;
}

.translation-error {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--danger);
  font-size: 12px;
}

.entity-translation footer {
  flex-wrap: wrap;
}

.facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.facts div {
  display: grid;
  gap: 5px;
  border-radius: 8px;
  background: var(--bg-secondary);
  padding: 12px;
}

.facts small {
  color: var(--text-muted);
  font-size: 12px;
}

.compact {
  min-height: 110px;
}

@media (max-width: 980px) {
  .reader-layout,
  .facts,
  .translation-fields {
    grid-template-columns: 1fr;
  }

  .reader-list {
    max-height: none;
  }
}
</style>
