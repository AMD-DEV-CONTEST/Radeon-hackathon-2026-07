import { get, post, put } from "./client.js";


export const listTemporalAnchors = (params) => get("/temporal/anchors", params);
export const createTemporalAnchor = (payload) => post("/temporal/anchors", payload);
export const listTemporalRelations = (params) => get("/temporal/relations", params);
export const createTemporalRelation = (payload) => post("/temporal/relations", payload);
export const listTimelines = (params) => get("/temporal/timelines", params);
export const createTimeline = (payload) => post("/temporal/timelines", payload);
export const createEntityStateSegment = (payload) => post("/temporal/state-segments", payload);
export const getResolvedEntityState = (entityId, params) => get(`/entities/${entityId}/resolved-state`, params);
export const getEntityStateHistory = (entityId, params) => get(`/entities/${entityId}/state-history`, params);
export const getChapterTemporalContext = (chapterId, params) => get(`/chapters/${chapterId}/temporal-context`, params);
export const setChapterTemporalContext = (chapterId, payload) => put(`/chapters/${chapterId}/temporal-context`, payload);
export const getTemporalEventMetadata = (eventId, params) => get(`/temporal/events/${eventId}/metadata`, params);
export const setTemporalEventMetadata = (eventId, payload) => put(`/temporal/events/${eventId}/metadata`, payload);
