import { get, post } from "./client.js";


export function importPreview(text, config) {
  return post("/import/preview", { text, extractor_config: config });
}

export function importConfirm(entities, relations) {
  return post("/import/confirm", { entities, relations });
}

export const createImportTask = (payload) => post("/import/tasks", payload);
export const listImportTasks = (limit = 50) => get("/import/tasks", { limit });
export const getImportTask = (taskId) => get(`/import/tasks/${taskId}`);
export const getImportTaskPreview = (taskId) => get(`/import/tasks/${taskId}/preview`);
export const cancelImportTask = (taskId) => post(`/import/tasks/${taskId}/cancel`, {});
export const retryImportTask = (taskId) => post(`/import/tasks/${taskId}/retry`, {});
export const confirmImportTask = (taskId, payload) => post(`/import/tasks/${taskId}/confirm`, payload);
export const analyzeImportTask = (taskId, analysisMode = null) => post(
  `/import/tasks/${taskId}/analyze`,
  analysisMode ? { analysis_mode: analysisMode } : {},
);
