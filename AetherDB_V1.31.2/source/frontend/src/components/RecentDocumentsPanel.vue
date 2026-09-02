<script setup>
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { FileText, Plus } from "@lucide/vue";

defineProps({
  documents: {
    type: Array,
    default: () => [],
  },
});

const router = useRouter();
const { t } = useI18n();

function openDocument() {
  router.push("/reader");
}
</script>

<template>
  <section class="panel">
    <header class="panel-header">
      <h2>{{ t("最近文档") }}</h2>
      <button type="button" @click="router.push('/worlds')">{{ t("查看全部") }} ›</button>
    </header>

    <div v-if="documents.length" class="doc-list">
      <button v-for="doc in documents" :key="doc.id || doc.title" type="button" class="doc-item" @click="openDocument(doc)">
        <span class="doc-icon"><FileText :size="16" /></span>
        <span class="doc-main">
          <strong>{{ doc.title }}</strong>
          <small>{{ doc.updatedAt || t("最近更新") }}</small>
        </span>
        <span class="doc-type">{{ doc.type }}</span>
      </button>
    </div>
    <div v-else class="empty">
      <span><Plus :size="24" /></span>
      <p>{{ t("暂无最近文档") }}</p>
      <small>{{ t("开始写作后会在这里显示最近更新") }}</small>
    </div>
  </section>
</template>

<style scoped>
.panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.9);
  box-shadow: var(--soft-shadow);
  padding: 16px;
}

.panel-header,
.doc-item {
  display: flex;
  align-items: center;
}

.panel-header {
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-header h2 {
  font-size: 16px;
}

.panel-header button {
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
}

.doc-list {
  display: grid;
  gap: 10px;
}

.doc-item {
  width: 100%;
  gap: 10px;
  min-height: 42px;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.doc-item:hover .doc-main strong {
  color: var(--accent);
}

.doc-icon {
  color: var(--accent);
}

.doc-main {
  display: grid;
  min-width: 0;
  flex: 1;
}

.doc-main strong,
.doc-main small,
.doc-type {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-main strong {
  font-size: 13px;
}

.doc-main small,
.doc-type {
  color: var(--text-muted);
  font-size: 11px;
}

.doc-type {
  max-width: 64px;
}

.empty {
  display: grid;
  place-items: center;
  gap: 4px;
  min-height: 112px;
  color: var(--text-muted);
  text-align: center;
}

.empty span {
  font-size: 26px;
}

.empty p {
  color: var(--text-secondary);
  font-size: 13px;
}

.empty small {
  font-size: 11px;
}
</style>
