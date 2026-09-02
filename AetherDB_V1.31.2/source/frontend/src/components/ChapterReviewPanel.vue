<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { AlertTriangle, Check, Clock3, Database, FileClock, GitMerge, RefreshCw } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();
const activeTab = ref("review");

const groups = computed(() => {
  const changeSet = store.pendingChangeSet || {};
  return [
    { key: "entities", label: "实体候选", count: changeSet.entities?.length || 0, icon: Database },
    { key: "relations", label: "关系变更", count: changeSet.relations?.length || 0, icon: GitMerge },
    { key: "conflicts", label: "冲突", count: changeSet.conflicts?.length || 0, icon: AlertTriangle },
  ];
});

const previewEntities = computed(() => (store.pendingChangeSet?.entities || []).slice(0, 6));
const previewRelations = computed(() => (store.pendingChangeSet?.relations || []).slice(0, 6));

function relationLabel(relation) {
  return `${relation.source || "?"} -> ${relation.relation_type || "related_to"} -> ${relation.target || "?"}`;
}

watch(() => store.activeChapter?.chapter_id, () => {
  if (activeTab.value === "versions") store.loadChapterVersions();
});

watch(activeTab, (tab) => {
  if (tab === "versions") store.loadChapterVersions();
});

onMounted(() => {
  if (activeTab.value === "versions") store.loadChapterVersions();
});
</script>

<template>
  <aside class="review-panel">
    <header class="review-header">
      <div class="review-tabs">
        <button type="button" :class="{ active: activeTab === 'review' }" @click="activeTab = 'review'">{{ t("审核与绑定") }}</button>
        <button type="button" :class="{ active: activeTab === 'versions' }" @click="activeTab = 'versions'">{{ t("版本历史") }}</button>
      </div>
      <button type="button" :title="t('刷新')" @click="activeTab === 'versions' ? store.loadChapterVersions() : store.createDraftChangeSet()"><RefreshCw :size="15" /></button>
    </header>

    <div v-if="activeTab === 'review'" class="review-content">
      <template v-if="store.pendingChangeSet">
        <div class="review-state" :class="{ confirmed: store.pendingChangeSet.status === 'confirmed' }">
          <span><Check v-if="store.pendingChangeSet.status === 'confirmed'" :size="16" /><Clock3 v-else :size="16" /></span>
          <div><strong>{{ t(store.pendingChangeSet.status === "confirmed" ? "变更已确认" : "等待作者确认") }}</strong><small>{{ store.pendingChangeSet.changeset_id }}</small></div>
        </div>
        <div class="change-groups">
          <div v-for="group in groups" :key="group.key">
            <component :is="group.icon" :size="15" />
            <span><small>{{ t(group.label) }}</small><strong>{{ group.count }}</strong></span>
          </div>
        </div>
        <div v-if="previewEntities.length || previewRelations.length" class="change-preview">
          <section v-if="previewEntities.length">
            <strong>{{ t("实体样例") }}</strong>
            <span v-for="entity in previewEntities" :key="entity.candidate_id || entity.title">{{ entity.title }} · {{ entity.type || "entity" }}</span>
          </section>
          <section v-if="previewRelations.length">
            <strong>{{ t("关系样例") }}</strong>
            <span v-for="relation in previewRelations" :key="relation.candidate_id || relationLabel(relation)">{{ relationLabel(relation) }}</span>
          </section>
        </div>
        <div v-if="store.pendingChangeSet.conflicts?.length" class="conflict-list">
          <strong>{{ t("需要处理的冲突") }}</strong>
          <p v-for="(item, index) in store.pendingChangeSet.conflicts" :key="index">{{ item.message || item.description || String(item) }}</p>
        </div>
        <button
          class="confirm-button"
          type="button"
          :disabled="store.pendingChangeSet.status === 'confirmed' || store.confirmingChangeSet"
          @click="store.confirmPendingChapterChangeSet()"
        >
          <Check :size="16" />{{ t(store.confirmingChangeSet ? "正在写入" : "确认并写入设定库") }}
        </button>
      </template>
      <div v-else class="panel-empty">
        <GitMerge :size="25" />
        <strong>{{ t("暂无章节分析结果") }}</strong>
        <small>{{ t("分析只生成候选预览，确认前不会修改世界设定。") }}</small>
        <button type="button" :disabled="!store.activeChapter || store.analysisLoading" @click="store.createDraftChangeSet()">
          {{ t(store.analysisLoading ? "正在分析" : "分析当前章节") }}
        </button>
      </div>
    </div>

    <div v-else class="version-content">
      <div v-if="!store.chapterVersions.length" class="panel-empty compact">
        <FileClock :size="24" /><strong>{{ t("暂无正式版本") }}</strong><small>{{ t("手动保存超过 100 字的正文后会建立版本记录。") }}</small>
      </div>
      <button v-for="version in store.chapterVersions" :key="version.version_id" type="button" @click="store.notifyAction(t('版本 {version} 为只读记录', { version: version.version }))">
        <span>v{{ version.version }}</span>
        <span><strong>{{ version.title || store.chapterTitle }}</strong><small>{{ t("{count} 字", { count: version.word_count || 0 }) }} · {{ version.saved_at || "" }}</small></span>
      </button>
    </div>

    <p v-if="store.chapterError" class="panel-error">{{ store.chapterError }}</p>
  </aside>
</template>

<style scoped>
.review-panel { min-width: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); }
.review-header { min-height: 46px; display: flex; align-items: center; justify-content: space-between; gap: 8px; border-bottom: 1px solid var(--border); padding: 0 10px; }
.review-header > button { width: 30px; height: 30px; display: grid; place-items: center; border: 0; border-radius: 6px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.review-header > button:hover { background: var(--accent-soft); color: var(--accent); }
.review-tabs { align-self: stretch; display: flex; gap: 12px; }
.review-tabs button { position: relative; border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 11px; }
.review-tabs button.active { color: var(--accent); font-weight: 700; }
.review-tabs button.active::after { content: ""; position: absolute; inset: auto 0 0; height: 2px; background: var(--accent); }
.review-content, .version-content { display: grid; gap: 12px; padding: 12px; }
.review-state { display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 9px; border: 1px solid #ead9b7; border-radius: 7px; background: #fff9ef; color: #9a5b18; padding: 10px; }
.review-state.confirmed { border-color: #c9ebdc; background: #eefbf5; color: #157353; }
.review-state > span { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: #fff; }
.review-state > div { min-width: 0; display: grid; gap: 2px; }
.review-state strong, .review-state small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.review-state strong { font-size: 12px; }
.review-state small { opacity: .72; font-size: 9px; }
.change-groups { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 6px; }
.change-groups > div { min-width: 0; display: flex; align-items: center; gap: 7px; border: 1px solid var(--border); border-radius: 7px; padding: 8px; }
.change-groups > div > span { min-width: 0; display: grid; gap: 2px; }
.change-groups small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 9px; }
.change-groups strong { font-size: 14px; }
.change-preview { display: grid; gap: 8px; }
.change-preview section { display: grid; gap: 5px; border: 1px solid var(--border); border-radius: 7px; background: #fff; padding: 8px; }
.change-preview strong { color: var(--text-primary); font-size: 11px; }
.change-preview span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-size: 9px; }
.conflict-list { display: grid; gap: 6px; border-left: 3px solid #d19a46; background: #fffaf1; padding: 9px; }
.conflict-list strong { font-size: 11px; }
.conflict-list p { color: var(--text-secondary); font-size: 10px; line-height: 1.5; }
.confirm-button, .panel-empty button { min-height: 34px; display: inline-flex; justify-content: center; align-items: center; gap: 6px; border: 0; border-radius: 7px; background: var(--accent); color: #fff; cursor: pointer; padding: 6px 10px; font-size: 11px; }
.confirm-button:disabled, .panel-empty button:disabled { background: #aaa5ba; cursor: not-allowed; }
.panel-empty { min-height: 220px; display: grid; place-items: center; align-content: center; gap: 8px; color: var(--text-muted); text-align: center; }
.panel-empty.compact { min-height: 150px; }
.panel-empty strong { color: var(--text-secondary); font-size: 12px; }
.panel-empty small { max-width: 230px; line-height: 1.55; font-size: 10px; }
.version-content > button { min-width: 0; display: grid; grid-template-columns: 38px minmax(0,1fr); align-items: center; gap: 9px; border: 1px solid var(--border); border-radius: 7px; background: #fff; cursor: pointer; padding: 8px; text-align: left; }
.version-content > button > span:first-child { color: var(--accent); font-size: 11px; font-weight: 700; }
.version-content > button > span:last-child { min-width: 0; display: grid; gap: 2px; }
.version-content strong, .version-content small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-content strong { font-size: 11px; }
.version-content small { color: var(--text-muted); font-size: 9px; }
.panel-error { margin: 0 12px 12px; border-radius: 7px; background: #fff0f0; color: #a84040; padding: 8px; font-size: 10px; }
@media (max-width: 1380px) { .change-groups { grid-template-columns: 1fr; } }
</style>
