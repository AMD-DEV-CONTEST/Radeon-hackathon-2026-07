import { buildQuery, get, post } from "./client.js";


export const createContextMap = (payload) => post("/context/map", payload);
export const listContextTasks = (params) => get("/context/tasks", params);
export const getContextCandidates = (taskId, databaseId) => (
  get(`/context/tasks/${taskId}/candidates`, { database_id: databaseId })
);
export const approveContextCandidates = (taskId, databaseId, items) => (
  post(`/context/tasks/${taskId}/approval${buildQuery({ database_id: databaseId })}`, { items })
);
export const buildEvidencePack = (taskId, databaseId, budget, mediaBudget) => (
  post(`/context/tasks/${taskId}/evidence-pack${buildQuery({ database_id: databaseId })}`, {
    budget,
    ...(mediaBudget ? { media_budget: mediaBudget } : {}),
  })
);
