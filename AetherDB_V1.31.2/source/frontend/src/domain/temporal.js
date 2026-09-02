const TEMPORAL_LABEL_KEYS = {
  order_only: "仅顺序",
  unknown: "未知",
  relative: "相对时间",
  exact: "精确时间",
  range: "时间范围",
  chapter: "章节",
  event: "事件",
  phase: "阶段",
  before: "早于",
  after: "晚于",
  simultaneous: "同时",
  overlaps: "时间重叠",
  approximately_before: "大约早于",
  approximately_after: "大约晚于",
  confirmed: "已确认",
  inferred: "推断",
  uncertain: "不确定",
  conflicting: "冲突",
  active: "启用",
  draft: "草稿",
  archived: "已归档",
  pending: "待确认",
  accepted: "已接受",
  physical: "身体状态",
  realm: "境界",
  location: "地点",
  identity: "身份",
  faction: "势力",
  injury: "伤势",
  equipment: "装备",
  ownership: "归属",
  relationship: "关系",
  psychological: "心理状态",
  behavior_logic: "行为逻辑",
  knowledge: "已知信息",
  goal: "目标",
  life_status: "生命状态",
};

export function temporalLabel(translate, value) {
  return translate(TEMPORAL_LABEL_KEYS[value] || value || "未知");
}

export function timelineLabel(translate, timeline) {
  return timeline?.is_default ? translate("主时间线") : timeline?.name || translate("时间线");
}
