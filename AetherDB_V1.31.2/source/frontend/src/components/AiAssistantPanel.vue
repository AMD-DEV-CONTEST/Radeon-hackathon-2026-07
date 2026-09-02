<script setup>
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { Bell, Bot, FileDiff, ScanText, ShieldAlert } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";

const router = useRouter();
const { t } = useI18n();
const store = useAppStore();
const tasks = [
  { label: "分析本章", icon: ScanText, action: () => store.createDraftChangeSet() },
  { label: "设定提醒", icon: Bell, action: () => store.notifyAction(t("设定提醒会基于当前章节与世界资料生成")) },
  { label: "冲突检查", icon: ShieldAlert, action: () => store.notifyAction(t("冲突检查结果需要确认后才会写入")) },
  { label: "生成变更预览", icon: FileDiff, action: () => store.createDraftChangeSet() },
];
</script>

<template>
  <section class="panel ai-panel">
    <header class="panel-header">
      <h2>{{ t("AI 创作辅助") }}</h2>
      <button type="button" @click="router.push('/settings')">{{ t("设置") }} ›</button>
    </header>

    <div class="ai-status-mark" :class="{ disabled: !store.aiConfigured }">
      <Bot :size="24" />
      <span>{{ store.aiConfigured ? t("AI 已配置") : t("AI 未配置") }}</span>
    </div>
    <p class="prompt">
      {{ store.aiConfigured ? t("当前风格：{profile}", { profile: t(store.aiSetup.profile || "通用") }) : t("AI 未配置：可以继续写作，分析功能会以预览入口降级显示。") }}
    </p>

    <div class="task-grid">
      <button v-for="task in tasks" :key="task.label" type="button" @click="task.action">
        <component :is="task.icon" :size="15" />
        <span>{{ t(task.label) }}</span>
      </button>
    </div>

    <div class="profile-row">
      <span>Prompt Profile</span>
      <strong>{{ t(store.aiSetup.profile || "通用") }}</strong>
    </div>
    <div class="safety-note">
      {{ t("AI 建议不会自动修改正文或写入设定库，所有变更都需要你确认。") }}
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
}

.panel-header h2 {
  font-size: 16px;
}

.panel-header button {
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
}

.ai-status-mark { min-height: 52px; display: flex; align-items: center; justify-content: center; gap: 9px; margin: 14px 0 8px; border: 1px solid #d9d2fb; border-radius: 8px; background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 700; }
.ai-status-mark.disabled { border-color: var(--border); background: var(--bg-secondary); color: var(--text-muted); }

.prompt {
  margin-bottom: 14px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px solid var(--border);
  border-left: 1px solid var(--border);
}

.task-grid button {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 8px;
  border: 0;
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}

.task-grid button:hover {
  color: var(--accent);
  background: #fbfaff;
}

.profile-row,
.safety-note {
  margin-top: 12px;
  border-radius: 8px;
  background: var(--bg-secondary);
  padding: 10px;
  font-size: 12px;
}

.profile-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: var(--text-secondary);
}

.profile-row strong {
  color: var(--accent);
}

.safety-note {
  color: var(--text-secondary);
  line-height: 1.6;
}
</style>
