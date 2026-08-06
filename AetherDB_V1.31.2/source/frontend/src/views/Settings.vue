<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  Archive,
  Bot,
  Check,
  Database,
  KeyRound,
  Languages,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
} from "@lucide/vue";
import AiManagementPanel from "../components/AiManagementPanel.vue";
import { createBackup, getAutoBackup, getBackupStats, listBackups, restoreBackup, setAutoBackup } from "../api/backup.js";
import { activatePromptProfile, createPromptProfile, listPromptProfiles, testPromptProfile, updatePromptProfile } from "../api/prompts.js";
import { getActiveBook, getActiveDatabase, getBooks, getDatabases } from "../api/settings.js";
import { setLocale } from "../i18n/index.js";
import { useAppStore } from "../stores/app.js";

const route = useRoute();
const router = useRouter();
const { locale, t } = useI18n();
const store = useAppStore();
const isDesktopApp = Boolean(window.__TAURI_INTERNALS__);
const validSections = new Set(["ai", "prompt", "data", "backup", "security"]);
const section = ref(validSections.has(route.query.section) ? route.query.section : "ai");
const apiKey = ref(sessionStorage.getItem("aetherdb_api_key") || "");
const advancedMode = ref(localStorage.getItem("aetherdb_advanced_mode") === "true");
const activeDatabase = ref(null);
const activeBook = ref(null);
const databases = ref([]);
const books = ref([]);
const loading = ref(true);
const message = ref("");
const error = ref("");

const promptProfiles = ref([]);
const selectedPromptId = ref("");
const promptName = ref("");
const promptContent = ref("");
const loadedPromptContent = ref("");
const promptTestResult = ref(null);
const promptBusy = ref(false);

const backupStats = ref(null);
const backups = ref([]);
const autoBackup = ref(true);
const backupBusy = ref(false);
const restoreTarget = ref(null);

const sections = [
  { key: "ai", label: "AI 设置与管理", desc: "供应商、模型、本地部署与任务路由", icon: Bot, capability: "manage_models" },
  { key: "prompt", label: "AI 指令模板", desc: "Prompt Profile、测试与版本", icon: Sparkles, capability: "manage_models" },
  { key: "data", label: "数据库管理", desc: "世界库与作品状态", icon: Database, capability: "read_content" },
  { key: "backup", label: "备份与恢复", desc: "数据备份、恢复与自动备份", icon: Archive, capability: "manage_backups" },
  { key: "security", label: "访问与高级设置", desc: "AetherDB 凭据与技术信息", icon: KeyRound },
];

const currentPrompt = computed(() => promptProfiles.value.find((item) => item.profile_id === selectedPromptId.value));
const currentSection = computed(() => sections.find((item) => item.key === section.value));
const deploymentLabel = computed(() => t({
  local_desktop: "本地桌面所有者模式",
  competition_local: "赛事本地所有者模式",
  hosted_bridge: "托管桥接（未启用）",
  full_server_deployment: "完整服务器部署（未启用）",
}[store.authStatus?.deployment_mode] || "部署模式未知"));
const permissionSummary = computed(() => {
  if (!store.authStatus?.authenticated) return t("凭据尚未通过验证，管理功能保持锁定。");
  if (!store.authStatus?.deployment_enabled) return t("当前凭据有效，但此部署模式尚未启用。");
  if (store.authStatus?.effective_role === "owner") return t("已验证 Owner，会话拥有完整本地管理能力。");
  return t("当前会话按服务器角色能力运行。");
});
const setupSteps = computed(() => [
  { label: "选择 AI 模式", done: Boolean(store.aiSetup.mode) },
  { label: "配置可用模型", done: store.aiConfigured },
  { label: "选择 AI 指令模板", done: promptProfiles.value.some((item) => item.is_active) },
]);

function showMessage(value) {
  message.value = value;
  window.setTimeout(() => { message.value = ""; }, 2400);
}

function setInterfaceLocale(value) {
  setLocale(value);
  showMessage(t("界面语言已更新"));
}

function isSectionAvailable(item) {
  if (!item?.capability || !store.authStatus) return true;
  return store.hasCapability(item.capability);
}

watch(section, (value) => {
  router.replace({ query: value === "ai" ? {} : { section: value } });
  if (value === "backup" && !backupStats.value) loadBackups();
});

watch(() => route.query.section, (value) => {
  const next = validSections.has(value) ? value : "ai";
  if (section.value !== next) section.value = next;
});

watch(selectedPromptId, () => {
  const profile = currentPrompt.value;
  promptName.value = profile?.name || "";
  promptContent.value = profile?.content || "";
  loadedPromptContent.value = promptContent.value;
  promptTestResult.value = null;
});

async function saveAccessSettings() {
  const trimmed = apiKey.value.trim();
  if (!isDesktopApp) {
    if (trimmed) sessionStorage.setItem("aetherdb_api_key", trimmed);
    else sessionStorage.removeItem("aetherdb_api_key");
  }
  localStorage.setItem("aetherdb_advanced_mode", String(advancedMode.value));
  await store.loadAuthStatus();
  if (!isSectionAvailable(currentSection.value)) section.value = "security";
  if (store.authStatus?.authenticated && store.authStatus?.deployment_enabled) {
    await loadRuntimeState();
  }
  showMessage(t("访问设置已保存，后续请求将使用新的凭据。"));
}

function skipSetup() {
  store.setAiSetup({ initialized: false });
  showMessage(t("已跳过 AI 配置，写作、阅读和搜索仍可使用"));
}

async function loadRuntimeState() {
  loading.value = true;
  error.value = "";
  if (!store.hasCapability("read_content")) {
    loading.value = false;
    return;
  }
  const promptTask = store.hasCapability("manage_models") ? listPromptProfiles() : Promise.resolve({ profiles: [] });
  const tasks = await Promise.allSettled([getActiveDatabase(), getActiveBook(), getDatabases(), getBooks(), promptTask]);
  databases.value = tasks[2].status === "fulfilled" ? (tasks[2].value?.databases || []) : [];
  books.value = tasks[3].status === "fulfilled" ? (tasks[3].value?.books || []) : [];
  const databaseId = tasks[0].status === "fulfilled" ? tasks[0].value?.active_database_id : null;
  const bookId = tasks[1].status === "fulfilled" ? tasks[1].value?.active_book_id : null;
  activeDatabase.value = databases.value.find((item) => item.database_id === databaseId) || (databaseId ? { database_id: databaseId, name: databaseId } : null);
  activeBook.value = books.value.find((item) => item.book_id === bookId) || (bookId ? { book_id: bookId, title: bookId } : null);
  if (tasks[4].status === "fulfilled") {
    promptProfiles.value = tasks[4].value?.profiles || [];
    selectedPromptId.value = promptProfiles.value.find((item) => item.is_active)?.profile_id || promptProfiles.value[0]?.profile_id || "";
  }
  store.backendAvailable = tasks.some((task) => task.status === "fulfilled");
  if (!store.backendAvailable) error.value = t("未连接到 AetherDB 后端。页面仍可打开，但管理操作需要本地服务。");
  loading.value = false;
}

async function savePrompt() {
  if (!promptName.value.trim() || !promptContent.value.trim()) return;
  promptBusy.value = true;
  error.value = "";
  try {
    if (selectedPromptId.value) {
      await updatePromptProfile(selectedPromptId.value, { name: promptName.value.trim(), content: promptContent.value });
      showMessage(t("AI 指令模板已更新并生成新版本"));
    } else {
      const id = `custom_${Date.now()}`;
      await createPromptProfile({ profile_id: id, name: promptName.value.trim(), content: promptContent.value });
      selectedPromptId.value = id;
      showMessage(t("自定义 AI 指令模板已创建"));
    }
    const result = await listPromptProfiles();
    promptProfiles.value = result?.profiles || [];
    loadedPromptContent.value = promptContent.value;
  } catch (err) {
    error.value = err.message || t("保存 AI 指令模板失败");
  } finally { promptBusy.value = false; }
}

function createPromptDraft() {
  selectedPromptId.value = "";
  promptName.value = "";
  promptContent.value = "";
  loadedPromptContent.value = "";
  promptTestResult.value = null;
}

async function activatePrompt() {
  if (!selectedPromptId.value) return;
  promptBusy.value = true;
  try {
    await activatePromptProfile(selectedPromptId.value);
    promptProfiles.value = promptProfiles.value.map((item) => ({ ...item, is_active: item.profile_id === selectedPromptId.value ? 1 : 0 }));
    store.setAiSetup({ profile: promptName.value, initialized: true });
    showMessage(t("当前 AI 指令模板已启用"));
  } catch (err) { error.value = err.message || t("启用模板失败"); }
  finally { promptBusy.value = false; }
}

async function testPrompt() {
  if (!selectedPromptId.value) return;
  promptBusy.value = true;
  try {
    promptTestResult.value = await testPromptProfile({ profile_id: selectedPromptId.value, task_type: "all", variables: {} });
    showMessage(t("模板测试已完成"));
  } catch (err) { error.value = err.message || t("模板测试失败"); }
  finally { promptBusy.value = false; }
}

async function loadBackups() {
  backupBusy.value = true;
  error.value = "";
  const tasks = await Promise.allSettled([getBackupStats(), listBackups(), getAutoBackup()]);
  if (tasks[0].status === "fulfilled") backupStats.value = tasks[0].value;
  if (tasks[1].status === "fulfilled") backups.value = tasks[1].value?.backups || [];
  if (tasks[2].status === "fulfilled") autoBackup.value = Boolean(tasks[2].value?.auto_backup_on_startup);
  if (tasks.every((task) => task.status === "rejected")) error.value = t("无法读取备份状态，请检查 Owner 或管理凭据。");
  backupBusy.value = false;
}

async function runBackup() {
  backupBusy.value = true;
  try { await createBackup("Created from desktop settings"); await loadBackups(); showMessage(t("数据备份已创建")); }
  catch (err) { error.value = err.message || t("创建备份失败"); }
  finally { backupBusy.value = false; }
}

async function toggleAutoBackup() {
  try { await setAutoBackup(autoBackup.value); showMessage(t("自动备份设置已更新")); }
  catch (err) { autoBackup.value = !autoBackup.value; error.value = err.message || t("更新自动备份失败"); }
}

async function confirmRestore() {
  if (!restoreTarget.value) return;
  backupBusy.value = true;
  try { await restoreBackup(restoreTarget.value.name); restoreTarget.value = null; showMessage(t("备份已恢复，请刷新相关页面")); }
  catch (err) { error.value = err.message || t("恢复备份失败"); }
  finally { backupBusy.value = false; }
}

onMounted(async () => {
  await store.loadAuthStatus();
  if (!isSectionAvailable(currentSection.value)) section.value = "security";
  await loadRuntimeState();
});
</script>

<template>
  <div class="page-shell settings-page">
    <header class="page-header settings-header">
      <div><h1>{{ t("AI 设置与管理") }}</h1><p>{{ t("统一管理模型供应商、本地运行时、任务分工、AI 指令以及数据安全设置。") }}</p></div>
      <span class="status-pill" :class="{ offline: store.backendAvailable === false }">{{ t(store.backendAvailable === false ? "服务未连接" : "本地服务已连接") }}</span>
    </header>

    <section v-if="!store.aiConfigured && store.hasCapability('manage_models')" class="setup-wizard">
      <div><span class="eyebrow">{{ t("首次启动") }}</span><h2>{{ t("三步完成 AI 工作流") }}</h2><p>{{ t("可以先跳过；未配置 AI 时，写作、阅读和普通搜索仍可使用。") }}</p></div>
      <div class="setup-steps"><div v-for="step in setupSteps" :key="step.label" :class="{ done: step.done }"><Check :size="15" /><span>{{ t(step.label) }}</span></div></div>
      <div class="setup-actions"><button class="btn btn-primary" type="button" @click="section = 'ai'">{{ t("开始配置") }}</button><button class="btn btn-secondary" type="button" @click="skipSetup">{{ t("暂时跳过") }}</button></div>
    </section>

    <div class="settings-layout">
      <aside class="section-nav">
        <button v-for="item in sections" :key="item.key" type="button" :class="{ active: section === item.key }" :disabled="!isSectionAvailable(item)" :title="!isSectionAvailable(item) ? t('当前会话无权访问此设置') : undefined" @click="section = item.key">
          <component :is="item.icon" :size="18" /><span><strong>{{ t(item.label) }}</strong><small>{{ t(item.desc) }}</small></span>
        </button>
      </aside>

      <main class="settings-content">
        <AiManagementPanel v-if="section === 'ai'" />

        <section v-else-if="section === 'prompt'" class="settings-section">
          <header class="content-heading"><div><h2>{{ t("AI 指令模板") }}</h2><p>{{ t("选择预设或维护自定义模板；测试和启用是两个独立动作。") }}</p></div><button class="btn btn-secondary" type="button" @click="createPromptDraft">{{ t("新建自定义模板") }}</button></header>
          <div class="prompt-layout">
            <div class="prompt-list">
              <button v-for="profile in promptProfiles" :key="profile.profile_id" type="button" :class="{ active: selectedPromptId === profile.profile_id }" @click="selectedPromptId = profile.profile_id">
                <span><strong>{{ profile.name }}</strong><small>{{ t(profile.is_builtin ? "预设模板" : "自定义模板") }} · v{{ profile.version || 1 }}</small></span>
                <Check v-if="profile.is_active" :size="16" />
              </button>
              <div v-if="!promptProfiles.length" class="small-empty">{{ t("暂无可用模板") }}</div>
            </div>
            <div class="prompt-editor">
              <div class="field-row"><label>{{ t("模板名称") }}</label><input v-model="promptName" maxlength="120" :placeholder="t('输入模板名称')" /></div>
              <div class="field-row"><label>{{ t("模板内容") }}</label><textarea v-model="promptContent" rows="16" :placeholder="t('定义模型在创作和分析任务中的工作方式...')" /></div>
              <div class="editor-actions">
                <button class="btn btn-secondary" type="button" :disabled="promptContent === loadedPromptContent" @click="promptContent = loadedPromptContent"><RotateCcw :size="16" />{{ t("恢复本次修改") }}</button>
                <button class="btn btn-secondary" type="button" :disabled="!selectedPromptId || promptBusy" @click="testPrompt">{{ t("测试模板") }}</button>
                <button class="btn btn-secondary" type="button" :disabled="!selectedPromptId || currentPrompt?.is_active || promptBusy" @click="activatePrompt">{{ t("启用模板") }}</button>
                <button class="btn btn-primary" type="button" :disabled="!promptName.trim() || !promptContent.trim() || promptBusy" @click="savePrompt"><Save :size="16" />{{ t("保存版本") }}</button>
              </div>
              <pre v-if="promptTestResult" class="test-result">{{ JSON.stringify(promptTestResult, null, 2) }}</pre>
            </div>
          </div>
        </section>

        <section v-else-if="section === 'data'" class="settings-section">
          <header class="content-heading"><div><h2>{{ t("数据库管理") }}</h2><p>{{ t("查看当前世界库、作品和本地注册状态。") }}</p></div><button class="icon-button" type="button" :title="t('刷新数据库状态')" @click="loadRuntimeState"><RefreshCw :size="17" :class="{ spinning: loading }" /></button></header>
          <div class="runtime-grid">
            <div><small>{{ t("当前世界库") }}</small><strong>{{ activeDatabase?.name || t("未选择") }}</strong></div>
            <div><small>{{ t("当前作品") }}</small><strong>{{ activeBook?.title || t("未选择") }}</strong></div>
            <div><small>{{ t("世界库数量") }}</small><strong>{{ databases.length }}</strong></div>
            <div><small>{{ t("作品数量") }}</small><strong>{{ books.length }}</strong></div>
          </div>
          <div v-if="advancedMode" class="advanced-box"><strong>{{ t("高级信息") }}</strong><span>database_id: {{ activeDatabase?.database_id || t("未选择") }}</span><span>book_id: {{ activeBook?.book_id || t("未选择") }}</span></div>
        </section>

        <section v-else-if="section === 'backup'" class="settings-section">
          <header class="content-heading"><div><h2>{{ t("备份与恢复") }}</h2><p>{{ t("备份当前业务数据。恢复会覆盖现有内容，因此需要二次确认。") }}</p></div><button class="btn btn-primary" type="button" :disabled="backupBusy" @click="runBackup"><Archive :size="16" />{{ t("创建备份") }}</button></header>
          <div class="runtime-grid"><div><small>{{ t("备份数量") }}</small><strong>{{ backupStats?.total_backups || 0 }}</strong></div><div><small>{{ t("占用空间") }}</small><strong>{{ backupStats?.total_size_human || "0 B" }}</strong></div><div><small>{{ t("最近备份") }}</small><strong>{{ backupStats?.last_backup?.timestamp || t("暂无") }}</strong></div><label class="setting-toggle"><input v-model="autoBackup" type="checkbox" @change="toggleAutoBackup" /><span><strong>{{ t("启动时自动备份") }}</strong><small>{{ t("本地服务启动时创建安全快照") }}</small></span></label></div>
          <div class="backup-list"><article v-for="backup in backups" :key="backup.name"><div><strong>{{ backup.timestamp || backup.name }}</strong><span>{{ backup.description || t("数据备份") }} · {{ backup.size_human || t("大小未知") }}</span></div><button class="btn btn-secondary" type="button" @click="restoreTarget = backup">{{ t("恢复") }}</button></article><div v-if="!backups.length" class="small-empty">{{ t("暂无数据备份") }}</div></div>
        </section>

        <section v-else class="settings-section">
          <header class="content-heading"><div><h2>{{ t("访问与高级设置") }}</h2><p>{{ t("这里的 API Key 用于访问 AetherDB 后端，不是云端模型供应商密钥。") }}</p></div><ShieldCheck :size="24" /></header>
          <div class="permission-summary" :class="{ unavailable: store.authStatus && !store.authStatus.deployment_enabled }">
            <span class="permission-icon"><ShieldCheck :size="20" /></span>
            <span><strong>{{ deploymentLabel }}</strong><small>{{ permissionSummary }}</small></span>
            <span v-if="store.authStatus?.authenticated && store.authStatus?.deployment_enabled" class="role-pill">{{ t("当前主体：{role} · {count} 项能力", { role: store.authStatus.effective_role === "owner" ? t("本地 Owner") : store.authStatus.effective_role, count: store.authStatus.capabilities.length }) }}</span>
            <button v-else class="icon-button" type="button" :title="t('重新验证权限')" :disabled="store.authStatusLoading" @click="store.loadAuthStatus"><RefreshCw :size="16" :class="{ spinning: store.authStatusLoading }" /></button>
          </div>
          <div class="language-setting">
            <span class="language-setting-icon"><Languages :size="19" /></span>
            <span><strong>{{ t("界面语言") }}</strong><small>{{ t("选择 AetherDB 的界面语言。切换立即生效，不会重载当前页面。") }}</small></span>
            <div class="segmented-control" role="group" :aria-label="t('界面语言')">
              <button type="button" :class="{ active: locale === 'zh-CN' }" @click="setInterfaceLocale('zh-CN')">{{ t("中文") }}</button>
              <button type="button" :class="{ active: locale === 'en-US' }" @click="setInterfaceLocale('en-US')">{{ t("英文") }}</button>
            </div>
          </div>
          <div class="security-card">
            <div v-if="isDesktopApp" class="desktop-credential-note"><KeyRound :size="18" /><span><strong>{{ t("桌面 Owner 会话") }}</strong><small>{{ t("桌面会话凭据由 AetherDB 临时管理，不写入配置文件或浏览器存储。") }}</small></span></div>
            <div v-else class="field-row"><label>AetherDB API Key</label><input v-model="apiKey" type="password" autocomplete="off" :placeholder="t('请求将通过 X-API-Key 请求头携带')" /></div>
            <label class="setting-toggle"><input v-model="advancedMode" type="checkbox" /><span><strong>{{ t("高级模式") }}</strong><small>{{ t("显示数据库、作品及模型配置的技术标识") }}</small></span></label>
            <button class="btn btn-primary" type="button" :disabled="store.authStatusLoading" @click="saveAccessSettings"><Save :size="16" />{{ t("保存访问设置") }}</button>
          </div>
        </section>

        <div v-if="error || message" class="page-feedback" :class="{ error: Boolean(error) }">{{ error || message }}</div>
      </main>
    </div>

    <div v-if="restoreTarget" class="dialog-backdrop" @click.self="restoreTarget = null"><section class="restore-dialog" role="dialog" aria-modal="true"><Archive :size="28" /><h3>{{ t("恢复数据备份") }}</h3><p>{{ t("将恢复“{name}”并覆盖当前业务数据。请确认当前工作已经保存。", { name: restoreTarget.timestamp || restoreTarget.name }) }}</p><div><button class="btn btn-secondary" type="button" @click="restoreTarget = null">{{ t("取消") }}</button><button class="btn danger-button" type="button" :disabled="backupBusy" @click="confirmRestore">{{ t("确认恢复") }}</button></div></section></div>
  </div>
</template>

<style scoped>
.settings-page { max-width: 1500px; margin: 0 auto; }
.settings-header { padding-top: 4px; }
.status-pill.offline { background: #fff3e8; color: #9a5b18; }
.setup-wizard { display: grid; grid-template-columns: minmax(260px,1fr) minmax(250px,.8fr) auto; gap: 18px; align-items: center; margin-bottom: 18px; border: 1px solid #ddd6fb; border-radius: 8px; background: linear-gradient(105deg,#fff 0%,#f6f3ff 100%); padding: 17px; }
.eyebrow { color: var(--accent); font-size: 11px; }
.setup-wizard h2 { margin: 4px 0 5px; font-size: 17px; }
.setup-wizard p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.setup-steps { display: grid; gap: 7px; }
.setup-steps div { display: flex; align-items: center; gap: 7px; color: var(--text-muted); font-size: 12px; }
.setup-steps div.done { color: #167251; }
.setup-actions { display: flex; gap: 8px; }
.settings-layout { display: grid; grid-template-columns: 230px minmax(0,1fr); gap: 16px; align-items: start; }
.section-nav { position: sticky; top: 18px; display: grid; gap: 6px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.88); box-shadow: var(--soft-shadow); padding: 8px; }
.section-nav button { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 9px; align-items: start; border: 0; border-radius: 7px; background: transparent; color: var(--text-secondary); cursor: pointer; text-align: left; padding: 10px; }
.section-nav button.active { background: var(--accent-soft); color: var(--accent); }
.section-nav button:disabled { opacity: .48; cursor: not-allowed; }
.section-nav button span { display: grid; gap: 3px; }
.section-nav strong { color: inherit; font-size: 12px; }
.section-nav small { color: var(--text-muted); font-size: 10px; line-height: 1.45; }
.settings-content, .settings-section { display: grid; gap: 15px; min-width: 0; }
.settings-section { border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.92); box-shadow: var(--soft-shadow); padding: 18px; }
.content-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.content-heading h2 { margin-bottom: 4px; font-size: 17px; }
.content-heading p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.prompt-layout { display: grid; grid-template-columns: 230px minmax(0,1fr); gap: 13px; }
.prompt-list, .prompt-editor { display: grid; gap: 8px; align-content: start; }
.prompt-list button { display: flex; justify-content: space-between; gap: 8px; align-items: center; border: 1px solid var(--border); border-radius: 8px; background: #fff; cursor: pointer; text-align: left; padding: 10px; }
.prompt-list button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
.prompt-list button span { display: grid; gap: 3px; min-width: 0; }
.prompt-list strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.prompt-list small { color: var(--text-secondary); font-size: 10px; }
.editor-actions { display: flex; justify-content: flex-end; gap: 7px; flex-wrap: wrap; }
.test-result { max-height: 220px; overflow: auto; border-radius: 8px; background: #252237; color: #e9e6f6; padding: 12px; font-size: 11px; white-space: pre-wrap; }
.runtime-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 9px; }
.runtime-grid > div, .setting-toggle { display: grid; gap: 5px; border-radius: 8px; background: var(--bg-secondary); padding: 12px; }
.runtime-grid small, .advanced-box span { color: var(--text-muted); font-size: 11px; }
.runtime-grid strong, .advanced-box span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.advanced-box { display: grid; gap: 6px; border: 1px dashed #cdc5e9; border-radius: 8px; padding: 12px; }
.setting-toggle { grid-template-columns: auto minmax(0,1fr); align-items: center; cursor: pointer; }
.setting-toggle input { width: auto; }
.setting-toggle span { display: grid; gap: 3px; }
.backup-list { display: grid; gap: 8px; }
.backup-list article { display: flex; justify-content: space-between; gap: 12px; align-items: center; border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.backup-list article div { display: grid; gap: 3px; min-width: 0; }
.backup-list article strong, .backup-list article span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.backup-list article strong { font-size: 12px; }
.backup-list article span { color: var(--text-secondary); font-size: 10px; }
.security-card { display: grid; gap: 14px; max-width: 680px; }
.security-card .setting-toggle { background: var(--bg-secondary); }
.language-setting { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 11px; align-items: center; max-width: 680px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-secondary); padding: 12px; }
.language-setting-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 7px; background: #fff; color: var(--accent); }
.language-setting > span:nth-child(2) { display: grid; gap: 3px; min-width: 0; }
.language-setting strong { font-size: 12px; }
.language-setting small { color: var(--text-muted); font-size: 10px; line-height: 1.5; }
.segmented-control { display: inline-grid; grid-template-columns: repeat(2,minmax(72px,1fr)); gap: 2px; border: 1px solid var(--border); border-radius: 7px; background: #fff; padding: 3px; }
.segmented-control button { min-height: 30px; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary); cursor: pointer; padding: 5px 10px; font-size: 11px; white-space: nowrap; }
.segmented-control button.active { background: var(--accent); color: #fff; }
.permission-summary { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 11px; align-items: center; max-width: 680px; border: 1px solid #cfe9df; border-radius: 8px; background: #f3fbf7; padding: 12px; }
.permission-summary.unavailable { border-color: #ead7bc; background: #fff9ef; }
.permission-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px; background: #e4f6ee; color: #167251; }
.permission-summary.unavailable .permission-icon { background: #f8ead5; color: #9a5b18; }
.permission-summary > span:nth-child(2), .desktop-credential-note > span { min-width: 0; display: grid; gap: 3px; }
.permission-summary strong, .desktop-credential-note strong { font-size: 12px; }
.permission-summary small, .desktop-credential-note small { color: var(--text-secondary); font-size: 10px; line-height: 1.45; }
.role-pill { border-radius: 999px; background: #e4f6ee; color: #167251; padding: 5px 9px; font-size: 10px; white-space: nowrap; }
.desktop-credential-note { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 9px; align-items: center; color: var(--text-secondary); }
.small-empty { min-height: 90px; display: grid; place-items: center; border: 1px dashed var(--border); border-radius: 8px; color: var(--text-muted); font-size: 12px; }
.icon-button { width: 34px; height: 34px; display: inline-grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.page-feedback { position: sticky; bottom: 12px; z-index: 5; border-radius: 8px; background: #edfdf6; color: #167251; box-shadow: var(--soft-shadow); padding: 10px 12px; font-size: 12px; }
.page-feedback.error { background: #fff0f0; color: #a33f3f; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 60; display: grid; place-items: center; padding: 20px; background: rgba(28,25,44,.44); }
.restore-dialog { width: min(440px,100%); display: grid; gap: 13px; border-radius: 8px; background: #fff; padding: 22px; }
.restore-dialog p { color: var(--text-secondary); font-size: 12px; line-height: 1.7; }
.restore-dialog > div { display: flex; justify-content: flex-end; gap: 8px; }
.danger-button { background: #b54545; color: #fff; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1050px) { .setup-wizard, .settings-layout, .prompt-layout { grid-template-columns: 1fr; } .section-nav { position: static; grid-template-columns: repeat(2,minmax(0,1fr)); } .runtime-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 650px) { .section-nav, .runtime-grid { grid-template-columns: 1fr; } .content-heading, .setup-actions { flex-direction: column; } .editor-actions .btn { width: 100%; } .language-setting, .permission-summary { grid-template-columns: auto minmax(0,1fr); } .segmented-control, .permission-summary > :last-child { grid-column: 1 / -1; width: 100%; } .segmented-control button { flex: 1; } .role-pill { text-align: center; white-space: normal; } }
</style>
