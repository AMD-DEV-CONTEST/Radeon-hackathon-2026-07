export function normalizeRelation(raw = {}) {
  const sourceId = raw.source_id || raw.source || raw.source_entity_id || "";
  const targetId = raw.target_id || raw.target || raw.target_entity_id || "";

  return {
    id: raw.id || `${sourceId}-${raw.relation_type || raw.type || "related"}-${targetId}`,
    sourceId,
    targetId,
    sourceTitle: raw.source_title || raw.source || sourceId || "未知源实体",
    targetTitle: raw.target_title || raw.target || targetId || "未知目标实体",
    type: raw.relation_type || raw.type || "related_to",
    description: raw.description || raw.rel_desc || "",
    bookId: raw.book_id || "",
    raw,
  };
}

export function normalizeRelationList(payload) {
  const list = Array.isArray(payload) ? payload : payload?.results || payload?.relations || [];
  return list.map(normalizeRelation);
}
