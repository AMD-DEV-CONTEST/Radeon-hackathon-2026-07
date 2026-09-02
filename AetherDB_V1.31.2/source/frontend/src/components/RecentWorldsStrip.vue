<script setup>
import { useAppStore } from "../stores/app.js";
import { useI18n } from "vue-i18n";
import { BookPlus, Database } from "@lucide/vue";

defineProps({
  worlds: {
    type: Array,
    default: () => [],
  },
});
const emit = defineEmits(["create-group", "create-world"]);

const store = useAppStore();
const { t } = useI18n();

async function selectWorld(world) {
  await store.selectWorld(world);
}
</script>

<template>
  <section class="recent-worlds">
    <div class="section-heading">
      <div><span>◈</span><h2>{{ t("最近访问的世界") }}</h2></div>
      <div class="section-actions">
        <button type="button" @click="emit('create-group')"><Database :size="15" />{{ t("新建分组") }}</button>
        <button type="button" @click="emit('create-world')"><BookPlus :size="15" />{{ t("新建世界") }}</button>
      </div>
    </div>

    <div v-if="worlds.length" class="world-grid">
      <button v-for="world in worlds" :key="world.id || world.title" class="world-card" :class="{ selected: world.databaseId === store.activeDatabase?.database_id && (!world.bookId || world.bookId === store.activeBook?.book_id) }" type="button" @click="selectWorld(world)">
        <div class="world-cover"></div>
        <div class="world-info">
          <strong>{{ world.title }}</strong>
          <small>{{ world.subtitle }}</small>
        </div>
        <div class="world-stats">
          <span>{{ t("实体 {count}", { count: world.entities || 0 }) }}</span>
          <span>{{ t("关系 {count}", { count: world.relations || 0 }) }}</span>
          <span>{{ t("事件 {count}", { count: world.events || 0 }) }}</span>
        </div>
      </button>
    </div>

    <div v-else class="empty-worlds">
      <p>{{ t("暂无最近访问的世界") }}</p>
      <small>{{ t("创建或打开世界后，这里会显示真实记录") }}</small>
    </div>
  </section>
</template>

<style scoped>
.recent-worlds {
  display: grid;
  gap: 12px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.section-heading > div { display: flex; align-items: center; gap: 8px; }

.section-heading h2 {
  font-size: 16px;
}

.section-heading span {
  color: var(--accent);
}

.section-actions { flex-wrap: wrap; justify-content: flex-end; }
.section-actions button { min-height: 30px; display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 7px; background: rgba(255,255,255,.9); color: var(--text-secondary); cursor: pointer; padding: 5px 9px; font-size: 11px; }
.section-actions button:hover { border-color: #cec4fb; color: var(--accent); }
.section-actions button:disabled { color: var(--text-muted); cursor: not-allowed; }

.world-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.world-card {
  display: grid;
  gap: 8px;
  min-width: 0;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.world-card.selected .world-cover {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.world-card.selected .world-info strong {
  color: var(--accent);
}

.world-cover {
  height: 68px;
  border-radius: 8px;
  background-image: url("../assets/workspace-mountains.png");
  background-size: cover;
  background-position: center;
  box-shadow: var(--soft-shadow);
}

.world-info,
.world-stats {
  min-width: 0;
}

.world-info {
  display: grid;
  gap: 2px;
}

.world-info strong,
.world-info small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.world-info strong {
  font-size: 13px;
}

.world-info small,
.world-stats {
  color: var(--text-muted);
  font-size: 11px;
}

.world-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
}

.world-stats span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-worlds {
  display: grid;
  place-items: center;
  min-height: 120px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  color: var(--text-muted);
  text-align: center;
}

.empty-worlds p {
  color: var(--text-secondary);
  font-size: 14px;
}

.empty-worlds small {
  font-size: 12px;
}

@media (max-width: 1180px) {
  .world-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 620px) { .section-heading { align-items: flex-start; flex-direction: column; } .section-actions { width: 100%; } .section-actions button { flex: 1; } }
</style>
