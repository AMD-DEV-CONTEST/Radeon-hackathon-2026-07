// Simple JSON object diff — returns { added: Record<string,unknown>, removed: Record<string,unknown>, changed: Record<string,{old:unknown,new:unknown}> }
export interface JsonDiff {
  added: Record<string, unknown>;
  removed: Record<string, unknown>;
  changed: Record<string, { old: unknown; new: unknown }>;
}

export function diffJson(oldObj: Record<string, unknown>, newObj: Record<string, unknown>): JsonDiff {
  const added: Record<string, unknown> = {};
  const removed: Record<string, unknown> = {};
  const changed: Record<string, { old: unknown; new: unknown }> = {};

  const allKeys = new Set([...Object.keys(oldObj), ...Object.keys(newObj)]);

  for (const key of allKeys) {
    const oldVal = oldObj[key];
    const newVal = newObj[key];

    if (oldVal === undefined && newVal !== undefined) {
      added[key] = newVal;
    } else if (oldVal !== undefined && newVal === undefined) {
      removed[key] = oldVal;
    } else if (JSON.stringify(oldVal) !== JSON.stringify(newVal)) {
      changed[key] = { old: oldVal, new: newVal };
    }
  }

  return { added, removed, changed };
}

export function hasChanges(diff: JsonDiff): boolean {
  return Object.keys(diff.added).length + Object.keys(diff.removed).length + Object.keys(diff.changed).length > 0;
}
