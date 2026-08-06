<script setup>
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { Box, Brain, CalendarDays, Flag, MapPin, Scale, Settings2, UserRound } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";
import QuickCreateDialog from "./QuickCreateDialog.vue";

const store = useAppStore();
const { t } = useI18n();
const activeType = ref(null);

const types = [
  { key: "character", icon: UserRound, label: "创建角色", desc: "身份、经历与性格" },
  { key: "faction", icon: Flag, label: "创建势力", desc: "组织目标与历史" },
  { key: "location", icon: MapPin, label: "创建地点", desc: "区域、环境与特征" },
  { key: "event", icon: CalendarDays, label: "创建事件", desc: "时间、起因与结果" },
  { key: "item", icon: Box, label: "创建物品", desc: "来源、能力与归属" },
  { key: "concept", icon: Brain, label: "创建概念", desc: "定义、类别与影响" },
  { key: "rule", icon: Scale, label: "创建规则", desc: "条件、效果与例外" },
  { key: "system", icon: Settings2, label: "创建系统", desc: "组成、机制与限制" },
];

function openCreate(type) {
  if (!store.activeDatabase?.database_id) {
    store.notifyAction(t("请先在“最近访问的世界”中选择一个分组或世界"));
    return;
  }
  activeType.value = type;
}
</script>

<template>
  <section class="quick-section">
    <div class="section-heading"><span>✧</span><h2>{{ t("快速创建") }}</h2><small>{{ store.activeDatabase ? t("写入：{name}", { name: store.activeDatabase.name || store.activeDatabase.title || store.activeDatabase.database_id }) : t("请先选择目标分组") }}</small></div>
    <div class="quick-create">
      <button v-for="type in types" :key="type.key" class="quick-btn" type="button" @click="openCreate(type)">
        <span class="quick-icon"><component :is="type.icon" :size="23" /></span>
        <span class="quick-copy"><strong>{{ t(type.label) }}</strong><small>{{ t(type.desc) }}</small></span>
      </button>
    </div>
    <QuickCreateDialog v-if="activeType" :entity-type="activeType" @close="activeType = null" />
  </section>
</template>

<style scoped>
.quick-section { display: grid; gap: 12px; }
.section-heading { display: flex; align-items: center; gap: 8px; }
.section-heading h2 { font-size: 16px; font-weight: 700; }
.section-heading > span { color: var(--accent); }
.section-heading small { margin-left: auto; max-width: 48%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 10px; }
.quick-create { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; background: rgba(255,255,255,.88); box-shadow: var(--soft-shadow); }
.quick-btn { min-height: 88px; display: flex; align-items: center; gap: 10px; padding: 12px; border: 0; border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); background: transparent; cursor: pointer; text-align: left; }
.quick-btn:nth-child(4n) { border-right: 0; }
.quick-btn:nth-last-child(-n + 4) { border-bottom: 0; }
.quick-btn:hover { background: #fbfaff; }
.quick-icon { width: 38px; height: 38px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: var(--accent-soft); color: var(--accent); }
.quick-copy { display: grid; gap: 4px; min-width: 0; }
.quick-copy strong, .quick-copy small { overflow-wrap: anywhere; line-height: 1.3; }
.quick-copy strong { font-size: 13px; }
.quick-copy small { color: var(--text-secondary); font-size: 11px; }
@media (max-width: 1120px) { .quick-create { grid-template-columns: repeat(2,minmax(0,1fr)); } .quick-btn:nth-child(2n) { border-right: 0; } .quick-btn:nth-last-child(-n + 4) { border-bottom: 1px solid var(--border); } .quick-btn:nth-last-child(-n + 2) { border-bottom: 0; } }
@media (max-width: 620px) { .section-heading { flex-wrap: wrap; } .section-heading small { width: 100%; max-width: 100%; margin-left: 24px; } .quick-create { grid-template-columns: 1fr; } .quick-btn { border-right: 0; border-bottom: 1px solid var(--border) !important; } .quick-btn:last-child { border-bottom: 0 !important; } }
</style>
