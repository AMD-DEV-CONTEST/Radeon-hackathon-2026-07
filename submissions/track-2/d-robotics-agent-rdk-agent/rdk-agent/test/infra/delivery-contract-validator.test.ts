import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { SkillContractValidationPlan } from "../../src/domain/agent-profile.ts";
import { enforceDeliveryContract, validateDeliveryContract } from "../../src/infra/delivery-contract-validator.ts";

function fixture(context: { after(callback: () => void): void }) {
	const workspace = mkdtempSync(join(tmpdir(), "rdk-agent-contract-workspace-"));
	const skillDirectory = mkdtempSync(join(tmpdir(), "rdk-agent-contract-skills-"));
	context.after(() => {
		rmSync(workspace, { recursive: true, force: true });
		rmSync(skillDirectory, { recursive: true, force: true });
	});
	const delivery = join(workspace, ".rdk-agent", "deliveries", "skills", "servo-control");
	mkdirSync(delivery, { recursive: true });
	mkdirSync(join(workspace, "examples", "tests"), { recursive: true });
	mkdirSync(join(skillDirectory, "servo-control"), { recursive: true });
	writeFileSync(join(workspace, "examples", "plugin.toml"), 'api_version = 1\nid = "servo"\nentrypoint = ["python3", "servo.py"]\n');
	writeFileSync(
		join(workspace, "examples", "servo.py"),
		'ACTIONS = {\n    "wave-hands": lambda c: None,\n    "wave-left-hand": lambda c: None,\n}\n' +
		'parser.add_argument("args", nargs="*")\nparser.add_argument("--hold")\nparser.add_argument("--exchange", action="store_true")\n',
	);
	writeFileSync(
		join(workspace, "examples", "tests", "test_wave.py"),
		"def test_wave_left_hand_sequence():\n    pass\n\ndef test_wave_left_hand_is_left_only_action():\n    pass\n",
	);
	writeFileSync(join(workspace, "examples", "tests", "test_cli.py"), "def test_main_dispatches_wave_left_hand():\n    pass\n");
	writeFileSync(
		join(skillDirectory, "servo-control", "SKILL.md"),
		'---\nname: servo-control\ndescription: baseline\n---\nUse `sophonctl servo wave-hands`.\n',
	);
	writeFileSync(
		join(delivery, "SKILL.md"),
		'---\nname: servo-control\ndescription: delivery\n---\nUse `sophonctl servo wave-hands` or `sophonctl servo wave-left-hand`.\n',
	);
	const plan: SkillContractValidationPlan = {
		kind: "skill-contract",
		source: ".rdk-agent/deliveries/skills/servo-control",
		skillName: "servo-control",
		manifest: "examples/plugin.toml",
		entrypointSource: "examples/servo.py",
		evidenceFiles: ["examples/tests/test_wave.py", "examples/tests/test_cli.py"],
		baselineSkillName: "servo-control",
	};
	return { workspace, skillDirectory, delivery, plan };
}

test("skill contract accepts accurate commands, evidence and preserved abilities", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand --hold 1`.\n" +
		"`test_wave.py` contains `test_wave_left_hand_sequence`.\n" +
		"`test_wave.py` contains `test_wave_left_hand_is_left_only_action`.\n" +
		"`test_cli.py` contains `test_main_dispatches_wave_left_hand`.\n" +
		"动作式输入不需要二次确认；实际物理效果仍需最终真机阶段由人类目视确认。\n",
	);
	await assert.doesNotReject(() => validateDeliveryContract(workspace, skillDirectory, plan));
});

test("skill contract requires natural-language authorization and the physical acceptance boundary", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand`.\n" +
		"`test_cli.py` contains `test_main_dispatches_wave_left_hand`.\n",
	);
	await assert.rejects(
		() => validateDeliveryContract(workspace, skillDirectory, plan),
		(error: unknown) => /无需二次确认/.test(String(error)) && /物理效果/.test(String(error)),
	);
});

test("skill contract rejects a sophonctl command that omits the plugin id", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(join(delivery, "acceptance.md"), "Run `sophonctl wave-left-hand`.\n");
	await assert.rejects(() => validateDeliveryContract(workspace, skillDirectory, plan), /缺少插件名 servo/);
});

test("skill contract rejects false no-parameter claims and wrong test ownership", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand`; this action 无任何参数。\n" +
		"`test_cli.py` contains `test_wave_left_hand_sequence`.\n",
	);
	await assert.rejects(() => validateDeliveryContract(workspace, skillDirectory, plan), /存在通用选项/);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand`.\n`test_cli.py` contains `test_wave_left_hand_sequence`.\n",
	);
	await assert.rejects(() => validateDeliveryContract(workspace, skillDirectory, plan), /错误归属/);
});

test("skill contract converts a false passed result into TDD revision feedback", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(join(delivery, "acceptance.md"), "Run `sophonctl wave-left-hand`.\n");
	const result = await enforceDeliveryContract(
		{ summary: "model said passed", outcome: "completed" },
		workspace,
		skillDirectory,
		plan,
	);
	assert.equal(result.outcome, "revision");
	assert.match(result.feedback ?? "", /缺少插件名 servo/);
	assert.match(result.summary, /确定性交付校验失败/);
});

test("skill contract rejects premature pass, false actions mapping and inferred permissions", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand`. `test_wave_left_hand_sequence` 通过。\n",
	);
	await assert.rejects(() => validateDeliveryContract(workspace, skillDirectory, plan), /不能.*预写测试已通过/);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand`; plugin.toml 的 [actions] 明确定义自然语言映射。\n",
	);
	await assert.rejects(() => validateDeliveryContract(workspace, skillDirectory, plan), /错把.*\[actions\]/);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Run `sophonctl servo wave-left-hand`; entrypoint 路径非 root 可写。\n",
	);
	await assert.rejects(() => validateDeliveryContract(workspace, skillDirectory, plan), /文件权限结论/);
});

test("skill contract reports multiple semantic errors in one revision", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"Natural language maps to `sophonctl servo wave-left-hand`; [actions] 定义自然语言映射。\n" +
		"The 动作本身不接受任何参数，额外参数将导致解析失败。\n" +
		"未在 plugin.toml 中定义的说法不构成有效触发。\n" +
		"plugin.toml 未配置 shell，所以安全。\n",
	);
	await assert.rejects(
		() => validateDeliveryContract(workspace, skillDirectory, plan),
		(error: unknown) => {
			assert.match(String(error), /存在通用选项/);
			assert.match(String(error), /\[actions\]/);
			assert.match(String(error), /nargs='\*'/);
			assert.match(String(error), /自然语言边界/);
			assert.match(String(error), /shell 字段/);
			return true;
		},
	);
});

test("skill contract rejects claims beyond the exact test assertions", async (context) => {
	const { workspace, skillDirectory, delivery, plan } = fixture(context);
	writeFileSync(
		join(delivery, "acceptance.md"),
		"CLI 命令 `sophonctl servo wave-left-hand` 由 plugin.toml 定义。\n" +
		"`test_main_dispatches_wave_left_hand` 验证 --hold 延时和无异常。\n" +
		"plugin.toml 未定义 shell，因此无 shell 注入风险。\n" +
		"atexit 确保无资源泄漏。\n",
	);
	await assert.rejects(
		() => validateDeliveryContract(workspace, skillDirectory, plan),
		(error: unknown) => {
			assert.match(String(error), /CLI 动作命令的定义来源/);
			assert.match(String(error), /shell 字段/);
			assert.match(String(error), /绝对安全或资源泄漏/);
			return true;
		},
	);
});
