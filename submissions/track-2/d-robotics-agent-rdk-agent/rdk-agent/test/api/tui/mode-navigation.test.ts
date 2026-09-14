import assert from "node:assert/strict";
import test from "node:test";
import { adjacentModeId, modeSwitchDirection } from "../../../src/api/tui/mode-navigation.ts";
import type { OrchestrationMode } from "../../../src/domain/orchestration-mode.ts";

const modes: readonly OrchestrationMode[] = [
	{
		id: "robot-development",
		name: "机器人开发模式",
		type: "robot-development",
		loops: [],
		deliveryAgentIds: [],
		acceptanceAgentIds: [],
	},
	{
		id: "robot-application",
		name: "机器人应用模式",
		type: "robot-application",
		agentId: "application",
	},
];

test("only the simultaneous Shift+Tab chord switches modes", () => {
	assert.equal(modeSwitchDirection("\t"), 0);
	assert.equal(modeSwitchDirection("\x1b[Z"), 1);
	assert.equal(modeSwitchDirection("a"), 0);
});

test("mode switching follows configuration order and wraps around", () => {
	assert.equal(adjacentModeId(modes, "robot-development", 1), "robot-application");
	assert.equal(adjacentModeId(modes, "robot-application", 1), "robot-development");
	assert.equal(adjacentModeId(modes, "robot-development", -1), "robot-application");
	assert.equal(adjacentModeId(modes, "robot-application", -1), "robot-development");
});

test("mode switching rejects an unknown selected mode", () => {
	assert.throws(() => adjacentModeId(modes, "missing", 1), /当前模式不存在/);
});
