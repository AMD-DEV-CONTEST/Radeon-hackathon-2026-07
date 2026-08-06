import { buildQuery, del, get, post } from "./client.js";

export function getMediaVisionStatus(databaseId, bookId) {
  return get("/media-vision/status", {
    database_id: databaseId,
    book_id: bookId,
  });
}

export function listMediaVisualSpaces(databaseId) {
  return get("/media-vision/spaces", { database_id: databaseId });
}

export function createMediaVisualSpace(databaseId, requestedBackend = "auto") {
  return post("/media-vision/spaces", {
    database_id: databaseId,
    requested_backend: requestedBackend,
  });
}

export function validateMediaVisualSpace(spaceId, databaseId) {
  return post(`/media-vision/spaces/${encodeURIComponent(spaceId)}/validate`, {
    database_id: databaseId,
  });
}

export function activateMediaVisualSpace(spaceId, databaseId) {
  return post(`/media-vision/spaces/${encodeURIComponent(spaceId)}/activate`, {
    database_id: databaseId,
  });
}

export function rollbackMediaVisualSpace(databaseId) {
  return post("/media-vision/spaces/rollback", { database_id: databaseId });
}

export function garbageCollectMediaVisualSpace(spaceId, databaseId) {
  return post(
    `/media-vision/spaces/${encodeURIComponent(spaceId)}/garbage-collect`,
    {
      database_id: databaseId,
      confirm_space_id: spaceId,
    },
  );
}

export function listMediaVisualMigrations(databaseId, status = null, limit = 100) {
  return get("/media-vision/migrations", {
    database_id: databaseId,
    status,
    limit,
  });
}

export function getMediaVisualMigration(taskId, databaseId) {
  return get(`/media-vision/migrations/${encodeURIComponent(taskId)}`, {
    database_id: databaseId,
  });
}

export function cancelMediaVisualMigration(taskId, databaseId) {
  return post(`/media-vision/migrations/${encodeURIComponent(taskId)}/cancel`, {
    database_id: databaseId,
  });
}

export function retryMediaVisualMigration(taskId, databaseId) {
  return post(`/media-vision/migrations/${encodeURIComponent(taskId)}/retry`, {
    database_id: databaseId,
  });
}

export function indexMediaVisionAsset(assetId, databaseId, payload = {}) {
  return post(
    `/media-vision/assets/${encodeURIComponent(assetId)}/index${buildQuery({
      database_id: databaseId,
    })}`,
    payload,
  );
}

export function indexMediaVisionBatch(databaseId, payload) {
  return post(
    `/media-vision/index-batch${buildQuery({ database_id: databaseId })}`,
    payload,
  );
}

export function removeMediaVisionAsset(assetId, databaseId) {
  return del(
    `/media-vision/assets/${encodeURIComponent(assetId)}/index${buildQuery({
      database_id: databaseId,
    })}`,
  );
}

export function searchMediaVisionText(databaseId, payload) {
  return post(
    `/media-vision/search/text${buildQuery({ database_id: databaseId })}`,
    payload,
  );
}

export function searchMediaVisionImage(databaseId, payload) {
  return post(
    `/media-vision/search/image${buildQuery({ database_id: databaseId })}`,
    payload,
  );
}
