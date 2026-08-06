<script setup>
import { useI18n } from "vue-i18n";
import { CalendarDays, Files, GitFork, Milestone, Tags, UsersRound } from "@lucide/vue";

defineProps({
  stats: {
    type: Object,
    required: true,
  },
});

const { locale, t } = useI18n();
const items = [
  { key: "entities", label: "实体总数", icon: UsersRound },
  { key: "relations", label: "关系总数", icon: GitFork },
  { key: "events", label: "事件总数", icon: CalendarDays },
  { key: "timeline", label: "时间线节点", icon: Milestone },
  { key: "tags", label: "标签总数", icon: Tags },
  { key: "documents", label: "文档总数", icon: Files },
];

function formatNumber(value) {
  return Number(value || 0).toLocaleString(locale.value);
}
</script>

<template>
  <section class="panel">
    <header class="panel-header">
      <h2>{{ t("世界概览") }}</h2>
      <button type="button">{{ t("查看全部") }} ›</button>
    </header>
    <div class="overview-grid">
      <div v-for="item in items" :key="item.key" class="overview-item">
        <span class="item-icon"><component :is="item.icon" :size="14" /></span>
        <span class="item-copy">
          <small>{{ t(item.label) }}</small>
          <strong>{{ formatNumber(stats[item.key]) }}</strong>
        </span>
      </div>
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

.panel-header {
  display: flex;
  align-items: center;
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

.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 16px;
}

.overview-item {
  display: flex;
  gap: 10px;
  align-items: center;
  min-width: 0;
}

.item-icon {
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
}

.item-copy {
  display: grid;
  min-width: 0;
}

.item-copy small {
  color: var(--text-muted);
  font-size: 11px;
}

.item-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 16px;
}
</style>
