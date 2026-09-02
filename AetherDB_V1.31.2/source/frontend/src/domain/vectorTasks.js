export const ACTIVE_VECTOR_TASK_STATUSES = new Set(["queued", "running"]);

const TASK_STATUS_LABELS = {
  queued: "等待执行",
  running: "正在生成",
  completed: "已完成",
  partial_failed: "部分失败",
  failed: "执行失败",
  cancelled: "已取消",
};

const TASK_KIND_LABELS = {
  rebuild: "重建索引",
  entity_sync: "实体同步",
  retry_failed: "失败项重试",
};

export function vectorTaskStatusLabel(status) {
  return TASK_STATUS_LABELS[status] || status || "未知状态";
}

export function vectorTaskKindLabel(kind) {
  return TASK_KIND_LABELS[kind] || kind || "向量任务";
}

export function vectorTaskProgress(task) {
  const total = Math.max(0, Number(task?.total_items || 0));
  const processed = Math.max(0, Number(task?.processed_items || 0));
  if (!total) return task?.status === "completed" ? 100 : 0;
  return Math.min(100, Math.round((processed / total) * 100));
}

export function isActiveVectorTask(task) {
  return ACTIVE_VECTOR_TASK_STATUSES.has(task?.status);
}

export function canRetryVectorTask(task) {
  return ["partial_failed", "failed"].includes(task?.status)
    && Number(task?.failed_items || 0) > 0;
}
