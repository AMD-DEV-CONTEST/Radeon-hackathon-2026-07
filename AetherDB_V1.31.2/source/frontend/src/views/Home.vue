<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ArrowRight, BookOpen, Maximize2, PenLine, Upload } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";
import AiAssistantPanel from "../components/AiAssistantPanel.vue";
import QuickCreateGrid from "../components/QuickCreateGrid.vue";
import RecentDocumentsPanel from "../components/RecentDocumentsPanel.vue";
import RecentWorldsStrip from "../components/RecentWorldsStrip.vue";
import WorldOverviewPanel from "../components/WorldOverviewPanel.vue";
import CreateWorldDialog from "../components/CreateWorldDialog.vue";
import heroImage from "../assets/workspace-mountains.png";

const store = useAppStore();
const router = useRouter();
const { locale, t } = useI18n();
const createDialogKind = ref("");

const greeting = computed(() => {
  const hour = new Date().getHours();
  if (hour < 11) return t("早安");
  if (hour < 18) return t("午安");
  return t("晚上好");
});

function formatNumber(value) {
  return Number(value || 0).toLocaleString(locale.value);
}

onMounted(() => {
  store.fetchDashboard();
});

function enterImmersive() {
  if (store.requestImmersiveWriting()) {
    router.push({ path: "/workspace", query: { mode: "immersive" } });
  }
}

function enterWorkspace() {
  router.push("/workspace");
}
</script>

<template>
  <div class="home-shell">
    <div class="hero-backdrop" :style="{ backgroundImage: `url(${heroImage})` }"></div>

    <header class="topbar">
      <div>
        <h1>{{ t("{greeting}，Worldbuilder", { greeting }) }}</h1>
        <p>{{ t("首页是作者模式的创作入口。先写正文，再分析设定变更，确认后才入库。") }}</p>
      </div>
      <div class="window-actions">
        <span class="ai-state" :class="{ ready: store.aiConfigured }">{{ t(store.aiConfigured ? "AI 已配置" : "AI 未配置") }}</span>
        <button type="button">? {{ t("帮助") }}</button>
        <span>−</span>
        <span>□</span>
        <span>×</span>
      </div>
    </header>

    <div class="dashboard-grid">
      <main class="workspace-column">
        <section class="creation-entry">
          <div class="creation-entry-heading">
            <span class="creation-mark"><PenLine :size="22" /></span>
            <div>
              <small>{{ t("继续创作") }}</small>
              <h2>{{ store.activeChapter ? store.chapterTitle : t(store.activeBook ? "创建第一章" : "先选择一个作品") }}</h2>
              <p>{{ store.activeBook ? t("{world} · {volume} · {chapter}", { world: store.currentWorldName, volume: store.chapterMeta.volume, chapter: store.chapterMeta.chapterNo }) : t("创作工作台会保存章节正文、版本和分析预览。") }}</p>
            </div>
          </div>
          <div class="creation-metrics">
            <div><small>{{ t("章节字数") }}</small><strong>{{ formatNumber(store.todayWords) }}</strong></div>
            <div><small>{{ t("保存状态") }}</small><strong>{{ store.chapterDirty ? t("待保存") : store.lastSavedAt || t("暂无记录") }}</strong></div>
            <div><small>{{ t("章节数量") }}</small><strong>{{ formatNumber(store.chapters.length) }}</strong></div>
          </div>
          <div class="creation-actions">
            <button class="secondary" type="button" @click="enterWorkspace"><ArrowRight :size="16" />{{ t("进入创作工作台") }}</button>
            <button type="button" :disabled="!store.canEnterImmersive" @click="enterImmersive"><Maximize2 :size="16" />{{ t("沉浸写作") }}</button>
          </div>
        </section>

        <section class="import-entry">
          <div class="import-entry-icon"><Upload :size="20" /></div>
          <div><strong>{{ t("已有章节、设定或整本作品？") }}</strong><span>{{ t("创建持久化导入任务，逐项预览并确认后再写入当前世界。") }}</span></div>
          <button type="button" @click="$router.push({ path: '/import', query: { source: 'full_book', from: 'home' } })"><BookOpen :size="16" />{{ t("批量导入") }}</button>
        </section>

        <div v-if="store.actionMessage" class="action-toast">
          {{ store.actionMessage }}
        </div>

        <section class="lower-workspace-zone" :aria-label="t('快速创建与最近访问')">
          <QuickCreateGrid />
          <RecentWorldsStrip :worlds="store.recentWorlds" @create-group="createDialogKind = 'group'" @create-world="createDialogKind = 'world'" />
        </section>
      </main>

      <aside class="right-rail">
        <div class="mini-stats">
          <div class="mini-stat">
            <small>{{ t("今日创作") }}</small>
            <strong>{{ store.writingActivity.todayWords === null ? t("暂无统计") : t("{count} 字", { count: formatNumber(store.writingActivity.todayWords) }) }}</strong>
          </div>
          <div class="mini-stat">
            <small>{{ t("连续创作") }}</small>
            <strong>{{ store.writingActivity.streakDays === null ? t("暂无统计") : t("{count} 天", { count: formatNumber(store.writingActivity.streakDays) }) }}</strong>
          </div>
        </div>

        <AiAssistantPanel />
        <div v-if="!store.aiConfigured" class="setup-card">
          <strong>{{ t("首次启动向导") }}</strong>
          <span>{{ t("三步完成：选择 AI 模式、配置模型、选择使用风格。也可以先跳过。") }}</span>
          <button type="button" @click="$router.push('/settings')">{{ t("打开 AI 设置") }}</button>
        </div>
        <WorldOverviewPanel :stats="store.overviewStats" />
        <RecentDocumentsPanel :documents="store.recentDocuments" />

      </aside>
    </div>

    <CreateWorldDialog v-if="createDialogKind" :kind="createDialogKind" @close="createDialogKind = ''" />
  </div>
</template>

<style scoped>
.home-shell {
  position: relative;
  min-height: 100vh;
  padding: 38px 28px 28px;
  overflow: hidden;
}

.hero-backdrop {
  position: absolute;
  inset: 0 0 auto 0;
  height: 220px;
  background-size: cover;
  background-position: center top;
  opacity: 0.52;
  pointer-events: none;
}

.hero-backdrop::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(245,246,251,0.2) 0%, rgba(245,246,251,0.78) 64%, #f5f6fb 100%);
}

.topbar,
.dashboard-grid {
  position: relative;
  z-index: 1;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 28px;
  padding: 0 6px;
}

.topbar h1 {
  font-size: 25px;
  line-height: 1.25;
  margin-bottom: 8px;
}

.topbar p {
  color: var(--text-secondary);
  font-size: 13px;
}

.window-actions {
  display: flex;
  align-items: center;
  gap: 18px;
  color: #4c485f;
  font-size: 13px;
}

.ai-state {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #fff7ed;
  color: #9a5b18;
  font-size: 12px;
}

.ai-state.ready {
  background: #edfdf6;
  color: #117250;
}

.window-actions button {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(620px, 1fr) 340px;
  gap: 18px;
  align-items: start;
  width: min(100%, 1720px);
  margin: 0 auto;
}

.workspace-column,
.right-rail {
  display: grid;
  gap: 18px;
}

.creation-entry {
  min-height: 230px;
  display: grid;
  grid-template-columns: minmax(0,1fr) auto;
  grid-template-rows: 1fr auto;
  gap: 18px 24px;
  align-items: center;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,.93);
  box-shadow: var(--card-shadow);
  padding: 26px;
}

.creation-entry-heading { min-width: 0; display: flex; align-items: center; gap: 16px; }
.creation-mark { width: 52px; height: 52px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: var(--accent-soft); color: var(--accent); }
.creation-entry-heading > div { min-width: 0; display: grid; gap: 5px; }
.creation-entry-heading small { color: var(--accent); font-size: 11px; }
.creation-entry-heading h2, .creation-entry-heading p { overflow-wrap: anywhere; }
.creation-entry-heading h2 { font-size: 24px; }
.creation-entry-heading p { color: var(--text-secondary); font-size: 12px; line-height: 1.45; }
.creation-metrics { display: grid; grid-template-columns: repeat(3,minmax(92px,1fr)); gap: 1px; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; background: var(--border); }
.creation-metrics > div { display: grid; gap: 5px; background: #fff; padding: 12px; }
.creation-metrics small { color: var(--text-muted); font-size: 10px; }
.creation-metrics strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.creation-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; gap: 8px; border-top: 1px solid var(--border); padding-top: 16px; }
.creation-actions button { min-height: 36px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 7px; background: var(--accent); color: #fff; cursor: pointer; padding: 7px 13px; font-size: 11px; }
.creation-actions button.secondary { border: 1px solid var(--border); background: #fff; color: var(--accent); }
.creation-actions button:disabled { background: #aaa5ba; cursor: not-allowed; }

.right-rail {
  min-width: 0;
}

.lower-workspace-zone {
  display: grid;
  gap: 18px;
  min-height: 35vh;
  align-content: start;
}

.mini-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.mini-stat {
  min-height: 58px;
  display: grid;
  align-content: center;
  gap: 4px;
  padding: 10px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.88);
  box-shadow: var(--soft-shadow);
}

.mini-stat small {
  color: var(--text-muted);
  font-size: 11px;
}

.mini-stat strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 18px;
}

.action-toast {
  justify-self: center;
  margin-top: -6px;
  padding: 8px 14px;
  border-radius: 999px;
  background: #242139;
  color: #fff;
  box-shadow: var(--soft-shadow);
  font-size: 12px;
}

.import-entry {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 11px;
  align-items: center;
  margin-top: -8px;
  border: 1px solid #dfd9f7;
  border-radius: 8px;
  background: rgba(251,250,255,0.92);
  padding: 10px 12px;
}

.import-entry-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
}

.import-entry > div:nth-child(2) {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.import-entry strong {
  font-size: 12px;
}

.import-entry span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: 11px;
}

.import-entry button {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  border-radius: 7px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  padding: 6px 11px;
  font-size: 12px;
}

.setup-card {
  display: grid;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255,255,255,0.9);
  box-shadow: var(--soft-shadow);
  padding: 14px;
}

.setup-card strong {
  font-size: 15px;
}

.setup-card span {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.setup-card button {
  justify-self: start;
  min-height: 32px;
  border: 0;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  padding: 6px 12px;
}

@media (max-width: 1180px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .right-rail {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mini-stats {
    grid-column: 1 / -1;
  }
}

@media (max-height: 760px) {
  .home-shell {
    padding-top: 24px;
  }

  .topbar {
    margin-bottom: 18px;
  }

  .lower-workspace-zone {
    min-height: 250px;
  }
}

@media (max-width: 760px) {
  .home-shell {
    padding: 24px 16px;
  }

  .topbar,
  .window-actions {
    flex-wrap: wrap;
  }

  .dashboard-grid,
  .right-rail {
    grid-template-columns: 1fr;
  }

  .creation-entry { grid-template-columns: 1fr; }
  .creation-metrics { grid-row: auto; }
  .creation-actions { grid-column: auto; }

  .import-entry {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .creation-entry { min-height: 0; padding: 18px; }
  .creation-entry-heading { align-items: flex-start; }
  .creation-entry-heading h2, .creation-entry-heading p { white-space: normal; }
  .creation-metrics { grid-template-columns: 1fr; }
  .creation-actions { display: grid; }

  .import-entry button {
    grid-column: 1 / -1;
    justify-content: center;
  }

  .import-entry span {
    overflow: visible;
    white-space: normal;
    line-height: 1.4;
  }

  .window-actions > span:not(.ai-state) {
    display: none;
  }
}
</style>
