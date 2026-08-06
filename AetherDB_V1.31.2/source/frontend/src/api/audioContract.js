import { buildQuery, del, get, patch, post } from "./client.js";


export const getAudioContractStatus = () => get("/audio/status");

export const createVoiceProfile = (payload) => (
  post("/audio/voice-profiles", payload)
);

export const listVoiceProfiles = (params) => (
  get("/audio/voice-profiles", params)
);

export const getVoiceProfile = (voiceProfileId, databaseId) => (
  get(`/audio/voice-profiles/${encodeURIComponent(voiceProfileId)}`, {
    database_id: databaseId,
  })
);

export const updateVoiceProfile = (voiceProfileId, databaseId, payload) => (
  patch(
    `/audio/voice-profiles/${encodeURIComponent(voiceProfileId)}${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  )
);

export const createPronunciationEntry = (payload) => (
  post("/audio/pronunciations", payload)
);

export const listPronunciationEntries = (params) => (
  get("/audio/pronunciations", params)
);

export const updatePronunciationEntry = (entryId, databaseId, payload) => (
  patch(
    `/audio/pronunciations/${encodeURIComponent(entryId)}${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  )
);

export const deletePronunciationEntry = (entryId, databaseId) => (
  del(
    `/audio/pronunciations/${encodeURIComponent(entryId)}${buildQuery({
      database_id: databaseId,
    })}`,
  )
);

export const getAudioAsset = (assetId, databaseId) => (
  get(`/audio/assets/${encodeURIComponent(assetId)}`, {
    database_id: databaseId,
  })
);

export const getAudioWaveform = (assetId, databaseId, points = 512) => (
  get(`/audio/assets/${encodeURIComponent(assetId)}/waveform`, {
    database_id: databaseId,
    points,
  })
);

export const createAudioTask = (payload) => (
  post("/audio/tasks", payload)
);

export const listAudioTasks = (params) => (
  get("/audio/tasks", params)
);

export const getAudioTask = (
  taskId,
  databaseId,
  { includeSourceText = false, includeResultText = false } = {},
) => (
  get(`/audio/tasks/${encodeURIComponent(taskId)}`, {
    database_id: databaseId,
    include_source_text: includeSourceText || undefined,
    include_result_text: includeResultText || undefined,
  })
);

export const cancelAudioTask = (taskId, databaseId) => (
  post(
    `/audio/tasks/${encodeURIComponent(taskId)}/cancel${buildQuery({
      database_id: databaseId,
    })}`,
    {},
  )
);

export const listAudioTaskEvents = (taskId, databaseId, limit = 200) => (
  get(`/audio/tasks/${encodeURIComponent(taskId)}/events`, {
    database_id: databaseId,
    limit,
  })
);

export const retryAudioTask = (taskId, databaseId) => (
  post(
    `/audio/tasks/${encodeURIComponent(taskId)}/retry${buildQuery({
      database_id: databaseId,
    })}`,
    {},
  )
);

export const publishAudioTask = (taskId, databaseId, payload = {}) => (
  post(
    `/audio/tasks/${encodeURIComponent(taskId)}/publish${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  )
);

export const registerAudioOutput = (taskId, databaseId, payload) => (
  post(
    `/audio/tasks/${encodeURIComponent(taskId)}/outputs${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  )
);

export const registerAudioResult = (taskId, databaseId, payload) => (
  post(
    `/audio/tasks/${encodeURIComponent(taskId)}/results${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  )
);

export const reviewAudioResult = (resultId, databaseId, approved) => (
  post(
    `/audio/results/${encodeURIComponent(resultId)}/review${buildQuery({
      database_id: databaseId,
    })}`,
    { approved },
  )
);
