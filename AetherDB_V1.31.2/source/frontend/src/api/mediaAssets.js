import { buildQuery, del, get, getBlob, patch, post, upload } from "./client.js";

export function listMediaAssets(params) {
  return get("/media-assets", params);
}

export function listEffectiveChapterMedia(params) {
  return get("/media-assets/effective", params);
}

export function getMediaAsset(assetId, databaseId) {
  return get(`/media-assets/${encodeURIComponent(assetId)}`, { database_id: databaseId });
}

export function uploadMediaAsset({
  databaseId,
  bookId,
  file,
  sourceType = "imported",
  createdByTaskId,
  signal,
}) {
  const form = new FormData();
  form.append("database_id", databaseId);
  form.append("book_id", bookId);
  form.append("source_type", sourceType);
  if (createdByTaskId) form.append("created_by_task_id", createdByTaskId);
  form.append("file", file, file.name || "media");
  return upload("/media-assets", form, { signal, timeoutMs: 300_000 });
}

export function updateMediaAsset(assetId, databaseId, payload) {
  return patch(`/media-assets/${encodeURIComponent(assetId)}${buildQuery({ database_id: databaseId })}`, payload);
}

export function submitMediaAsset(assetId, databaseId) {
  return post(`/media-assets/${encodeURIComponent(assetId)}/submit${buildQuery({ database_id: databaseId })}`, {});
}

export function approveMediaAsset(assetId, databaseId) {
  return post(`/media-assets/${encodeURIComponent(assetId)}/approve${buildQuery({ database_id: databaseId })}`, {});
}

export function rejectMediaAsset(assetId, databaseId) {
  return post(`/media-assets/${encodeURIComponent(assetId)}/reject${buildQuery({ database_id: databaseId })}`, {});
}

export function archiveMediaAsset(assetId, databaseId) {
  return post(`/media-assets/${encodeURIComponent(assetId)}/archive${buildQuery({ database_id: databaseId })}`, {});
}

export function createMediaBinding(assetId, databaseId, payload) {
  return post(`/media-assets/${encodeURIComponent(assetId)}/bindings${buildQuery({ database_id: databaseId })}`, payload);
}

export function deleteMediaBinding(assetId, bindingId, databaseId) {
  return del(
    `/media-assets/${encodeURIComponent(assetId)}/bindings/${encodeURIComponent(bindingId)}${buildQuery({ database_id: databaseId })}`,
  );
}

export function addMediaAnnotation(assetId, databaseId, payload) {
  return post(`/media-assets/${encodeURIComponent(assetId)}/annotations${buildQuery({ database_id: databaseId })}`, payload);
}

export function reviewMediaAnnotation(assetId, annotationId, databaseId, approved) {
  return post(
    `/media-assets/${encodeURIComponent(assetId)}/annotations/${encodeURIComponent(annotationId)}/review${buildQuery({
      database_id: databaseId,
    })}`,
    { approved },
  );
}

export function deleteMediaAsset(assetId, databaseId) {
  return del(`/media-assets/${encodeURIComponent(assetId)}${buildQuery({ database_id: databaseId })}`);
}

export function loadMediaContent(assetId, databaseId, options = {}) {
  return getBlob(`/media-assets/${encodeURIComponent(assetId)}/content`, { database_id: databaseId }, options);
}

export function cleanupMediaAssets(databaseId, retentionDays = 7) {
  return post(
    `/media-assets/maintenance/cleanup${buildQuery({
      database_id: databaseId,
      retention_days: retentionDays,
    })}`,
    {},
  );
}
