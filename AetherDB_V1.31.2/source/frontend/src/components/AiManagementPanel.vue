<script setup>
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cloud,
  Cpu,
  FlaskConical,
  Pencil,
  Plus,
  RefreshCw,
  Route,
  Server,
  Settings2,
  Trash2,
  X,
} from "@lucide/vue";
import { useAiManagementStore } from "../stores/aiManagement.js";
import { useAppStore } from "../stores/app.js";
import LocalDeploymentPanel from "./LocalDeploymentPanel.vue";
import HardwareAccelerationPanel from "./HardwareAccelerationPanel.vue";
import VectorMaintenancePanel from "./VectorMaintenancePanel.vue";

const store = useAiManagementStore();
const appStore = useAppStore();
const { locale, t } = useI18n();
const showLocalDeploy = ref(false);
const dialog = ref(null);
const confirmAction = ref(null);
const advancedMode = localStorage.getItem("aetherdb_advanced_mode") === "true";

const TASK_LABELS = {
  creative_continue: "续写创作",
  creative_assist: "创作辅助",
  chapter_analysis: "章节分析",
  world_consistency: "世界观检查",
  logic_check: "逻辑冲突检查",
  chapter_extract: "章节设定提取",
  changeset_build: "生成变更预览",
  changeset_review: "变更复核",
  rag_answer: "读者问答",
  "translation.entity": "实体翻译",
  "translation.chapter": "章节翻译",
};

const providerDefaults = () => ({
  id: "", display_name: "", provider_type: "openai_compatible", base_url: "https://api.openai.com/v1",
  api_format: "openai_compatible", credential_ref: "", models_endpoint: "/models", enabled: true, supports_model_discovery: true,
});

const PROVIDER_PRESETS = {
  openai_compatible: { base_url: "https://api.openai.com/v1", api_format: "openai_compatible", models_endpoint: "/models", supports_model_discovery: true },
  deepseek: { base_url: "https://api.deepseek.com", api_format: "openai_compatible", models_endpoint: "/models", supports_model_discovery: true },
  ollama: { base_url: "http://127.0.0.1:11434", api_format: "ollama", models_endpoint: "/api/tags", credential_ref: "", supports_model_discovery: true },
  custom: { base_url: "", api_format: "custom", models_endpoint: "", supports_model_discovery: false },
};
const profileDefaults = (providerId = "") => ({
  id: "", provider_id: providerId, provider_model_name: "", display_name: "", model_type: "chat",
  enabled: true, context_length: 32768, max_output_tokens: 4096, supports_streaming: true,
  supports_tools: false, supports_json_mode: true, cost_level: "unknown", privacy_level: "cloud_upload",
});
const bindingDefaults = () => ({
  id: "", scope_type: "global", scope_id: "", task_type: "creative_assist", target_id: "", priority: 0, enabled: true,
});

const availableProfiles = computed(() => store.profiles.filter((item) => item.enabled));
const latestTests = computed(() => store.tests.slice(0, 6));
const isSystemProvider = (provider) => provider.provider_type === "aetherdb_worker";
const isPassedTest = (test) => test?.status === "passed" || test?.success === true;
const scopeOptions = computed(() => {
  if (dialog.value?.type !== "binding") return [];
  if (dialog.value.form.scope_type === "database") {
    return appStore.databases.map((item) => ({
      value: item.database_id,
      label: item.name || item.title || item.database_id,
    }));
  }
  if (dialog.value.form.scope_type === "book") {
    return appStore.books.map((item) => {
      const databaseId = item.database_id || appStore.activeDatabase?.database_id;
      return {
        value: databaseId ? `${databaseId}/${item.book_id}` : item.book_id,
        label: item.title || item.name || item.book_id,
      };
    });
  }
  if (dialog.value.form.scope_type === "session" && dialog.value.form.scope_id) {
    return [{ value: dialog.value.form.scope_id, label: t("当前会话") }];
  }
  return [];
});

function openProvider(provider = null) {
  dialog.value = {
    type: "provider",
    editingId: provider?.id || null,
    form: { ...providerDefaults(), ...(provider || {}), api_key: "" },
  };
}

function openProfile(providerId, profile = null) {
  dialog.value = { type: "profile", editingId: profile?.id || null, form: { ...profileDefaults(providerId), ...(profile || {}) } };
}

function openBinding(binding = null) {
  const form = { ...bindingDefaults(), ...(binding || {}) };
  if (!binding) form.id = `route_${Date.now()}`;
  dialog.value = { type: "binding", editingId: binding?.id || null, form };
}

function applyProviderPreset() {
  if (dialog.value?.type !== "provider" || dialog.value.editingId) return;
  Object.assign(dialog.value.form, PROVIDER_PRESETS[dialog.value.form.provider_type] || PROVIDER_PRESETS.custom);
}

function updateScope() {
  if (dialog.value?.type !== "binding") return;
  const form = dialog.value.form;
  if (form.scope_type === "global") form.scope_id = "";
  else if (form.scope_type === "database") form.scope_id = appStore.activeDatabase?.database_id || scopeOptions.value[0]?.value || "";
  else if (form.scope_type === "book") {
    const activeBook = appStore.activeBook;
    const databaseId = activeBook?.database_id || appStore.activeDatabase?.database_id;
    form.scope_id = activeBook
      ? (databaseId ? `${databaseId}/${activeBook.book_id}` : activeBook.book_id)
      : scopeOptions.value[0]?.value || "";
  }
}

function cleanOptional(value) {
  const trimmed = typeof value === "string" ? value.trim() : value;
  return trimmed === "" ? null : trimmed;
}

async function saveDialog() {
  const current = dialog.value;
  if (!current) return;
  try {
    if (current.type === "provider") {
      if (!advancedMode && !current.editingId) {
        await store.quickSetupProvider(current.form.base_url, current.form.api_key);
        dialog.value = null;
        return;
      }
      const form = Object.fromEntries([
        "id", "display_name", "provider_type", "base_url", "api_format", "credential_ref",
        "models_endpoint", "enabled", "supports_model_discovery",
      ].map((key) => [key, current.form[key]]));
      form.credential_ref = cleanOptional(form.credential_ref);
      form.models_endpoint = cleanOptional(form.models_endpoint);
      const providerId = current.editingId || form.id;
      const apiKey = current.form.api_key || "";
      if (apiKey) form.credential_ref = `secure:${providerId}`;
      if (current.editingId) delete form.id;
      await store.saveProvider(form, current.editingId);
      if (apiKey) await store.saveProviderCredential(providerId, apiKey);
    } else if (current.type === "profile") {
      const form = Object.fromEntries([
        "id", "provider_id", "provider_model_name", "display_name", "model_type", "enabled",
        "context_length", "max_output_tokens", "supports_streaming", "supports_tools",
        "supports_json_mode", "cost_level", "privacy_level",
      ].map((key) => [key, current.form[key]]));
      form.context_length = form.context_length ? Number(form.context_length) : null;
      form.max_output_tokens = form.max_output_tokens ? Number(form.max_output_tokens) : null;
      if (current.editingId) {
        delete form.id;
        delete form.provider_id;
      }
      await store.saveProfile(form, current.editingId);
    } else {
      const form = { ...current.form, priority: Number(current.form.priority || 0) };
      form.scope_id = current.form.scope_type === "global" ? null : cleanOptional(form.scope_id);
      if (current.editingId) {
        const update = { target_id: form.target_id, priority: form.priority, enabled: form.enabled };
        await store.saveBinding(update, current.editingId);
      } else {
        await store.saveBinding(form);
      }
    }
    dialog.value = null;
  } catch { /* store exposes the error */ }
}

async function toggleProvider(provider) {
  try { await store.saveProvider({ enabled: !provider.enabled }, provider.id); } catch { /* store exposes the error */ }
}

async function toggleProfile(profile) {
  try { await store.saveProfile({ enabled: !profile.enabled }, profile.id); } catch { /* store exposes the error */ }
}

async function toggleBinding(binding) {
  try { await store.saveBinding({ target_id: binding.target_id, priority: binding.priority, enabled: !binding.enabled }, binding.id); } catch { /* store exposes the error */ }
}

async function testProvider(providerId) {
  try { await store.testProvider(providerId); } catch { /* store exposes the error */ }
}

async function testProfile(profileId) {
  try { await store.testProfile(profileId); } catch { /* store exposes the error */ }
}

async function clearProviderCredential() {
  const current = dialog.value;
  if (current?.type !== "provider" || !current.editingId) return;
  try {
    await store.removeProviderCredential(current.editingId);
    current.form.credential_ref = "";
    current.form.api_key = "";
  } catch { /* store exposes the error */ }
}

async function selectAnalysisMode(mode) {
  try { await store.saveAnalysisPreference(mode); } catch { /* store exposes the error */ }
}

function askDelete(kind, item) {
  const labels = { provider: "供应商", profile: "模型配置", binding: "任务路由" };
  confirmAction.value = { kind, item, label: labels[kind] };
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString(locale.value);
}

async function confirmDelete() {
  const action = confirmAction.value;
  if (!action) return;
  try {
    if (action.kind === "provider") await store.removeProvider(action.item.id);
    if (action.kind === "profile") await store.removeProfile(action.item.id);
    if (action.kind === "binding") await store.removeBinding(action.item.id);
    confirmAction.value = null;
  } catch { /* store exposes the error */ }
}

onMounted(() => {
  store.loadAll();
  if (!appStore.databases.length && !appStore.books.length) appStore.fetchDashboard();
});
</script>

<template>
  <div class="ai-management">
    <section class="summary-grid">
      <article><Cloud :size="22" /><span>{{ t("模型供应商") }}</span><strong>{{ store.summary.enabled_provider_count }} / {{ store.summary.provider_count }}</strong></article>
      <article><Cpu :size="22" /><span>{{ t("可用模型") }}</span><strong>{{ store.summary.available_model_count }} / {{ store.summary.model_count }}</strong></article>
      <article><Route :size="22" /><span>{{ t("任务路由") }}</span><strong>{{ store.summary.enabled_binding_count }} / {{ store.summary.binding_count }}</strong></article>
      <article><Activity :size="22" /><span>{{ t("近 30 天调用") }}</span><strong>{{ formatNumber(store.summary.usage_calls_30d) }}</strong></article>
    </section>

    <HardwareAccelerationPanel />
    <VectorMaintenancePanel />

    <section class="analysis-preference">
      <div><strong>{{ t("实体分析方式") }}</strong><span>{{ t("本地规则可离线运行；云端模型用于提高识别准确性和跨段归纳能力。") }}</span></div>
      <div class="segmented-control" role="group" :aria-label="t('默认实体分析方式')">
        <button type="button" :class="{ active: store.analysisPreferences.default_mode === 'ask' }" @click="selectAnalysisMode('ask')">{{ t("首次询问") }}</button>
        <button type="button" :class="{ active: store.analysisPreferences.default_mode === 'local_rules' }" @click="selectAnalysisMode('local_rules')">{{ t("本地规则") }}</button>
        <button type="button" :class="{ active: store.analysisPreferences.default_mode === 'cloud_model' }" @click="selectAnalysisMode('cloud_model')">{{ t("云端模型") }}</button>
      </div>
      <small v-if="store.analysisPreferences.default_mode === 'cloud_model' && !store.analysisPreferences.cloud_model_available">{{ t("尚未配置可用云端模型；导入分析会明确报错，不会静默切换。") }}</small>
    </section>

    <div v-if="store.error" class="feedback error"><AlertTriangle :size="16" />{{ store.error }}</div>
    <div v-if="store.message" class="feedback success"><CheckCircle2 :size="16" />{{ store.message }}</div>

    <section class="management-section">
      <header class="management-heading">
        <div>
          <h2>{{ t("模型供应商") }}</h2>
          <p>{{ t("供应商负责连接方式与协议；具体模型和任务分工在其下独立配置。") }}</p>
        </div>
        <div class="heading-actions">
          <button class="btn btn-secondary" type="button" @click="showLocalDeploy = !showLocalDeploy">
            <Server :size="16" /> {{ t(showLocalDeploy ? "收起本地部署" : "高级设置 / 本地部署") }}
          </button>
          <button class="btn btn-primary" type="button" @click="openProvider()"><Plus :size="16" /> {{ t("新增供应商") }}</button>
        </div>
      </header>

      <LocalDeploymentPanel v-if="showLocalDeploy" class="local-panel" :provider-id="store.localProviders[0]?.id || null" />

      <div v-if="store.loading && !store.providers.length" class="loading-row"><RefreshCw :size="18" class="spinning" />{{ t("正在加载供应商...") }}</div>
      <div v-else-if="!store.providers.length" class="empty-state">
        <Cloud :size="28" />
        <strong>{{ t("尚未配置模型供应商") }}</strong>
        <small>{{ t("添加云端兼容接口，或在本地部署中连接已有 Ollama。") }}</small>
      </div>
      <div v-else class="provider-list">
        <article v-for="provider in store.providers" :key="provider.id" class="provider-card">
          <header>
            <div class="provider-icon" :class="{ local: provider.provider_type === 'ollama' }">
              <Server v-if="provider.provider_type === 'ollama'" :size="22" />
              <Cloud v-else :size="22" />
            </div>
            <div class="provider-copy">
              <div><strong>{{ provider.display_name }}</strong><span class="state-badge" :class="{ positive: provider.enabled }">{{ t(provider.enabled ? "已启用" : "已停用") }}</span></div>
              <small>{{ provider.provider_type }} · {{ provider.base_url }}</small>
            </div>
            <div class="row-actions">
              <span v-if="isSystemProvider(provider)" class="state-badge">{{ t("系统托管") }}</span>
              <template v-else>
                <button v-if="store.busyAction === `provider-test:${provider.id}`" class="btn btn-secondary compact" type="button" @click="store.cancelConnectionTest"><X :size="15" /> {{ t("取消") }}</button>
                <button v-else class="btn btn-secondary compact" type="button" @click="testProvider(provider.id)"><FlaskConical :size="15" /> {{ t("测试") }}</button>
                <button class="icon-button" type="button" :title="t('编辑供应商')" @click="openProvider(provider)"><Pencil :size="16" /></button>
                <button class="icon-button" type="button" :title="t(provider.enabled ? '停用供应商' : '启用供应商')" @click="toggleProvider(provider)"><Settings2 :size="16" /></button>
                <button class="icon-button danger" type="button" :title="t('删除供应商')" @click="askDelete('provider', provider)"><Trash2 :size="16" /></button>
              </template>
            </div>
          </header>

          <div class="profile-list">
            <article v-for="profile in store.profilesByProvider(provider.id)" :key="profile.id" class="profile-row">
              <Cpu :size="17" />
              <div>
                <strong>{{ profile.display_name }}</strong>
                <small>{{ profile.provider_model_name }} · {{ profile.model_type }}</small>
              </div>
              <span class="state-badge" :class="{ positive: profile.enabled && profile.health_status !== 'unhealthy' }">{{ profile.enabled ? t(profile.health_status || "可用") : t("已停用") }}</span>
              <template v-if="!isSystemProvider(provider)">
                <button v-if="store.busyAction === `profile-test:${profile.id}`" class="icon-button" type="button" :title="t('取消')" @click="store.cancelConnectionTest"><X :size="15" /></button>
                <button v-else class="icon-button" type="button" :title="t('测试模型')" @click="testProfile(profile.id)"><FlaskConical :size="15" /></button>
                <button class="icon-button" type="button" :title="t('编辑模型')" @click="openProfile(provider.id, profile)"><Pencil :size="15" /></button>
                <button class="icon-button" type="button" :title="t(profile.enabled ? '停用模型' : '启用模型')" @click="toggleProfile(profile)"><Settings2 :size="15" /></button>
                <button class="icon-button danger" type="button" :title="t('删除模型配置')" @click="askDelete('profile', profile)"><Trash2 :size="15" /></button>
              </template>
            </article>
            <button v-if="!isSystemProvider(provider)" class="add-profile" type="button" @click="openProfile(provider.id)"><Plus :size="15" /> {{ t("添加模型配置") }}</button>
          </div>
        </article>
      </div>
    </section>

    <section class="management-section">
      <header class="management-heading">
        <div><h2>{{ t("任务路由") }}</h2><p>{{ t("为每类任务指定一个主模型；世界或作品级配置可覆盖全局配置。") }}</p></div>
        <button class="btn btn-primary" type="button" :disabled="!availableProfiles.length" @click="openBinding()"><Plus :size="16" /> {{ t("新增路由") }}</button>
      </header>
      <div v-if="!store.bindings.length" class="empty-state compact-empty"><Route :size="25" /><strong>{{ t("尚未配置任务路由") }}</strong><small>{{ t("先添加可用模型，再为创作和检查任务分配主模型。") }}</small></div>
      <div v-else class="routing-table">
        <div class="routing-head"><span>{{ t("任务") }}</span><span>{{ t("作用范围") }}</span><span>{{ t("分配模型") }}</span><span>{{ t("优先级") }}</span><span>{{ t("状态") }}</span><span></span></div>
        <div v-for="binding in store.bindings" :key="binding.id" class="routing-row">
          <strong>{{ t(TASK_LABELS[binding.task_type] || binding.task_type) }}</strong>
          <span>{{ binding.scope_type === 'global' ? t('全局') : t("{scope} · {id}", { scope: binding.scope_type, id: binding.scope_id || t("未指定") }) }}</span>
          <span>{{ store.profiles.find((item) => item.id === binding.target_id)?.display_name || binding.target_id }}</span>
          <span>{{ binding.priority }}</span>
          <button class="text-toggle" :class="{ active: binding.enabled }" type="button" @click="toggleBinding(binding)">{{ t(binding.enabled ? "已启用" : "已停用") }}</button>
          <div class="row-actions">
            <button class="icon-button" type="button" :title="t('编辑任务路由')" @click="openBinding(binding)"><Pencil :size="15" /></button>
            <button class="icon-button danger" type="button" :title="t('删除任务路由')" @click="askDelete('binding', binding)"><Trash2 :size="15" /></button>
          </div>
        </div>
      </div>
    </section>

    <section v-if="latestTests.length" class="management-section test-history">
      <header class="management-heading"><div><h2>{{ t("最近连接测试") }}</h2><p>{{ t("用于判断配置和运行时是否可用，不展示密钥或完整响应内容。") }}</p></div></header>
      <div class="test-grid">
        <article v-for="test in latestTests" :key="test.id || `${test.created_at}-${test.provider_id}`">
          <CheckCircle2 v-if="isPassedTest(test)" :size="17" />
          <AlertTriangle v-else :size="17" />
          <div><strong>{{ test.model_profile_id || test.provider_id || t("模型连接") }}</strong><span>{{ test.created_at || t("刚刚") }}</span></div>
          <span>{{ t(isPassedTest(test) ? "通过" : "失败") }}</span>
        </article>
      </div>
    </section>

    <div v-if="dialog" class="dialog-backdrop" @click.self="dialog = null">
      <form class="dialog-card" :class="{ 'provider-dialog': dialog.type === 'provider' }" role="dialog" aria-modal="true" @submit.prevent="saveDialog">
        <header>
          <div>
            <h3 v-if="dialog.type === 'provider'">{{ t(dialog.editingId ? "编辑供应商" : "新增供应商") }}</h3>
            <h3 v-else-if="dialog.type === 'profile'">{{ t(dialog.editingId ? "编辑模型配置" : "新增模型配置") }}</h3>
            <h3 v-else>{{ t(dialog.editingId ? "编辑任务路由" : "新增任务路由") }}</h3>
            <p>{{ t("带技术含义的标识只在此管理表单中出现。") }}</p>
          </div>
          <button class="icon-button dialog-close" type="button" :title="t('关闭')" :aria-label="t('关闭')" @click="dialog = null"><X :size="18" /></button>
        </header>

        <div v-if="dialog.type === 'provider'" class="form-grid">
          <div class="field-row full"><label>{{ t("模型 API URL") }}</label><input v-model.trim="dialog.form.base_url" type="url" required maxlength="512" autocomplete="url" placeholder="https://api.deepseek.com" /></div>
          <div class="field-row full"><label>API Key</label><input v-model="dialog.form.api_key" type="password" autocomplete="new-password" maxlength="8192" :required="!dialog.editingId" :placeholder="t(dialog.form.credential_ref?.startsWith('secure:') ? '已保存；留空保持不变' : '粘贴云端供应商 API Key')" /><small>{{ t("系统会自动识别兼容协议、验证连接并发现模型；Key 由 Windows 加密保存在本机") }}</small></div>
          <div v-if="advancedMode" class="field-row"><label>{{ t("供应商 ID") }}</label><input v-model.trim="dialog.form.id" required pattern="[a-z0-9][a-z0-9._-]{1,63}" autocomplete="off" :placeholder="t('例如 deepseek-official')" :disabled="Boolean(dialog.editingId)" /><small>{{ t("仅使用小写字母、数字、点、下划线或连字符") }}</small></div>
          <div v-if="advancedMode" class="field-row"><label>{{ t("显示名称") }}</label><input v-model.trim="dialog.form.display_name" required maxlength="80" autocomplete="off" :placeholder="t('显示给用户的名称')" /></div>
          <div v-if="advancedMode" class="field-row"><label>{{ t("供应商类型") }}</label><select v-model="dialog.form.provider_type" @change="applyProviderPreset"><option value="openai_compatible">{{ t("OpenAI 兼容") }}</option><option value="deepseek">DeepSeek</option><option value="ollama">{{ t("Ollama 本地") }}</option><option value="custom">{{ t("自定义") }}</option></select></div>
          <div v-if="advancedMode" class="field-row"><label>{{ t("API 格式") }}</label><select v-model="dialog.form.api_format"><option value="openai_compatible">OpenAI</option><option value="ollama">Ollama</option><option value="custom">{{ t("自定义") }}</option></select></div>
          <div v-if="advancedMode" class="field-row"><label>{{ t("模型列表路径") }}</label><input v-model="dialog.form.models_endpoint" placeholder="/models" /></div>
          <button v-if="dialog.editingId && dialog.form.credential_ref?.startsWith('secure:')" class="btn btn-secondary compact" type="button" :disabled="Boolean(store.busyAction)" @click="clearProviderCredential"><Trash2 :size="15" />{{ t("清除已保存 Key") }}</button>
          <div v-if="advancedMode" class="field-row"><label>{{ t("环境变量引用") }}</label><input v-model.trim="dialog.form.credential_ref" autocomplete="off" pattern="(?:env|secure):[A-Za-z_][A-Za-z0-9_.-]{0,119}" placeholder="env:DEEPSEEK_API_KEY" /><small>{{ t("高级部署可使用环境变量；填写 API Key 时会自动改为本机安全引用") }}</small></div>
          <label class="check-row"><input v-model="dialog.form.enabled" type="checkbox" />{{ t("启用供应商") }}</label>
          <label class="check-row"><input v-model="dialog.form.supports_model_discovery" type="checkbox" />{{ t("支持模型发现") }}</label>
        </div>

        <div v-else-if="dialog.type === 'profile'" class="form-grid">
          <div class="field-row"><label>{{ t("模型配置 ID") }}</label><input v-model="dialog.form.id" required pattern="[a-z0-9][a-z0-9:._-]{1,127}" :disabled="Boolean(dialog.editingId)" /></div>
          <div class="field-row"><label>{{ t("显示名称") }}</label><input v-model="dialog.form.display_name" required maxlength="100" /></div>
          <div class="field-row full"><label>{{ t("供应商模型名称") }}</label><input v-model="dialog.form.provider_model_name" required maxlength="256" /></div>
          <div class="field-row"><label>{{ t("模型类型") }}</label><select v-model="dialog.form.model_type"><option value="chat">{{ t("对话 / 生成") }}</option><option value="embedding">{{ t("向量模型") }}</option><option value="vision">{{ t("视觉模型") }}</option><option value="image">{{ t("图像生成") }}</option></select></div>
          <div class="field-row"><label>{{ t("隐私级别") }}</label><select v-model="dialog.form.privacy_level"><option value="local_only">{{ t("仅本地") }}</option><option value="cloud_upload">{{ t("上传云端") }}</option><option value="hybrid">{{ t("混合") }}</option></select></div>
          <div class="field-row"><label>{{ t("上下文长度") }}</label><input v-model.number="dialog.form.context_length" type="number" min="1024" max="10000000" /></div>
          <div class="field-row"><label>{{ t("最大输出 Token") }}</label><input v-model.number="dialog.form.max_output_tokens" type="number" min="1" max="1000000" /></div>
          <div class="field-row"><label>{{ t("成本等级") }}</label><select v-model="dialog.form.cost_level"><option value="unknown">{{ t("未知") }}</option><option value="free">{{ t("免费") }}</option><option value="low">{{ t("低") }}</option><option value="medium">{{ t("中") }}</option><option value="high">{{ t("高") }}</option></select></div>
          <label class="check-row"><input v-model="dialog.form.enabled" type="checkbox" />{{ t("启用模型") }}</label>
          <label class="check-row"><input v-model="dialog.form.supports_streaming" type="checkbox" />{{ t("流式输出") }}</label>
          <label class="check-row"><input v-model="dialog.form.supports_json_mode" type="checkbox" />{{ t("JSON 模式") }}</label>
          <label class="check-row"><input v-model="dialog.form.supports_tools" type="checkbox" />{{ t("工具调用") }}</label>
        </div>

        <div v-else class="form-grid">
          <div v-if="advancedMode" class="field-row"><label>{{ t("路由 ID") }}</label><input v-model="dialog.form.id" required pattern="[a-z0-9][a-z0-9:._-]{1,127}" :disabled="Boolean(dialog.editingId)" /></div>
          <div class="field-row"><label>{{ t("任务类型") }}</label><select v-model="dialog.form.task_type" :disabled="Boolean(dialog.editingId)"><option v-for="(label,key) in TASK_LABELS" :key="key" :value="key">{{ t(label) }}</option></select></div>
          <div class="field-row"><label>{{ t("作用范围") }}</label><select v-model="dialog.form.scope_type" :disabled="Boolean(dialog.editingId)" @change="updateScope"><option value="global">{{ t("全部世界与作品") }}</option><option value="database">{{ t("指定世界库") }}</option><option value="book">{{ t("指定作品") }}</option><option v-if="dialog.editingId && dialog.form.scope_type === 'session'" value="session">{{ t("当前会话") }}</option></select></div>
          <div v-if="dialog.form.scope_type !== 'global'" class="field-row"><label>{{ t(dialog.form.scope_type === 'book' ? '选择作品' : '选择世界库') }}</label><select v-model="dialog.form.scope_id" required :disabled="Boolean(dialog.editingId)"><option disabled value="">{{ t("请选择") }}</option><option v-for="item in scopeOptions" :key="item.value" :value="item.value">{{ item.label }}{{ advancedMode ? ` · ${item.value}` : '' }}</option></select></div>
          <div class="field-row full"><label>{{ t("分配模型") }}</label><select v-model="dialog.form.target_id" required><option disabled value="">{{ t("选择模型") }}</option><option v-for="profile in availableProfiles" :key="profile.id" :value="profile.id">{{ profile.display_name }} · {{ profile.provider_model_name }}</option></select></div>
          <div class="field-row"><label>{{ t("优先级") }}</label><input v-model.number="dialog.form.priority" type="number" min="-1000" max="1000" /></div>
          <label class="check-row"><input v-model="dialog.form.enabled" type="checkbox" />{{ t("启用路由") }}</label>
        </div>

        <div class="dialog-actions">
          <button class="btn btn-secondary" type="button" @click="dialog = null">{{ t("取消") }}</button>
          <button class="btn btn-primary" type="submit" :disabled="Boolean(store.busyAction)">{{ t(store.busyAction ? "保存中..." : "保存") }}</button>
        </div>
      </form>
    </div>

    <div v-if="confirmAction" class="dialog-backdrop" @click.self="confirmAction = null">
      <section class="dialog-card confirm-card" role="dialog" aria-modal="true">
        <AlertTriangle :size="27" />
        <h3>{{ t("删除{type}", { type: t(confirmAction.label) }) }}</h3>
        <p>{{ t("将删除“{name}”。如果仍被其他配置引用，后端会拒绝此操作并保留数据。", { name: confirmAction.item.display_name || t(TASK_LABELS[confirmAction.item.task_type] || confirmAction.item.id) }) }}</p>
        <div class="dialog-actions"><button class="btn btn-secondary" type="button" @click="confirmAction = null">{{ t("取消") }}</button><button class="btn danger-button" type="button" @click="confirmDelete">{{ t("确认删除") }}</button></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.ai-management { display: grid; gap: 16px; }
.summary-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 10px; }
.summary-grid article { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 4px 10px; align-items: center; min-height: 72px; border: 1px solid var(--border); border-radius: 8px; background: #fff; padding: 12px; }
.summary-grid svg { grid-row: 1 / 3; color: var(--accent); }
.summary-grid span { color: var(--text-secondary); font-size: 11px; }
.summary-grid strong { font-size: 18px; }
.feedback { display: flex; align-items: center; gap: 8px; border-radius: 8px; padding: 10px 12px; font-size: 12px; }
.feedback.error { background: #fff0f0; color: #a33f3f; }
.feedback.success { background: #edfdf6; color: #167251; }
.analysis-preference { display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 12px; align-items: center; border: 1px solid var(--border); border-radius: 8px; background: #fff; padding: 14px 16px; }
.analysis-preference > div:first-child { display: grid; gap: 4px; }
.analysis-preference span, .analysis-preference small { color: var(--text-secondary); font-size: 11px; line-height: 1.5; }
.analysis-preference > small { grid-column: 1 / -1; color: #9a5b18; }
.segmented-control { display: inline-grid; grid-template-columns: repeat(3,auto); border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }
.segmented-control button { min-height: 34px; border: 0; border-right: 1px solid var(--border); background: #fff; color: var(--text-secondary); cursor: pointer; padding: 0 12px; font-size: 11px; }
.segmented-control button:last-child { border-right: 0; }
.segmented-control button.active { background: var(--accent-soft); color: var(--accent); }
.management-section { display: grid; gap: 14px; border: 1px solid var(--border); border-radius: 8px; background: rgba(255,255,255,.94); box-shadow: var(--soft-shadow); padding: 17px; }
.management-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.management-heading h2 { margin-bottom: 4px; font-size: 16px; }
.management-heading p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.heading-actions, .row-actions { display: flex; gap: 7px; align-items: center; flex-wrap: wrap; }
.local-panel { border: 1px solid #dcd5fb; border-radius: 8px; background: #fbfaff; padding: 15px; }
.provider-list, .profile-list { display: grid; gap: 9px; }
.provider-card { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.provider-card > header { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 11px; align-items: center; padding: 13px; }
.provider-icon { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 8px; background: #eff3ff; color: #586bc7; }
.provider-icon.local { background: #eaf8f2; color: #2f896d; }
.provider-copy { min-width: 0; display: grid; gap: 4px; }
.provider-copy > div { display: flex; gap: 8px; align-items: center; }
.provider-copy strong, .profile-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.provider-copy small, .profile-row small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-size: 11px; }
.profile-list { border-top: 1px solid var(--border); background: #faf9fc; padding: 9px 13px 13px 62px; }
.profile-row { display: grid; grid-template-columns: auto minmax(0,1fr) auto repeat(4,34px); gap: 8px; align-items: center; min-height: 44px; }
.profile-row > div { min-width: 0; display: grid; gap: 3px; }
.state-badge { border-radius: 999px; padding: 3px 8px; background: #f1eff5; color: var(--text-secondary); font-size: 10px; }
.state-badge.positive { background: #e9f8f1; color: #167251; }
.icon-button { width: 34px; height: 34px; display: inline-grid; place-items: center; border: 1px solid var(--border); border-radius: 7px; background: #fff; color: var(--text-secondary); cursor: pointer; }
.icon-button:hover { border-color: #cec4fb; color: var(--accent); }
.icon-button.danger { color: #b54545; }
.compact { min-height: 34px; padding: 6px 10px; font-size: 12px; }
.add-profile { min-height: 34px; display: flex; align-items: center; justify-content: center; gap: 6px; border: 1px dashed #cec8dc; border-radius: 7px; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: 12px; }
.add-profile:hover { border-color: var(--accent); color: var(--accent); }
.loading-row { min-height: 110px; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--text-secondary); font-size: 13px; }
.compact-empty { min-height: 130px; }
.routing-table { display: grid; overflow-x: auto; }
.routing-head, .routing-row { min-width: 760px; display: grid; grid-template-columns: 1.2fr .9fr 1.2fr 70px 80px 80px; gap: 10px; align-items: center; padding: 9px 10px; }
.routing-head { color: var(--text-muted); font-size: 11px; border-bottom: 1px solid var(--border); }
.routing-row { border-bottom: 1px solid #f0edf5; font-size: 12px; }
.routing-row:last-child { border-bottom: 0; }
.routing-row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
.text-toggle { border: 0; border-radius: 999px; background: #f0eef4; color: var(--text-secondary); cursor: pointer; padding: 4px 8px; font-size: 10px; }
.text-toggle.active { background: #e9f8f1; color: #167251; }
.test-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.test-grid article { display: grid; grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 8px; border-radius: 8px; background: var(--bg-secondary); padding: 10px; }
.test-grid article > div { display: grid; gap: 2px; min-width: 0; }
.test-grid strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.test-grid span { color: var(--text-secondary); font-size: 10px; }
.dialog-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(28,25,44,.44); }
.dialog-card { width: min(680px,100%); max-height: calc(100vh - 40px); overflow-y: auto; display: grid; gap: 17px; border-radius: 8px; background: #fff; box-shadow: 0 24px 70px rgba(28,25,44,.24); padding: 21px; }
.dialog-card.provider-dialog { width: min(920px,100%); gap: 24px; padding: 28px; }
.dialog-card > header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.dialog-card h3 { margin-bottom: 4px; font-size: 20px; }
.dialog-card p { color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 16px; }
.form-grid .full { grid-column: 1 / -1; }
.form-grid .field-row small { color: var(--text-muted); font-size: 10px; line-height: 1.45; }
.provider-dialog input, .provider-dialog select { min-height: 48px; }
.dialog-close { flex: 0 0 auto; }
.check-row { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 12px; }
.check-row input { width: auto; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.confirm-card { width: min(450px,100%); }
.confirm-card > svg { color: #b54545; }
.danger-button { background: #b54545; color: #fff; }
.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) {
  .summary-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
  .management-heading, .provider-card > header { grid-template-columns: 1fr; display: grid; }
  .profile-list { padding-left: 13px; }
  .profile-row { grid-template-columns: auto minmax(0,1fr) auto repeat(2,34px); }
  .profile-row .icon-button:nth-last-child(3), .profile-row .icon-button:nth-last-child(2) { display: none; }
}
@media (max-width: 620px) {
  .summary-grid, .test-grid, .form-grid { grid-template-columns: 1fr; }
  .analysis-preference { grid-template-columns: 1fr; }
  .segmented-control { grid-template-columns: repeat(3,minmax(0,1fr)); }
  .form-grid .full { grid-column: auto; }
  .heading-actions { width: 100%; }
  .heading-actions .btn { flex: 1; }
  .dialog-card.provider-dialog { gap: 17px; padding: 20px; }
}
</style>
