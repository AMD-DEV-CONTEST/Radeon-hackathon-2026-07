<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import { useI18n } from "vue-i18n";
import { AlertTriangle, CheckCircle2, ChevronRight, GripVertical, PanelRightClose, PanelRightOpen, RotateCcw, Settings2, Sparkles } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";

const store = useAppStore();
const { t } = useI18n();
const activeTab = ref("analysis");
const collapsed = ref(false);
const panelWidth = ref(Math.min(440, Math.max(260, Number(localStorage.getItem("aetherdb_immersive_ai_width")) || 300)));
let resizing = false;
const relatedItems = computed(() => store.recentDocuments.slice(0, 3));
const analysisMessage = computed(() => {
  if (!store.aiConfigured) return t("AI 尚未配置，正文仍可正常保存；分析功能暂不执行。");
  if (store.pendingChangeSet) return store.pendingChangeSet.summary;
  return t("分析本章后，这里会显示与当前世界相关的实体、设定建议和冲突结果。");
});

function resizePanel(event) {
  if (!resizing) return;
  panelWidth.value = Math.min(440, Math.max(260, window.innerWidth - event.clientX));
}

function stopResize() {
  if (!resizing) return;
  resizing = false;
  localStorage.setItem("aetherdb_immersive_ai_width", String(panelWidth.value));
  window.removeEventListener("pointermove", resizePanel);
  window.removeEventListener("pointerup", stopResize);
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
}

function startResize(event) {
  if (collapsed.value) return;
  resizing = true;
  event.currentTarget.setPointerCapture?.(event.pointerId);
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
  window.addEventListener("pointermove", resizePanel);
  window.addEventListener("pointerup", stopResize, { once: true });
}

function resetPanelWidth() {
  panelWidth.value = 300;
  localStorage.setItem("aetherdb_immersive_ai_width", "300");
}

onBeforeUnmount(stopResize);
</script>

<template>
  <aside class="assistant-rail" :class="{ collapsed }" :style="{ '--assistant-width': `${panelWidth}px` }">
    <button v-if="collapsed" class="rail-reopen" type="button" :title="t('展开 AI 创作辅助')" @click="collapsed = false"><PanelRightOpen :size="19" /></button>
    <template v-else>
      <button class="resize-handle" type="button" :title="t('拖动调整面板宽度')" :aria-label="t('拖动调整面板宽度')" @pointerdown="startResize"><GripVertical :size="15" /></button>
      <header class="rail-header">
        <div class="rail-tabs">
          <button type="button" :class="{ active: activeTab === 'settings' }" @click="activeTab = 'settings'">{{ t("设定") }}</button>
          <button type="button" :class="{ active: activeTab === 'analysis' }" @click="activeTab = 'analysis'">{{ t("AI 分析") }}</button>
        </div>
        <div class="rail-actions"><button type="button" :title="t('恢复默认宽度')" @click="resetPanelWidth"><RotateCcw :size="15" /></button><button type="button" :title="t('收起为窄栏')" @click="collapsed = true"><PanelRightClose :size="17" /></button></div>
      </header>

      <div v-if="activeTab === 'analysis'" class="rail-content">
        <section class="rail-section">
          <header><strong>{{ t("相关资料") }}</strong><span>{{ t("{count} 项内容", { count: relatedItems.length }) }}</span></header>
          <div v-if="relatedItems.length" class="related-list">
            <button v-for="item in relatedItems" :key="item.id || item.title" type="button" @click="store.notifyAction(t('查看相关资料：{title}', { title: item.title }))">
              <span class="related-mark">{{ item.title.slice(0, 1) }}</span>
              <span><strong>{{ item.title }}</strong><small>{{ item.type ? t(item.type) : t("世界资料") }}</small></span>
            </button>
          </div>
          <div v-else class="rail-empty">{{ t("当前世界暂无相关资料") }}</div>
        </section>

        <section class="rail-section suggestion">
          <header><strong><Sparkles :size="15" />{{ t("写作建议") }}</strong></header>
          <p>{{ analysisMessage }}</p>
          <button type="button" :disabled="!store.aiConfigured" @click="store.createDraftChangeSet()">{{ t("分析当前章节") }}</button>
        </section>

        <section class="rail-section conflict">
          <header><strong><CheckCircle2 v-if="!store.pendingChangeSet?.warnings?.length" :size="15" /><AlertTriangle v-else :size="15" />{{ t("冲突检查") }}</strong><span>{{ store.pendingChangeSet?.warnings?.length ? t("{count} 项待确认", { count: store.pendingChangeSet.warnings.length }) : t("暂无结果") }}</span></header>
          <p>{{ t("分析结果只生成预览，确认前不会修改世界设定。") }}</p>
        </section>

        <button class="rail-link" type="button" @click="store.notifyAction(t('设定快速跳转已打开'))">{{ t("设定快速跳转") }}<ChevronRight :size="16" /></button>
      </div>

      <div v-else class="rail-content">
        <section class="rail-section settings-state">
          <Settings2 :size="22" />
          <strong>{{ store.currentWorldName }}</strong>
          <p>{{ t("创作内容将关联到当前世界。正文保存和设定变更仍保持独立。") }}</p>
        </section>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.assistant-rail { position: relative; width: var(--assistant-width); flex: 0 0 var(--assistant-width); min-width: 0; height: 100%; overflow: auto; border-left: 1px solid var(--border); background: rgba(255,255,255,.94); }
.assistant-rail.collapsed { width: 48px; flex-basis: 48px; overflow: hidden; display: grid; justify-items: center; align-content: start; padding-top: 11px; background: rgba(255,255,255,.88); }
.rail-reopen { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--accent); cursor: pointer; }
.resize-handle { position: absolute; z-index: 2; inset: 50% auto auto 1px; width: 18px; height: 42px; display: grid; place-items: center; transform: translateY(-50%); border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-muted); cursor: col-resize; box-shadow: var(--soft-shadow); }
.rail-actions button { width: 32px; height: 32px; display: grid; place-items: center; border: 0; border-radius: 7px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.rail-reopen:hover, .rail-actions button:hover { background: var(--accent-soft); color: var(--accent); }
.rail-header { height: 52px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding: 0 12px; }
.rail-tabs { display: flex; align-self: stretch; gap: 14px; }
.rail-tabs button { position: relative; border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 12px; }
.rail-tabs button.active { color: var(--accent); font-weight: 700; }
.rail-tabs button.active::after { content: ""; position: absolute; inset: auto 0 0; height: 2px; background: var(--accent); }
.rail-actions { display: flex; gap: 2px; }
.rail-content { display: grid; align-content: start; }
.rail-section { display: grid; gap: 10px; padding: 16px; border-bottom: 1px solid var(--border); }
.rail-section header { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
.rail-section header strong { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.rail-section header span, .rail-section p { color: var(--text-secondary); font-size: 11px; line-height: 1.65; }
.related-list { display: grid; gap: 5px; }
.related-list button { min-width: 0; display: grid; grid-template-columns: auto minmax(0,1fr); align-items: center; gap: 9px; border: 0; border-radius: 7px; background: transparent; cursor: pointer; text-align: left; padding: 7px; }
.related-list button:hover { background: var(--bg-secondary); }
.related-mark { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-weight: 700; }
.related-list button > span:last-child { min-width: 0; display: grid; gap: 2px; }
.related-list strong, .related-list small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.related-list strong { font-size: 12px; }
.related-list small, .rail-empty { color: var(--text-muted); font-size: 10px; }
.rail-empty { min-height: 70px; display: grid; place-items: center; border: 1px dashed var(--border); border-radius: 7px; }
.suggestion { background: #fbfaff; }
.suggestion > button { min-height: 32px; border: 1px solid #dcd5fb; border-radius: 7px; background: #fff; color: var(--accent); cursor: pointer; }
.suggestion > button:disabled { color: var(--text-muted); cursor: not-allowed; }
.rail-link { min-height: 44px; display: flex; justify-content: space-between; align-items: center; border: 0; border-bottom: 1px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer; padding: 0 16px; font-size: 12px; }
.settings-state { place-items: center; text-align: center; padding-top: 34px; }
@media (max-width: 1050px) { .assistant-rail { --assistant-width: 260px; } }
@media (max-width: 820px) {
  .assistant-rail { position: absolute; z-index: 8; inset: 0 0 0 auto; width: min(var(--assistant-width),85vw); box-shadow: -12px 0 30px rgba(72,62,115,.12); }
  .assistant-rail.collapsed { position: relative; inset: auto; width: 48px; height: 100%; box-shadow: none; }
}
</style>
