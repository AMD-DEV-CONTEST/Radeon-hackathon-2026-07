<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { BookOpen, Bot, CalendarClock, ChevronDown, Clock3, Expand, Images, Layers3, Maximize2, Star } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";
import ChapterTemporalPanel from "../components/ChapterTemporalPanel.vue";
import ChapterReviewPanel from "../components/ChapterReviewPanel.vue";
import ContextAssistantPanel from "../components/ContextAssistantPanel.vue";
import ImmersiveAssistantPanel from "../components/ImmersiveAssistantPanel.vue";
import MediaWorkbenchPanel from "../components/MediaWorkbenchPanel.vue";
import WorkspaceEditor from "../components/WorkspaceEditor.vue";
import WorkspaceNavigator from "../components/WorkspaceNavigator.vue";

const route = useRoute();
const router = useRouter();
const { locale, t } = useI18n();
const store = useAppStore();
const immersive = computed(() => route.query.mode === "immersive");
const favorite = ref(localStorage.getItem("aetherdb_workspace_favorite") === "true");
const workbenchMode = ref("writing");
const currentVersion = computed(() => store.chapterVersions[0]?.version ? `v${store.chapterVersions[0].version}` : t("草稿"));

function formatNumber(value) {
  return Number(value || 0).toLocaleString(locale.value);
}

function enterImmersive() {
  if (store.requestImmersiveWriting()) router.push({ path: "/workspace", query: { mode: "immersive" } });
}

function exitImmersive() {
  store.setImmersiveWriting(false);
  router.push("/workspace");
}

function toggleFavorite() {
  favorite.value = !favorite.value;
  localStorage.setItem("aetherdb_workspace_favorite", String(favorite.value));
  store.notifyAction(t(favorite.value ? "已收藏当前创作页" : "已取消收藏"));
}

watch(immersive, (value) => store.setImmersiveWriting(value), { immediate: true });
onMounted(async () => {
  if (!store.databases.length) await store.fetchDashboard();
  if (store.activeChapter) await store.loadChapterVersions();
  if (immersive.value && !store.canEnterImmersive) exitImmersive();
});
</script>

<template>
  <div v-if="immersive" class="immersive-page">
    <header class="focus-topbar">
      <button class="world-context" type="button" @click="router.push('/')"><span>{{ store.currentWorldName.slice(0,1) }}</span><strong>{{ store.currentWorldName }}</strong><ChevronDown :size="15" /></button>
      <div class="chapter-context"><small>{{ t("当前章节") }}</small><strong>{{ store.chapterMeta.volume }} · {{ store.chapterMeta.chapterNo }} · {{ store.chapterTitle }}</strong></div>
      <div class="focus-status"><span><i :class="{ dirty: store.chapterDirty }"></i>{{ store.chapterSaving ? t("正在保存") : store.chapterDirty ? t("有未保存修改") : store.lastSavedAt ? t("已保存于 {time}", { time: store.lastSavedAt }) : t("尚未保存") }}</span><span>{{ t("{count} 字", { count: formatNumber(store.todayWords) }) }}</span></div>
    </header>
    <div class="focus-body">
      <main class="focus-editor"><WorkspaceEditor immersive @exit-immersive="exitImmersive" /></main>
      <ImmersiveAssistantPanel />
    </div>
    <div v-if="store.actionMessage" class="focus-toast">{{ store.actionMessage }}</div>
  </div>

  <div v-else class="workspace-page">
    <header class="workspace-context-bar">
      <div class="context-breadcrumbs">
        <div><small>{{ t("数据库") }}</small><strong>{{ store.activeDatabase?.name || store.activeDatabase?.database_id || t("未选择") }}</strong></div>
        <div><small>{{ t("作品") }}</small><strong>{{ store.activeBook?.title || t("未选择") }}</strong></div>
        <div><small>{{ t("章节") }}</small><strong>{{ store.activeChapter ? `${store.chapterMeta.chapterNo}《${store.chapterTitle}》` : t("未创建") }}</strong></div>
        <div><small>{{ t("版本") }}</small><strong>{{ currentVersion }}</strong></div>
      </div>
      <div class="context-actions">
        <button type="button" :disabled="!store.activeBook" @click="store.createChapterDraft()"><Layers3 :size="15" />{{ t("新建章节") }}</button>
        <button type="button" :disabled="!store.canEnterImmersive" @click="enterImmersive"><Expand :size="15" />{{ t("沉浸模式") }}</button>
        <button type="button" :class="{ active: favorite }" @click="toggleFavorite"><Star :size="15" :fill="favorite ? 'currentColor' : 'none'" />{{ t(favorite ? "取消收藏" : "收藏本页") }}</button>
      </div>
    </header>

    <section v-if="!store.canEnterImmersive" class="world-required">
      <BookOpen :size="24" />
      <div><strong>{{ t("请先选择数据库和作品") }}</strong><p>{{ t("章节正文必须归属于明确作品；选择后才能保存、分析或进入沉浸模式。") }}</p></div>
      <button type="button" @click="router.push('/')">{{ t("返回首页选择") }}</button>
    </section>

    <div class="creation-workbench" :class="{ 'wide-mode': workbenchMode !== 'writing' }">
      <WorkspaceNavigator class="workbench-navigation" />
      <main class="workbench-main">
        <nav class="mode-tabs" :aria-label="t('创作模式')">
          <button :class="{ active: workbenchMode === 'writing' }" type="button" @click="workbenchMode = 'writing'"><BookOpen :size="15" />{{ t("正文创作") }}</button>
          <button :class="{ active: workbenchMode === 'assistant' }" type="button" :disabled="!store.activeBook" @click="workbenchMode = 'assistant'"><Bot :size="15" />{{ t("上下文助手") }}</button>
          <button :class="{ active: workbenchMode === 'temporal' }" type="button" :disabled="!store.activeChapter" @click="workbenchMode = 'temporal'"><CalendarClock :size="15" />{{ t("时间上下文") }}</button>
          <button :class="{ active: workbenchMode === 'media' }" type="button" @click="workbenchMode = 'media'"><Images :size="15" />{{ t("媒体资产") }}</button>
          <button v-if="workbenchMode === 'writing'" type="button" :disabled="!store.activeChapter" @click="store.createDraftChangeSet()"><Maximize2 :size="15" />{{ t("章节分析") }}</button>
          <span>{{ store.activeChapter ? t("来源：{chapter}", { chapter: store.chapterMeta.chapterNo }) : t("等待章节") }}</span>
        </nav>
        <WorkspaceEditor v-if="workbenchMode === 'writing'" expanded @request-immersive="enterImmersive" />
        <ContextAssistantPanel v-else-if="workbenchMode === 'assistant'" />
        <ChapterTemporalPanel v-else-if="workbenchMode === 'temporal'" />
        <MediaWorkbenchPanel v-else />
      </main>
      <ChapterReviewPanel v-if="workbenchMode === 'writing'" class="workbench-review" />
    </div>

    <section class="recent-tasks">
      <header><span><Clock3 :size="15" /><strong>{{ t("最近章节任务") }}</strong></span><button type="button" @click="store.loadChapters()">{{ t("刷新记录") }}</button></header>
      <div v-if="store.chapters.length" class="task-row">
        <button v-for="chapter in [...store.chapters].reverse().slice(0, 5)" :key="chapter.chapter_id" type="button" @click="store.openChapter(chapter.chapter_id)">
          <strong>{{ chapter.title }}</strong><span>{{ t("{count} 字", { count: formatNumber(chapter.word_count) }) }}</span><span>{{ t(chapter.analysis_status === "completed" ? "已分析" : "正文草稿") }}</span><small>{{ chapter.updated_at || "" }}</small>
        </button>
      </div>
      <div v-else class="task-empty">{{ t("创建章节后，这里会显示真实任务记录。") }}</div>
    </section>

    <div v-if="store.actionMessage" class="workbench-toast">{{ store.actionMessage }}</div>
  </div>
</template>

<style scoped>
.workspace-page { min-height: 100%; width: min(100%, 1760px); margin: 0 auto; padding: 18px; }
.workspace-context-bar { min-height: 54px; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.92); box-shadow: var(--soft-shadow); padding: 7px 10px; }
.context-breadcrumbs { min-width: 0; display: flex; align-items: center; gap: 4px; }
.context-breadcrumbs > div { min-width: 0; display: grid; grid-template-columns: auto minmax(0,auto); align-items: center; gap: 7px; padding: 6px 10px; }
.context-breadcrumbs > div + div { border-left: 1px solid var(--border); }
.context-breadcrumbs small { border-radius: 5px; background: var(--accent-soft); color: var(--accent); padding: 3px 5px; font-size: 9px; }
.context-breadcrumbs strong { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.context-actions { flex: 0 0 auto; display: flex; gap: 6px; }
.context-actions button { min-height: 32px; display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; padding: 6px 9px; font-size: 10px; }
.context-actions button:hover, .context-actions button.active { border-color: #cec4fb; color: var(--accent); background: var(--accent-soft); }
.context-actions button:disabled { color: var(--text-muted); cursor: not-allowed; background: #f7f7f9; }
.world-required { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 13px; margin-bottom: 14px; border: 1px solid #e8cfaa; border-radius: 8px; background: #fff9ef; color: #9a5b18; padding: 12px 14px; }
.world-required p { margin-top: 3px; color: #8a755e; font-size: 10px; }
.world-required button { min-height: 30px; border: 0; border-radius: 7px; background: #fff; color: #8a5a22; cursor: pointer; padding: 5px 10px; font-size: 10px; }
.creation-workbench { display: grid; grid-template-columns: 220px minmax(620px,1fr) 310px; gap: 12px; align-items: start; }
.creation-workbench.wide-mode { grid-template-columns: 220px minmax(0,1fr); }
.workbench-main { min-width: 0; display: grid; gap: 8px; }
.mode-tabs { min-height: 44px; display: flex; align-items: stretch; gap: 3px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.92); padding: 5px; }
.mode-tabs button { min-width: 104px; display: inline-flex; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 6px; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 10px; }
.mode-tabs button.active { background: var(--accent); color: #fff; }
.mode-tabs button:disabled { color: var(--text-muted); cursor: not-allowed; }
.mode-tabs > span { min-width: 0; margin-left: auto; align-self: center; overflow: hidden; color: var(--text-muted); padding: 0 8px; text-overflow: ellipsis; white-space: nowrap; font-size: 9px; }
.recent-tasks { margin-top: 12px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.9); }
.recent-tasks > header { min-height: 42px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 0 12px; }
.recent-tasks > header span { display: flex; align-items: center; gap: 6px; }
.recent-tasks > header strong { font-size: 12px; }
.recent-tasks > header button { border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: 10px; }
.task-row { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 1px; background: var(--border); }
.task-row button { min-width: 0; display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 3px 7px; border: 0; background: #fff; cursor: pointer; padding: 9px 11px; text-align: left; }
.task-row button:hover { background: #fbfaff; }
.task-row strong, .task-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-row strong { font-size: 10px; }
.task-row span, .task-row small { color: var(--text-muted); font-size: 9px; }
.task-row small { grid-column: 1 / -1; }
.task-empty { min-height: 58px; display: grid; place-items: center; color: var(--text-muted); font-size: 10px; }
.workbench-toast, .focus-toast { position: fixed; z-index: 70; left: 50%; bottom: 22px; transform: translateX(-50%); border-radius: 999px; background: #242139; color: #fff; box-shadow: var(--soft-shadow); padding: 8px 14px; font-size: 12px; }
.immersive-page { height: 100%; min-height: 0; display: grid; grid-template-rows: 58px minmax(0,1fr); background: #fff; }
.focus-topbar { display: grid; grid-template-columns: minmax(190px,.8fr) minmax(280px,1.2fr) auto; align-items: center; gap: 18px; border-bottom: 1px solid var(--border); padding: 0 16px; }
.world-context { min-width: 0; display: flex; align-items: center; gap: 8px; border: 0; background: transparent; cursor: pointer; text-align: left; }
.world-context > span { width: 30px; height: 30px; display: grid; place-items: center; border-radius: 50%; background: #29253b; color: #fff; }
.world-context strong, .chapter-context strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.chapter-context { min-width: 0; display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 9px; }
.chapter-context small, .focus-status { color: var(--text-muted); font-size: 11px; }
.focus-status { display: flex; align-items: center; gap: 14px; white-space: nowrap; }
.focus-status span { display: flex; align-items: center; gap: 6px; }
.focus-status i { width: 7px; height: 7px; border-radius: 50%; background: #32c48d; }
.focus-status i.dirty { background: #d6a34a; }
.focus-body { position: relative; min-height: 0; display: flex; }
.focus-editor { min-width: 0; flex: 1; padding: 10px; background: #fafbfc; }
@media (max-width: 1480px) { .creation-workbench { grid-template-columns: 210px minmax(0,1fr); } .workbench-review { grid-column: 2; } }
@media (max-width: 1120px) { .workspace-context-bar { align-items: stretch; flex-direction: column; } .context-actions { justify-content: flex-end; } .task-row { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 860px) { .creation-workbench, .creation-workbench.wide-mode { grid-template-columns: 1fr; } .creation-workbench.wide-mode .workbench-navigation { display: none; } .workbench-review { grid-column: auto; } .context-breadcrumbs { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); } .context-breadcrumbs > div { align-items: start; } .context-breadcrumbs > div + div { border-left: 0; } .context-breadcrumbs strong { max-width: none; overflow: visible; overflow-wrap: anywhere; white-space: normal; line-height: 1.25; } .task-row { grid-template-columns: 1fr; } }
@media (max-width: 820px) { .focus-topbar { grid-template-columns: minmax(0,1fr) auto; } .chapter-context { display: none; } .focus-editor { padding: 0; } }
@media (max-width: 680px) { .workspace-page { padding: 10px; } .world-required { grid-template-columns: auto minmax(0,1fr); } .world-required button { grid-column: 1 / -1; } .context-actions { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); } .context-actions button { justify-content: center; padding-inline: 5px; } .focus-status span:first-child { display: none; } }
</style>
