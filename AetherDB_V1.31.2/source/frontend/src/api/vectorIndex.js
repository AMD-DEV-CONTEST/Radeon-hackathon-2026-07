import { get, post } from "./client.js";


export const getVectorIndexStatus = (databaseId) => (
  get("/vector-index/status", { database_id: databaseId })
);

export const getHardwareAccelerationStatus = () => get("/vector-index/runtime-status");

export const rebuildVectorIndex = (databaseId, bookId = null) => (
  post(`/vector-index/rebuild?database_id=${encodeURIComponent(databaseId)}${bookId ? `&book_id=${encodeURIComponent(bookId)}` : ""}`, {})
);

export const createVectorTask = (payload) => post("/vector-index/tasks", payload);
export const listVectorTasks = (params = {}) => get("/vector-index/tasks", params);
export const getVectorTask = (taskId) => get(`/vector-index/tasks/${taskId}`);
export const cancelVectorTask = (taskId) => post(`/vector-index/tasks/${taskId}/cancel`, {});
export const retryFailedVectorItems = (taskId) => (
  post(`/vector-index/tasks/${taskId}/retry-failed`, {})
);
