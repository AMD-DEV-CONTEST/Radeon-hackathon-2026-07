import { get, post, put, del } from "./client.js";

export function getEntities(params) {
  return get("/entity", params);
}

export function getEntity(id) {
  return get(`/entity/${id}`);
}

export function createEntity(data) {
  return post("/entity", data);
}

export function updateEntity(id, data) {
  return put(`/entity/${id}`, data);
}

export function deleteEntity(id) {
  return del(`/entity/${id}`);
}

export function getEntityTranslations(entityId) {
  return get(`/entity/${encodeURIComponent(entityId)}/translations`);
}

export function saveEntityTranslation(entityId, payload) {
  return post(`/entity/${encodeURIComponent(entityId)}/translate`, payload);
}

export function reviewEntityTranslation(translationId, payload) {
  return post(`/entity-translations/${encodeURIComponent(translationId)}/review`, payload);
}

export function getRelations(entityId, direction = "both") {
  return get(`/entity/${entityId}/relations`, { direction });
}

export function createRelation(data) {
  return post("/relation", data);
}
