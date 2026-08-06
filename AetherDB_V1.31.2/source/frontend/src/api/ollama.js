import { get, post } from "./client.js";


export const getOllamaStatus = (providerId = null) => (
  get("/ollama/status", { provider_id: providerId })
);

export const reconnectOllama = (providerId = null) => (
  post("/ollama/reconnect", { provider_id: providerId })
);

export const startOllama = (providerId = null) => (
  post("/ollama/start", { provider_id: providerId })
);

export const stopOllama = (providerId = null) => (
  post("/ollama/stop", { provider_id: providerId })
);

export const listOllamaObservations = (providerId = null) => (
  get("/ollama/observations", { provider_id: providerId })
);

export const listOllamaExecutions = (status = null, limit = 100) => (
  get("/ollama/executions", { status, limit })
);

export const getOllamaExecution = (executionId) => (
  get(`/ollama/executions/${encodeURIComponent(executionId)}`)
);

export const cancelOllamaExecution = (executionId) => (
  post(`/ollama/executions/${encodeURIComponent(executionId)}/cancel`, {})
);

export const getOllamaInstallPlan = (accelerator = null) => (
  get("/ollama/install/plan", { accelerator })
);

export const createOllamaInstallOperation = (accelerator = null) => (
  post("/ollama/install/operations", { accelerator })
);

export const listOllamaInstallOperations = (limit = 20) => (
  get("/ollama/install/operations", { limit })
);

export const getOllamaInstallOperation = (operationId) => (
  get(`/ollama/install/operations/${operationId}`)
);

export const confirmOllamaInstallDownload = (operationId) => (
  post(`/ollama/install/operations/${operationId}/confirm-download`, {})
);

export const cancelOllamaInstallOperation = (operationId) => (
  post(`/ollama/install/operations/${operationId}/cancel`, {})
);

export const launchOllamaInstaller = (operationId, confirmVersion) => (
  post(`/ollama/install/operations/${operationId}/launch`, { confirm_version: confirmVersion })
);

export const listOllamaModels = (providerId = null) => (
  get("/ollama/models", { provider_id: providerId })
);

export const pullOllamaModel = (model, providerId = null) => (
  post("/ollama/models/pull", { model, provider_id: providerId })
);

export const syncOllamaModels = (providerId) => (
  post("/ollama/models/sync", { provider_id: providerId })
);

export const loadOllamaModel = (model, providerId = null) => (
  post("/ollama/models/load", { model, provider_id: providerId })
);

export const unloadOllamaModel = (model, providerId = null) => (
  post("/ollama/models/unload", { model, provider_id: providerId })
);

export const deleteOllamaModel = (model, confirmModel, providerId = null) => (
  post("/ollama/models/delete", { model, confirm_model: confirmModel, provider_id: providerId })
);

export const listOllamaOperations = (limit = 20) => get("/ollama/operations", { limit });
export const getOllamaOperation = (operationId) => get(`/ollama/operations/${operationId}`);
export const retryOllamaOperation = (operationId) => post(`/ollama/operations/${operationId}/retry`, {});
export const cancelOllamaOperation = (operationId) => post(`/ollama/operations/${operationId}/cancel`, {});
