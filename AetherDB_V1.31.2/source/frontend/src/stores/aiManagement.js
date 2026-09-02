import { defineStore } from "pinia";
import {
  createModelBinding,
  createModelProfile,
  createModelProvider,
  deleteModelBinding,
  deleteModelProfile,
  deleteModelProvider,
  deleteModelProviderCredential,
  getAnalysisPreferences,
  getModelManagementOverview,
  listModelBindings,
  listModelProfiles,
  listModelProviders,
  listModelTests,
  quickSetupCloudProvider,
  saveModelProviderCredential,
  testModelProfile,
  testModelProvider,
  updateModelBinding,
  updateModelProfile,
  updateModelProvider,
  updateAnalysisPreferences,
} from "../api/models.js";
import {
  cancelOllamaInstallOperation,
  cancelOllamaExecution,
  cancelOllamaOperation,
  confirmOllamaInstallDownload,
  createOllamaInstallOperation,
  deleteOllamaModel,
  getOllamaInstallOperation,
  getOllamaInstallPlan,
  getOllamaOperation,
  getOllamaStatus,
  launchOllamaInstaller,
  listOllamaInstallOperations,
  listOllamaExecutions,
  listOllamaObservations,
  listOllamaOperations,
  loadOllamaModel,
  pullOllamaModel,
  reconnectOllama,
  retryOllamaOperation,
  startOllama,
  stopOllama,
  unloadOllamaModel,
} from "../api/ollama.js";
import {
  getModelRuntimeResources,
  listModelRuntimeDrift,
  reconcileModelRuntimeDrift,
} from "../api/modelRuntime.js";
import { getHardwareAccelerationStatus } from "../api/vectorIndex.js";
import { translate } from "../i18n/index.js";

const TERMINAL_OPERATIONS = new Set(["completed", "failed", "cancelled"]);
const TERMINAL_INSTALL_OPERATIONS = new Set(["ready", "failed", "cancelled"]);
let connectionTestController = null;

function errorMessage(error, fallback) {
  if (error?.status === 401 || error?.status === 403) return translate("管理员凭据无效或尚未配置");
  if (
    error?.status >= 500
    || ["BACKEND_UNAVAILABLE", "BACKEND_START_FAILED", "BACKEND_PORT_IN_USE", "BACKEND_TIMEOUT"].includes(error?.code)
  ) return error?.message || translate("本地 AI 管理服务暂不可用");
  return error?.detail?.message || error?.message || translate(fallback);
}

export const useAiManagementStore = defineStore("aiManagement", {
  state: () => ({
    overview: null,
    providers: [],
    profiles: [],
    bindings: [],
    tests: [],
    ollama: null,
    ollamaObservations: { runtimes: [], models: [] },
    ollamaExecutions: [],
    modelRuntimeResources: null,
    modelRuntimeDrift: [],
    operations: [],
    installPlan: null,
    installOperation: null,
    hardwareAcceleration: null,
    analysisPreferences: {
      default_mode: "ask",
      available_modes: ["local_rules", "cloud_model"],
      local_rules_available: true,
      cloud_model_available: false,
    },
    hardwareLoading: false,
    hardwareError: "",
    loading: false,
    ollamaLoading: false,
    busyAction: "",
    error: "",
    ollamaError: "",
    message: "",
    lastLoadedAt: null,
    pollTimer: null,
    installPollTimer: null,
  }),
  getters: {
    summary: (state) => state.overview?.summary || {
      provider_count: state.providers.length,
      enabled_provider_count: state.providers.filter((item) => item.enabled).length,
      model_count: state.profiles.length,
      available_model_count: state.profiles.filter((item) => item.enabled).length,
      binding_count: state.bindings.length,
      enabled_binding_count: state.bindings.filter((item) => item.enabled).length,
      usage_calls_30d: 0,
    },
    profilesByProvider: (state) => (providerId) => state.profiles.filter((item) => item.provider_id === providerId),
    localProviders: (state) => state.providers.filter((item) => (
      item.provider_type === "ollama" || /localhost|127\.0\.0\.1/.test(item.base_url || "")
    )),
  },
  actions: {
    notify(message) {
      this.message = message;
      window.clearTimeout(this._messageTimer);
      this._messageTimer = window.setTimeout(() => { this.message = ""; }, 2600);
    },
    async loadAll() {
      this.loading = true;
      this.error = "";
      const tasks = await Promise.allSettled([
        getModelManagementOverview(),
        listModelProviders(),
        listModelProfiles(),
        listModelBindings(),
        listModelTests({ limit: 20 }),
        getAnalysisPreferences(),
      ]);
      const [overview, providers, profiles, bindings, tests, analysisPreferences] = tasks;
      if (overview.status === "fulfilled") this.overview = overview.value;
      if (providers.status === "fulfilled") this.providers = providers.value?.providers || [];
      if (profiles.status === "fulfilled") this.profiles = profiles.value?.model_profiles || [];
      if (bindings.status === "fulfilled") this.bindings = bindings.value?.bindings || [];
      if (tests.status === "fulfilled") this.tests = tests.value?.tests || [];
      if (analysisPreferences.status === "fulfilled") this.analysisPreferences = analysisPreferences.value;
      if (tasks.every((task) => task.status === "rejected")) {
        this.error = errorMessage(tasks[0].reason, "无法加载 AI 管理数据");
      }
      this.lastLoadedAt = new Date();
      this.loading = false;
      await Promise.all([this.refreshOllama(), this.refreshHardwareAcceleration()]);
    },
    async runAction(key, action, successMessage, { refresh = true } = {}) {
      this.busyAction = key;
      this.error = "";
      try {
        const result = await action();
        if (refresh) await this.loadRegistry();
        if (successMessage) this.notify(successMessage);
        return result;
      } catch (error) {
        this.error = errorMessage(error, "操作失败");
        throw error;
      } finally {
        this.busyAction = "";
      }
    },
    async loadRegistry() {
      const tasks = await Promise.allSettled([
        getModelManagementOverview(), listModelProviders(), listModelProfiles(), listModelBindings(), listModelTests({ limit: 20 }), getAnalysisPreferences(),
      ]);
      if (tasks[0].status === "fulfilled") this.overview = tasks[0].value;
      if (tasks[1].status === "fulfilled") this.providers = tasks[1].value?.providers || [];
      if (tasks[2].status === "fulfilled") this.profiles = tasks[2].value?.model_profiles || [];
      if (tasks[3].status === "fulfilled") this.bindings = tasks[3].value?.bindings || [];
      if (tasks[4].status === "fulfilled") this.tests = tasks[4].value?.tests || [];
      if (tasks[5].status === "fulfilled") this.analysisPreferences = tasks[5].value;
    },
    async refreshHardwareAcceleration() {
      this.hardwareLoading = true;
      this.hardwareError = "";
      try {
        this.hardwareAcceleration = await getHardwareAccelerationStatus();
      } catch (error) {
        this.hardwareAcceleration = null;
        this.hardwareError = errorMessage(error, "无法读取硬件加速状态");
      } finally {
        this.hardwareLoading = false;
      }
    },
    saveProvider(payload, editingId = null) {
      return this.runAction(
        `provider:${editingId || payload.id}`,
        () => editingId ? updateModelProvider(editingId, payload) : createModelProvider(payload),
        translate(editingId ? "供应商配置已更新" : "供应商已添加"),
      );
    },
    quickSetupProvider(baseUrl, apiKey) {
      return this.runAction(
        "provider-quick-setup",
        () => quickSetupCloudProvider(baseUrl, apiKey),
        translate("云端模型已连接并完成配置"),
      );
    },
    saveAnalysisPreference(defaultMode) {
      return this.runAction(
        "analysis-preference",
        async () => {
          const result = await updateAnalysisPreferences(defaultMode);
          this.analysisPreferences = { ...this.analysisPreferences, ...result };
          return result;
        },
        translate("实体分析方式已更新"),
        { refresh: false },
      );
    },
    removeProvider(providerId) {
      return this.runAction(`provider:${providerId}`, () => deleteModelProvider(providerId), translate("供应商已删除"));
    },
    saveProviderCredential(providerId, apiKey) {
      return this.runAction(
        `provider-credential:${providerId}`,
        () => saveModelProviderCredential(providerId, apiKey),
        translate("API Key 已加密保存到本机"),
      );
    },
    removeProviderCredential(providerId) {
      return this.runAction(
        `provider-credential:${providerId}`,
        () => deleteModelProviderCredential(providerId),
        translate("已清除本机 API Key"),
      );
    },
    testProvider(providerId) {
      this.cancelConnectionTest();
      const controller = new AbortController();
      connectionTestController = controller;
      return this.runAction(
        `provider-test:${providerId}`,
        () => testModelProvider(providerId, { signal: controller.signal }),
        translate("连接测试已完成"),
      ).finally(() => {
        if (connectionTestController === controller) connectionTestController = null;
      });
    },
    saveProfile(payload, editingId = null) {
      return this.runAction(
        `profile:${editingId || payload.id}`,
        () => editingId ? updateModelProfile(editingId, payload) : createModelProfile(payload),
        translate(editingId ? "模型配置已更新" : "模型配置已添加"),
      );
    },
    removeProfile(profileId) {
      return this.runAction(`profile:${profileId}`, () => deleteModelProfile(profileId), translate("模型配置已删除"));
    },
    testProfile(profileId) {
      this.cancelConnectionTest();
      const controller = new AbortController();
      connectionTestController = controller;
      return this.runAction(
        `profile-test:${profileId}`,
        () => testModelProfile(profileId, { signal: controller.signal }),
        translate("模型测试已完成"),
      ).finally(() => {
        if (connectionTestController === controller) connectionTestController = null;
      });
    },
    cancelConnectionTest() {
      connectionTestController?.abort();
      connectionTestController = null;
    },
    saveBinding(payload, editingId = null) {
      return this.runAction(
        `binding:${editingId || payload.id}`,
        () => editingId ? updateModelBinding(editingId, payload) : createModelBinding(payload),
        translate(editingId ? "任务路由已更新" : "任务路由已添加"),
      );
    },
    removeBinding(bindingId) {
      return this.runAction(`binding:${bindingId}`, () => deleteModelBinding(bindingId), translate("任务路由已删除"));
    },
    async refreshOllama(providerId = null) {
      this.ollamaLoading = true;
      this.ollamaError = "";
      const [status, operations, installs, observations, executions, resources, drift] = await Promise.allSettled([
        getOllamaStatus(providerId),
        listOllamaOperations(20),
        listOllamaInstallOperations(10),
        listOllamaObservations(providerId),
        listOllamaExecutions(null, 50),
        getModelRuntimeResources(),
        listModelRuntimeDrift(true),
      ]);
      if (status.status === "fulfilled") this.ollama = status.value;
      else {
        this.ollama = null;
        this.ollamaError = errorMessage(status.reason, "无法读取 Ollama 状态");
      }
      if (operations.status === "fulfilled") this.operations = operations.value?.operations || [];
      if (installs.status === "fulfilled" && !this.installOperation) {
        this.installOperation = installs.value?.operations?.[0] || null;
      }
      if (observations.status === "fulfilled") {
        this.ollamaObservations = observations.value || { runtimes: [], models: [] };
      }
      if (executions.status === "fulfilled") {
        this.ollamaExecutions = executions.value?.executions || [];
      }
      if (resources.status === "fulfilled") this.modelRuntimeResources = resources.value;
      if (drift.status === "fulfilled") this.modelRuntimeDrift = drift.value?.items || [];
      this.ollamaLoading = false;
    },
    async installAction(key, action) {
      this.busyAction = `ollama-install:${key}`;
      this.ollamaError = "";
      try {
        const result = await action();
        if (result?.operation) this.installOperation = result.operation;
        return result;
      } catch (error) {
        this.ollamaError = errorMessage(error, "Ollama 安装操作失败");
        throw error;
      } finally {
        this.busyAction = "";
      }
    },
    async prepareOllamaInstall(accelerator = null) {
      return this.installAction("prepare", async () => {
        const plan = await getOllamaInstallPlan(accelerator);
        this.installPlan = plan?.plan || null;
        const operation = await createOllamaInstallOperation(accelerator);
        this.installOperation = operation?.operation || null;
        return operation;
      });
    },
    async confirmOllamaInstallDownload(operationId) {
      const response = await this.installAction(
        "download",
        () => confirmOllamaInstallDownload(operationId),
      );
      this.startInstallPolling(operationId);
      return response;
    },
    async cancelOllamaInstall(operationId) {
      const response = await this.installAction(
        "cancel",
        () => cancelOllamaInstallOperation(operationId),
      );
      this.stopInstallPolling();
      return response;
    },
    async launchOllamaInstall(operationId, version) {
      const response = await this.installAction(
        "launch",
        () => launchOllamaInstaller(operationId, version),
      );
      this.startInstallPolling(operationId);
      return response;
    },
    startInstallPolling(operationId) {
      this.stopInstallPolling();
      const poll = async () => {
        try {
          const response = await getOllamaInstallOperation(operationId);
          this.installOperation = response?.operation || null;
          if (!this.installOperation || TERMINAL_INSTALL_OPERATIONS.has(this.installOperation.status)) {
            this.stopInstallPolling();
            await this.refreshOllama();
            await this.loadRegistry();
          }
        } catch (error) {
          this.ollamaError = errorMessage(error, "无法刷新 Ollama 安装进度");
          this.stopInstallPolling();
        }
      };
      poll();
      this.installPollTimer = window.setInterval(poll, 1600);
    },
    stopInstallPolling() {
      if (this.installPollTimer) window.clearInterval(this.installPollTimer);
      this.installPollTimer = null;
    },
    async ollamaAction(key, action, successMessage, providerId = null) {
      this.busyAction = `ollama:${key}`;
      this.ollamaError = "";
      try {
        const result = await action();
        if (successMessage) this.notify(successMessage);
        await this.refreshOllama(providerId);
        return result;
      } catch (error) {
        this.ollamaError = errorMessage(error, "Ollama 操作失败");
        throw error;
      } finally {
        this.busyAction = "";
      }
    },
    startRuntime(providerId = null) {
      return this.ollamaAction("start", () => startOllama(providerId), translate("Ollama 已启动"), providerId);
    },
    stopRuntime(providerId = null) {
      return this.ollamaAction("stop", () => stopOllama(providerId), translate("AetherDB 管理的 Ollama 已停止"), providerId);
    },
    reconnectRuntime(providerId = null) {
      return this.ollamaAction("reconnect", () => reconnectOllama(providerId), translate("运行时状态已刷新"), providerId);
    },
    async pullModel(model, providerId = null) {
      const response = await this.ollamaAction("pull", () => pullOllamaModel(model, providerId), translate("模型下载任务已创建"), providerId);
      const operation = response?.operation;
      if (operation?.id) this.startOperationPolling(operation.id, providerId);
      return response;
    },
    loadModel(model, providerId = null) {
      return this.ollamaAction(`load:${model}`, () => loadOllamaModel(model, providerId), translate("模型已加载"), providerId);
    },
    unloadModel(model, providerId = null) {
      return this.ollamaAction(`unload:${model}`, () => unloadOllamaModel(model, providerId), translate("模型已卸载"), providerId);
    },
    deleteModel(model, confirmModel, providerId = null) {
      return this.ollamaAction(`delete:${model}`, () => deleteOllamaModel(model, confirmModel, providerId), translate("模型文件已删除"), providerId);
    },
    cancelExecution(executionId, providerId = null) {
      return this.ollamaAction(
        `execution:${executionId}`,
        () => cancelOllamaExecution(executionId),
        translate("已请求取消 AetherDB 模型任务"),
        providerId,
      );
    },
    async reconcileRuntimeDrift(providerId = null) {
      return this.ollamaAction(
        "drift",
        () => reconcileModelRuntimeDrift(),
        translate("已清理本项目失效租约并重新计算外部占用"),
        providerId,
      );
    },
    async retryOperation(operationId, providerId = null) {
      const response = await this.ollamaAction(`retry:${operationId}`, () => retryOllamaOperation(operationId), translate("已重新创建下载任务"), providerId);
      if (response?.operation?.id) this.startOperationPolling(response.operation.id, providerId);
    },
    async cancelOperation(operationId, providerId = null) {
      const response = await this.ollamaAction(
        `cancel:${operationId}`,
        () => cancelOllamaOperation(operationId),
        translate("模型下载已取消"),
        providerId,
      );
      this.stopOperationPolling();
      return response;
    },
    startOperationPolling(operationId, providerId = null) {
      this.stopOperationPolling();
      const poll = async () => {
        try {
          const response = await getOllamaOperation(operationId);
          const operation = response?.operation;
          const index = this.operations.findIndex((item) => item.id === operation?.id);
          if (operation && index >= 0) this.operations[index] = operation;
          else if (operation) this.operations.unshift(operation);
          if (!operation || TERMINAL_OPERATIONS.has(operation.status)) {
            this.stopOperationPolling();
            await this.refreshOllama(providerId);
          }
        } catch (error) {
          this.ollamaError = errorMessage(error, "无法刷新下载进度");
          this.stopOperationPolling();
        }
      };
      poll();
      this.pollTimer = window.setInterval(poll, 1600);
    },
    stopOperationPolling() {
      if (this.pollTimer) window.clearInterval(this.pollTimer);
      this.pollTimer = null;
    },
  },
});
