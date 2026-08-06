import {
  ApiError,
  apiErrorMessage,
  del,
  get,
  normalizeApiErrorCode,
  post,
  put,
  streamNdjson,
} from "./client.js";

const MODEL_TEST_OPTIONS = { timeoutMs: 30_000, timeoutCode: "MODEL_REQUEST_TIMEOUT" };

function requireSuccessfulDiagnostic(result) {
  if (result?.status !== "failed") return result;
  const code = normalizeApiErrorCode(result?.error?.code);
  throw new ApiError(apiErrorMessage(code), {
    code,
    detail: result?.error || null,
  });
}

export const listModelProviders = () => get("/model-providers");
export const getModelProvider = (providerId) => get(`/model-providers/${providerId}`);
export const createModelProvider = (payload) => post("/model-providers", payload);
export const quickSetupCloudProvider = (baseUrl, apiKey) => post(
  "/model-providers/quick-setup",
  { base_url: baseUrl, api_key: apiKey },
  MODEL_TEST_OPTIONS,
);
export const updateModelProvider = (providerId, payload) => put(`/model-providers/${providerId}`, payload);
export const saveModelProviderCredential = (providerId, apiKey) => put(`/model-providers/${providerId}/credential`, { api_key: apiKey });
export const deleteModelProviderCredential = (providerId) => del(`/model-providers/${providerId}/credential`);
export const deleteModelProvider = (providerId) => del(`/model-providers/${providerId}`);
export const testModelProvider = async (providerId, { signal } = {}) => requireSuccessfulDiagnostic(
  await post(`/model-providers/${providerId}/test-connection`, {}, { ...MODEL_TEST_OPTIONS, signal }),
);
export const getModelManagementOverview = () => get("/ai-management/overview");
export const getAnalysisPreferences = () => get("/ai/analysis-preferences");
export const updateAnalysisPreferences = (defaultMode) => put("/ai/analysis-preferences", { default_mode: defaultMode });

export const listModelProfiles = (providerId = null) => get("/model-profiles", { provider_id: providerId });
export const getModelProfile = (profileId) => get(`/model-profiles/${profileId}`);
export const createModelProfile = (payload) => post("/model-profiles", payload);
export const updateModelProfile = (profileId, payload) => put(`/model-profiles/${profileId}`, payload);
export const deleteModelProfile = (profileId) => del(`/model-profiles/${profileId}`);
export const testModelProfile = async (profileId, { signal } = {}) => requireSuccessfulDiagnostic(
  await post(`/model-profiles/${profileId}/test`, {}, { ...MODEL_TEST_OPTIONS, signal }),
);
export const listModelTests = (params = {}) => get("/model-tests", params);

export const listModelBindings = (params = {}) => get("/model-routing/bindings", params);
export const createModelBinding = (payload) => post("/model-routing/bindings", payload);
export const updateModelBinding = (bindingId, payload) => put(`/model-routing/bindings/${bindingId}`, payload);
export const deleteModelBinding = (bindingId) => del(`/model-routing/bindings/${bindingId}`);

export const executeModelStream = (payload, options = {}) => (
  streamNdjson("/model-routing/execute-stream", payload, options)
);
export const createModelDataManifest = (payload) => (
  post("/model-routing/data-manifests", payload)
);
export const getModelDataManifest = (dataManifestId) => (
  get(`/model-routing/data-manifests/${encodeURIComponent(dataManifestId)}`)
);
export const confirmModelDataManifest = (dataManifestId) => (
  post(
    `/model-routing/data-manifests/${encodeURIComponent(dataManifestId)}/confirm`,
    {},
  )
);
export const confirmModelRecovery = (ticketId, modelProfileId) => (
  post(`/model-routing/recovery/${ticketId}/confirm`, { model_profile_id: modelProfileId })
);
