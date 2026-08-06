import { buildQuery, get, post, streamNdjson } from "./client.js";


export const getMediaGenerationStatus = () => get("/media-generation/status");

export const createMediaGenerationTask = (payload) => (
  post("/media-generation/tasks", payload)
);

export const listMediaGenerationTasks = (params) => (
  get("/media-generation/tasks", params)
);

export const getMediaGenerationTask = (taskId, databaseId) => (
  get(`/media-generation/tasks/${encodeURIComponent(taskId)}`, {
    database_id: databaseId,
  })
);

export const publishMediaGenerationTask = (taskId, databaseId, payload) => (
  post(
    `/media-generation/tasks/${encodeURIComponent(taskId)}/publish${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  )
);

export const listMediaGenerationEvents = (
  taskId,
  databaseId,
  afterSequence = -1,
) => (
  get(`/media-generation/tasks/${encodeURIComponent(taskId)}/events`, {
    database_id: databaseId,
    after_sequence: afterSequence,
  })
);

export const streamMediaGenerationTask = (
  taskId,
  databaseId,
  options = {},
) => (
  streamNdjson(
    `/media-generation/tasks/${encodeURIComponent(taskId)}/stream${buildQuery({
      database_id: databaseId,
    })}`,
    {},
    options,
  )
);

export const cancelMediaGenerationTask = (taskId, databaseId) => (
  post(
    `/media-generation/tasks/${encodeURIComponent(taskId)}/cancel${buildQuery({
      database_id: databaseId,
    })}`,
    {},
  )
);

export const retryMediaGenerationTask = (taskId, databaseId) => (
  post(
    `/media-generation/tasks/${encodeURIComponent(taskId)}/retry${buildQuery({
      database_id: databaseId,
    })}`,
    {},
  )
);
