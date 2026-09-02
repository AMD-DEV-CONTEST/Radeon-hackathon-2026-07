export const ENTITY_TYPE_LABELS = {
  character: "角色",
  faction: "势力",
  location: "地点",
  rule: "规则",
  event: "事件",
  item: "物品",
  concept: "概念",
  system: "系统",
};

function parseTags(tags) {
  if (Array.isArray(tags)) return tags;
  if (!tags) return [];
  try {
    const parsed = JSON.parse(tags);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return String(tags)
      .split(",")
      .map((tag) => tag.trim())
      .filter(Boolean);
  }
}

export function normalizeEntity(raw = {}) {
  const id = raw.entity_id || raw.id || raw.global_entity_id || raw.source_entity_id || raw.target_entity_id || "";
  const type = raw.entity_type || raw.type || raw.kind || "concept";
  const content = raw.content || raw.full_content || raw.ai_summary || raw.description || raw.content_preview || "";

  return {
    id,
    rawId: id,
    title: raw.title || raw.name || raw.entity_title || "未命名实体",
    type,
    typeLabel: ENTITY_TYPE_LABELS[type] || type || "实体",
    content,
    fullContent: raw.full_content || content,
    summary: raw.ai_summary || raw.summary || content.slice(0, 160),
    tags: parseTags(raw.tags),
    importance: Number(raw.importance || raw.score || 0),
    relationCount: Number(raw.relation_count || raw.relations || 0),
    timelineYear: raw.timeline_year || raw.year || null,
    timelineEra: raw.timeline_era || raw.era || "",
    bookId: raw.book_id || "",
    databaseId: raw.database_id || "",
    updatedAt: raw.updated_at || raw.created_at || "",
    raw,
  };
}

export function normalizeEntityList(payload) {
  const list = Array.isArray(payload) ? payload : payload?.results || payload?.entities || [];
  return list.map(normalizeEntity);
}

export function entityPreview(entity) {
  return entity.summary || entity.content || "暂无内容摘要";
}
