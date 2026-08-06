<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { globalSearch, searchByKeyword, semanticSearch } from "../api/search.js";
import { getActiveBook, getActiveDatabase } from "../api/settings.js";
import { entityPreview, normalizeEntityList } from "../domain/entities.js";

const query = ref("");
const { t } = useI18n();
const mode = ref("keyword");
const scope = ref("book");
const loading = ref(false);
const error = ref("");
const searched = ref(false);
const results = ref([]);
const databaseId = ref("");
const bookId = ref("");

const modes = [
  { key: "keyword", label: "关键词", description: "标题、正文、摘要匹配" },
  { key: "semantic", label: "语义", description: "向量与全文混合检索" },
  { key: "global", label: "全局", description: "跨数据库与作品检索" },
];
const scopes = [
  { key: "book", label: "当前作品" },
  { key: "database", label: "当前世界库" },
  { key: "all", label: "全部世界库" },
];

const activeMode = computed(() => modes.find((item) => item.key === mode.value));

async function loadContext() {
  const [database, book] = await Promise.allSettled([getActiveDatabase(), getActiveBook()]);
  if (database.status === "fulfilled") databaseId.value = database.value?.active_database_id || "";
  if (book.status === "fulfilled") bookId.value = book.value?.active_book_id || "";
}

async function runSearch() {
  const text = query.value.trim();
  if (!text) {
    error.value = t("请输入搜索内容");
    return;
  }

  loading.value = true;
  error.value = "";
  searched.value = true;

  try {
    let payload;
    if (mode.value === "semantic") {
      if (!databaseId.value || !bookId.value) await loadContext();
      if (!databaseId.value || !bookId.value) throw new Error(t("请先选择当前世界库与作品"));
      payload = await semanticSearch({ query: text, top_k: 30, database_id: databaseId.value, book_id: bookId.value });
    } else if (mode.value === "global") {
      if (!databaseId.value || !bookId.value) await loadContext();
      payload = await globalSearch(text, { scope: scope.value, databaseId: databaseId.value, bookId: bookId.value, limit: 30 });
    } else {
      payload = await searchByKeyword({ keyword: text, limit: 30 });
    }
    results.value = normalizeEntityList(payload);
  } catch (err) {
    results.value = [];
    error.value = err.message || t("搜索失败，请确认服务已启动");
  } finally {
    loading.value = false;
  }
}

onMounted(loadContext);
</script>

<template>
  <div class="page-shell search-page">
    <header class="page-header">
      <div>
        <h1>{{ t("搜索") }}</h1>
        <p>{{ t("在当前世界、语义索引或全局索引中查找实体与设定。") }}</p>
      </div>
      <span class="status-pill">{{ t(activeMode.description) }}</span>
    </header>

    <section class="panel search-panel">
      <div class="mode-tabs">
        <button
          v-for="item in modes"
          :key="item.key"
          type="button"
          :class="{ active: mode === item.key }"
          @click="mode = item.key"
        >
          <strong>{{ t(item.label) }}</strong>
          <small>{{ t(item.description) }}</small>
        </button>
      </div>

      <form class="search-form" @submit.prevent="runSearch">
        <input v-model="query" :placeholder="t('输入人物、地点、规则、事件或自然语言问题...')" />
        <button class="btn btn-primary" type="submit" :disabled="loading">
          {{ t(loading ? "搜索中..." : "开始搜索") }}
        </button>
      </form>
      <div class="scope-row" :aria-label="t('搜索范围')">
        <span>{{ t("搜索范围") }}</span>
        <button
          v-for="item in scopes"
          :key="item.key"
          type="button"
          :class="{ active: scope === item.key }"
          @click="scope = item.key"
        >
          {{ t(item.label) }}
        </button>
      </div>
    </section>

    <section class="panel results-panel">
      <h2 class="panel-title">{{ t("搜索结果") }}</h2>
      <div v-if="error" class="empty-state">
        <strong>{{ error }}</strong>
        <small>{{ t("页面已保持可用。修复服务或调整关键词后可以重试。") }}</small>
      </div>
      <div v-else-if="loading" class="empty-state">
        <strong>{{ t("正在检索") }}</strong>
        <small>{{ t("正在从 {mode} 搜索中整理结果。", { mode: t(activeMode.label) }) }}</small>
      </div>
      <div v-else-if="results.length" class="result-grid">
        <article v-for="entity in results" :key="entity.id || entity.title" class="result-card">
          <div class="result-head">
            <span class="type-badge">{{ t(entity.typeLabel) }}</span>
            <span class="score">{{ t("重要度 {value}", { value: entity.importance || 0 }) }}</span>
          </div>
          <h3>{{ entity.title }}</h3>
          <p>{{ entityPreview(entity) }}</p>
          <div class="tag-list">
            <span v-for="tag in entity.tags.slice(0, 5)" :key="tag" class="tag">{{ tag }}</span>
          </div>
        </article>
      </div>
      <div v-else class="empty-state">
        <strong>{{ t(searched ? "没有找到匹配结果" : "等待搜索") }}</strong>
        <small>{{ t(searched ? "可以切换搜索模式或减少关键词限制。" : "输入关键词后会在这里显示数据驱动的搜索结果。") }}</small>
      </div>
    </section>
  </div>
</template>

<style scoped>
.search-page {
  display: grid;
  gap: 18px;
}

.search-panel {
  display: grid;
  gap: 16px;
}

.mode-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.mode-tabs button {
  display: grid;
  gap: 4px;
  min-height: 66px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.7);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  padding: 12px;
}

.mode-tabs button.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.mode-tabs small {
  color: var(--text-secondary);
  font-size: 12px;
}

.search-form {
  display: grid;
  grid-template-columns: 1fr 128px;
  gap: 12px;
}

.scope-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.scope-row span {
  color: var(--text-secondary);
  font-size: 12px;
}

.scope-row button {
  min-height: 30px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: rgba(255,255,255,0.7);
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px 10px;
  font-size: 12px;
}

.scope-row button.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.result-card {
  display: grid;
  gap: 10px;
  min-height: 170px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.78);
  padding: 14px;
}

.result-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.type-badge {
  color: var(--accent);
}

.result-card h3 {
  font-size: 16px;
}

.result-card p {
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 760px) {
  .mode-tabs,
  .search-form {
    grid-template-columns: 1fr;
  }
}
</style>
