import test from "node:test";
import assert from "node:assert/strict";

import {
  canRetryVectorTask,
  isActiveVectorTask,
  vectorTaskKindLabel,
  vectorTaskProgress,
  vectorTaskStatusLabel,
} from "../src/domain/vectorTasks.js";

test("vector task presentation keeps progress and actions deterministic", () => {
  const running = { status: "running", processed_items: 3, total_items: 8 };
  const failed = { status: "partial_failed", failed_items: 2 };

  assert.equal(vectorTaskProgress(running), 38);
  assert.equal(vectorTaskProgress({ status: "completed", total_items: 0 }), 100);
  assert.equal(vectorTaskProgress({ processed_items: 50, total_items: 10 }), 100);
  assert.equal(isActiveVectorTask(running), true);
  assert.equal(isActiveVectorTask(failed), false);
  assert.equal(canRetryVectorTask(failed), true);
  assert.equal(canRetryVectorTask({ status: "failed", failed_items: 0 }), false);
  assert.equal(vectorTaskStatusLabel("partial_failed"), "部分失败");
  assert.equal(vectorTaskKindLabel("rebuild"), "重建索引");
});
