<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { BookOpen, CheckCircle2, FileClock, Image, Mic2, PenLine, Plus, Sparkles } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();

const runtimeLabel = computed(() => {
  if (store.backendAvailable === false) return t("服务未连接");
  if (!store.aiConfigured) return t("正文服务可用");
  return t("创作服务就绪");
});

function createChapter() {
  store.createChapterDraft(t("第 {number} 章", { number: store.chapters.length + 1 }));
}
</script>

<template>
  <aside class="workspace-navigator">
    <section class="workflow-section">
      <header><strong>{{ t("工作流") }}</strong></header>
      <button class="workflow-item active" type="button">
        <PenLine :size="18" /><span><strong>{{ t("文本创作") }}</strong><small>{{ t("章节正文与自动保存") }}</small></span>
      </button>
      <button class="workflow-item" type="button" :disabled="!store.activeChapter" @click="store.createDraftChangeSet()">
        <Sparkles :size="18" /><span><strong>{{ t("章节分析") }}</strong><small>{{ t("提取设定并生成预览") }}</small></span>
      </button>
      <button class="workflow-item" type="button" disabled>
        <Image :size="18" /><span><strong>{{ t("视觉创作") }}</strong><small>{{ t("图像引擎未连接") }}</small></span>
      </button>
      <button class="workflow-item" type="button" disabled>
        <Mic2 :size="18" /><span><strong>{{ t("语音创作") }}</strong><small>{{ t("语音引擎未连接") }}</small></span>
      </button>
    </section>

    <section class="chapter-section">
      <header>
        <span><BookOpen :size="15" /><strong>{{ t("章节") }}</strong></span>
        <button type="button" :title="t('新建章节')" :disabled="!store.activeBook" @click="createChapter"><Plus :size="16" /></button>
      </header>
      <div v-if="store.chapterLoading" class="chapter-empty">{{ t("正在读取章节") }}</div>
      <div v-else-if="!store.chapters.length" class="chapter-empty">
        <span>{{ t("当前作品还没有章节") }}</span>
        <button type="button" :disabled="!store.activeBook" @click="createChapter">{{ t("创建第一章") }}</button>
      </div>
      <div v-else class="chapter-list">
        <button
          v-for="chapter in store.chapters"
          :key="chapter.chapter_id"
          type="button"
          :class="{ active: chapter.chapter_id === store.activeChapter?.chapter_id || store.isChapterGroupActive(chapter) }"
          @click="store.openChapter(chapter.chapter_id)"
        >
          <span>{{ chapter.chapter_index || "-" }}</span>
          <span><strong>{{ chapter.title }}</strong><small>{{ t("{count} 字", { count: chapter.word_count || 0 }) }} · {{ chapter.status || "draft" }}</small></span>
        </button>
      </div>
    </section>

    <section class="runtime-section">
      <header><span><FileClock :size="15" /><strong>{{ t("运行环境") }}</strong></span><i :class="{ online: store.backendAvailable }"></i></header>
      <dl>
        <div><dt>{{ t("本地服务") }}</dt><dd>{{ runtimeLabel }}</dd></div>
        <div><dt>{{ t("AI 分析") }}</dt><dd>{{ t(store.aiConfigured ? "已配置" : "本地规则") }}</dd></div>
        <div><dt>{{ t("自动保存") }}</dt><dd><CheckCircle2 :size="13" />{{ t("已启用") }}</dd></div>
      </dl>
    </section>
  </aside>
</template>

<style scoped>
.workspace-navigator { min-width: 0; display: grid; align-content: start; gap: 12px; }
.workflow-section, .chapter-section, .runtime-section { border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.92); box-shadow: var(--soft-shadow); overflow: hidden; }
section > header { min-height: 42px; display: flex; align-items: center; justify-content: space-between; gap: 8px; border-bottom: 1px solid var(--border); padding: 0 12px; }
section > header > span { display: flex; align-items: center; gap: 7px; }
section > header strong { font-size: 13px; }
section > header button { width: 28px; height: 28px; display: grid; place-items: center; border: 0; border-radius: 6px; background: transparent; color: var(--accent); cursor: pointer; }
section > header button:hover { background: var(--accent-soft); }
section > header button:disabled { color: var(--text-muted); cursor: not-allowed; }
.workflow-section { padding-bottom: 8px; }
.workflow-section > header { margin-bottom: 8px; }
.workflow-item { width: calc(100% - 16px); min-height: 64px; display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 10px; margin: 0 8px 5px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--text-secondary); cursor: pointer; padding: 8px 10px; text-align: left; }
.workflow-item > span { min-width: 0; display: grid; gap: 3px; }
.workflow-item strong, .workflow-item small { overflow-wrap: anywhere; line-height: 1.3; }
.workflow-item strong { color: var(--text-primary); font-size: 12px; }
.workflow-item small { color: var(--text-muted); font-size: 10px; }
.workflow-item.active { border-color: #d8d0fb; background: var(--accent-soft); color: var(--accent); }
.workflow-item:disabled { opacity: .58; cursor: not-allowed; }
.chapter-list { max-height: min(34vh, 330px); overflow: auto; padding: 7px; }
.chapter-list > button { width: 100%; min-width: 0; display: grid; grid-template-columns: 28px minmax(0,1fr); align-items: center; gap: 8px; border: 0; border-radius: 7px; background: transparent; cursor: pointer; padding: 7px; text-align: left; }
.chapter-list > button:hover, .chapter-list > button.active { background: var(--accent-soft); }
.chapter-list > button > span:first-child { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 6px; background: var(--bg-secondary); color: var(--text-secondary); font-size: 10px; }
.chapter-list > button > span:last-child { min-width: 0; display: grid; gap: 2px; }
.chapter-list strong, .chapter-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chapter-list strong { font-size: 11px; }
.chapter-list small { color: var(--text-muted); font-size: 9px; }
.chapter-empty { min-height: 92px; display: grid; place-items: center; gap: 7px; color: var(--text-muted); padding: 12px; text-align: center; font-size: 10px; }
.chapter-empty button { min-height: 28px; border: 1px solid var(--border); border-radius: 6px; background: #fff; color: var(--accent); cursor: pointer; padding: 4px 9px; }
.runtime-section header i { width: 7px; height: 7px; border-radius: 50%; background: #c2becd; }
.runtime-section header i.online { background: #32c48d; }
.runtime-section dl { display: grid; gap: 8px; padding: 11px 12px; }
.runtime-section dl > div { display: flex; justify-content: space-between; gap: 10px; font-size: 10px; }
.runtime-section dt { color: var(--text-muted); }
.runtime-section dd { display: flex; align-items: center; gap: 4px; color: var(--text-secondary); text-align: right; }
</style>
