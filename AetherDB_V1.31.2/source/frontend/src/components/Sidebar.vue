<script setup>
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { Archive, BookOpen, Bot, ChevronLeft, CircleHelp, Database, FileSearch, GitFork, Home, KeyRound, Network, PenLine, ScrollText, Search, Settings, Upload } from "@lucide/vue";
import { useAppStore } from "../stores/app.js";

const router = useRouter();
const route = useRoute();
const { t } = useI18n();
const store = useAppStore();
const appVersion = __APP_VERSION__;

const sections = [
  { title: "", items: [{ id: "home", path: "/", icon: Home, label: "首页" }] },
  { title: "创作", items: [
    { id: "workspace", path: "/workspace", icon: PenLine, label: "创作工作台" },
    { id: "documents", path: "/worlds", icon: FileSearch, label: "文档与实体" },
    { id: "import", path: "/import", icon: Upload, label: "批量导入" },
  ] },
  { title: "世界", items: [
    { id: "worlds", path: "/worlds", icon: Database, label: "世界库管理" },
    { id: "graph", path: "/graph", icon: Network, label: "关系图谱" },
    { id: "search", path: "/search", icon: Search, label: "搜索与发现" },
    { id: "reader", path: "/reader", icon: BookOpen, label: "世界阅读器" },
  ] },
  { title: "AI 助手", items: [
    { id: "ai-settings", path: "/settings", query: {}, icon: Bot, label: "AI 设置与管理" },
    { id: "ai-import", path: "/import", query: { source: "world_setting" }, icon: GitFork, label: "设定整理" },
  ] },
  { title: "设置与管理", items: [
    { id: "backup", path: "/settings", query: { section: "backup" }, icon: Archive, label: "备份与恢复" },
    { id: "security", path: "/settings", query: { section: "security" }, icon: KeyRound, label: "访问与高级设置" },
  ] },
];

function navigate(item) { router.push({ path: item.path, query: item.query || {} }); }

function isActive(item) {
  if (route.path !== item.path) return false;
  if (item.id === "home") return route.path === "/";
  if (item.id === "workspace") return route.path === "/workspace";
  if (item.query?.section) return route.query.section === item.query.section;
  if (item.id === "ai-settings") return !route.query.section;
  if (item.query?.source) return route.query.source === item.query.source;
  return true;
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: store.sidebarCollapsed }">
    <div class="brand">
      <div class="brand-mark">◆</div>
      <div v-if="!store.sidebarCollapsed" class="brand-copy"><strong>AetherDB</strong><span>Worldview Engine</span><small>v{{ appVersion }}</small></div>
    </div>
    <nav class="nav-sections">
      <section v-for="navSection in sections" :key="navSection.title || 'home'" class="nav-section">
        <p v-if="navSection.title && !store.sidebarCollapsed" class="section-title">{{ t(navSection.title) }}</p>
        <button v-for="item in navSection.items" :key="item.id" class="nav-item" :class="{ active: isActive(item) }" type="button" :title="t(item.label)" :aria-label="t(item.label)" @click="navigate(item)">
          <component :is="item.icon" :size="16" /><span v-if="!store.sidebarCollapsed" class="nav-label">{{ t(item.label) }}</span>
        </button>
      </section>
    </nav>
    <div class="sidebar-footer">
      <div class="world-chip"><div class="world-thumb">{{ store.currentWorldName.slice(0, 1) }}</div><div v-if="!store.sidebarCollapsed" class="world-meta"><strong>{{ store.currentWorldName }}</strong><span>{{ store.currentWorldMode }}</span></div></div>
      <div v-if="!store.sidebarCollapsed" class="server-state"><span :class="['state-dot', { online: store.backendAvailable }]"></span><span>{{ t(store.backendAvailable ? "本地服务运行中" : "未连接服务") }}</span></div>
      <div class="footer-actions"><button type="button" :title="t(store.sidebarCollapsed ? '展开侧栏' : '折叠侧栏')" @click="store.toggleSidebar"><ChevronLeft :size="16" :class="{ reversed: store.sidebarCollapsed }" /></button><button type="button" :class="{ active: route.path === '/logs' }" :title="t('日志')" @click="router.push('/logs')"><ScrollText :size="16" /></button><button type="button" :title="t('AI 设置与管理')" @click="router.push('/settings')"><Settings :size="16" /></button><button type="button" :title="t('帮助')"><CircleHelp :size="16" /></button></div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar { width: 224px; height: 100vh; display: flex; flex-direction: column; flex-shrink: 0; padding: 17px 13px; background: var(--bg-sidebar); border-right: 1px solid rgba(230,226,242,.8); color: var(--text-sidebar); transition: width .22s ease; }
.sidebar.collapsed { width: 68px; align-items: center; }
.brand { display: flex; align-items: center; gap: 10px; min-height: 45px; margin-bottom: 16px; }
.brand-mark { width: 34px; height: 34px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 50%; background: var(--accent); color: #fff; box-shadow: 0 10px 26px rgba(114,87,232,.25); }
.brand-copy { display: grid; grid-template-columns: auto auto; min-width: 0; align-items: baseline; }
.brand-copy strong { grid-column: 1 / -1; color: var(--text-primary); font-size: 14px; }
.brand-copy span { color: var(--text-muted); font-size: 9px; }
.brand-copy small { justify-self: end; color: var(--accent); font-size: 8px; }
.nav-sections { display: flex; flex-direction: column; gap: 11px; overflow-y: auto; padding-right: 2px; }
.section-title { margin: 0 0 4px 4px; color: var(--text-secondary); font-size: 11px; }
.nav-item { width: 100%; min-height: 32px; display: flex; align-items: center; gap: 9px; border: 0; border-radius: 6px; padding: 7px 9px; background: transparent; color: var(--text-sidebar); cursor: pointer; text-align: left; }
.nav-item:hover, .nav-item.active { background: var(--accent-soft); color: var(--accent); }
.nav-item svg { flex: 0 0 auto; }
.nav-label { min-width: 0; overflow-wrap: anywhere; font-size: 12px; line-height: 1.25; }
.sidebar-footer { margin-top: auto; display: grid; gap: 9px; }
.world-chip { display: flex; align-items: center; gap: 8px; padding: 7px; border-radius: 8px; background: rgba(255,255,255,.72); }
.world-thumb { width: 34px; height: 34px; flex: 0 0 auto; display: grid; place-items: center; border-radius: 8px; background: #29253b; color: #fff; font-weight: 700; }
.world-meta { display: grid; min-width: 0; }
.world-meta strong, .world-meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-meta strong { color: var(--text-primary); font-size: 12px; }
.world-meta span, .server-state { color: var(--text-muted); font-size: 10px; }
.server-state { display: flex; align-items: center; gap: 6px; }
.state-dot { width: 7px; height: 7px; border-radius: 50%; background: #c4c0cf; }
.state-dot.online { background: #32c48d; }
.footer-actions { display: flex; justify-content: space-around; }
.footer-actions button { width: 29px; height: 29px; display: grid; place-items: center; border: 0; border-radius: 50%; background: transparent; color: var(--text-secondary); cursor: pointer; }
.footer-actions button:hover, .footer-actions button.active { background: var(--accent-soft); color: var(--accent); }
.reversed { transform: rotate(180deg); }
@media (max-width: 800px) {
  .sidebar { width: 68px; align-items: center; padding-inline: 10px; }
  .brand-copy, .nav-label, .section-title, .world-meta, .server-state { display: none; }
  .nav-item { justify-content: center; padding-inline: 7px; }
  .world-chip { padding: 5px; }
  .sidebar-footer { width: 44px; justify-items: center; }
  .footer-actions { flex-direction: column; align-items: center; gap: 2px; }
}
</style>
