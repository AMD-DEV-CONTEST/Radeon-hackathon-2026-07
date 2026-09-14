import assert from "node:assert/strict";
import test from "node:test";
import type { AgentProfile } from "../../src/domain/agent-profile.ts";
import { AgentPromptBuilder } from "../../src/infra/agent-prompt-builder.ts";
import type { AgentExpectation, AgentRunRequest } from "../../src/shared/agent-runner.ts";

const profile: AgentProfile = {
	id: "stage",
	name: "Stage Agent",
	description: "test",
	tools: ["read", "write"],
	skills: ["demo-skill"],
	systemPrompt: "system",
	writePaths: ["tests/*.ts"],
	timeoutSeconds: 90,
	maxToolCalls: 6,
};

function request(expectation: AgentExpectation): AgentRunRequest {
	return {
		profile,
		userRequest: "新增 wave-hands",
		workspaceRoot: "/tmp/workspace",
		skillDirectory: "/tmp/skills",
		expectation,
		iteration: 1,
		previousDeliveries: [{ stageId: "upstream", summary: "upstream result" }],
		onEvent: () => undefined,
	};
}

test("test-agent prompt requires an initial target-behavior red run for new capabilities", () => {
	const prompt = new AgentPromptBuilder().build(request("test"));
	assert.doesNotMatch(prompt, /^\/skill:/);
	assert.match(prompt, /Agent ID：stage/);
	assert.match(prompt, /## Skill 白名单\ndemo-skill/);
	assert.match(prompt, /- demo-skill: \/tmp\/skills\/demo-skill\/SKILL\.md/);
	assert.match(prompt, /不得猜测 Skill 位于业务工作区/);
	assert.match(prompt, /不得默认固定使用列表第一项/);
	assert.match(prompt, /只允许新增或修改测试/);
	assert.match(prompt, /不得拿上一个循环的测试文件冒充当前阶段测试/);
	assert.match(prompt, /当前 Agent 的唯一任务（优先级最高）/);
	assert.match(prompt, /工具层允许写入的唯一路径范围：tests\/\*\.ts/);
	assert.match(prompt, /必须调用 scaffold 创建本轮新脚手架/);
	assert.match(prompt, /同名历史动作会被运行时可恢复地备份/);
	assert.match(prompt, /必须先得到因目标行为未实现而失败的有效红测/);
	assert.match(prompt, /测试在实现前直接通过.*意外绿测/);
	assert.match(prompt, /导入、测试收集、fixture、路径或 mock 配置失败永远不是有效红测/);
	assert.match(prompt, /工具调用上限为 6 次/);
	assert.match(prompt, /RDK_AGENT_RESULT: \{"status":"completed"\}/);
});

test("test-agent retry prompt must resolve verifier feedback instead of accepting the same red failure", () => {
	const retry = request("test");
	const prompt = new AgentPromptBuilder().build({ ...retry, iteration: 2 });
	assert.match(prompt, /返工轮强制规则/);
	assert.match(prompt, /不得把相同失败再次当作红测完成/);
});

test("prompt reports unlimited tools when maxToolCalls is omitted", () => {
	const prompt = new AgentPromptBuilder().build({
		...request("coding"),
		profile: { ...profile, maxToolCalls: undefined },
	});
	assert.match(prompt, /工具调用次数不设上限/);
	assert.doesNotMatch(prompt, /工具调用上限为/);
});

test("prompt makes the Podman test boundary explicit", () => {
	const prompt = new AgentPromptBuilder().build({
		...request("test"),
		profile: {
			...profile,
			sandbox: { kind: "podman", image: "python:3.12-slim", network: "none" },
		},
	});
	assert.match(prompt, /离线 Podman 容器 python:3\.12-slim/);
	assert.match(prompt, /工作区以只读方式挂载/);
	assert.match(prompt, /只保证 Python 3\.12 标准库/);
	assert.match(prompt, /不提供 pytest 或板端 Hobot\.GPIO/);
	assert.match(prompt, /write 可递归创建白名单内的父目录/);
	assert.match(prompt, /不要探测或依赖开发机 Python/);
});

test("coding-agent prompt protects upstream tests", () => {
	const prompt = new AgentPromptBuilder().build(request("coding"));
	assert.match(prompt, /不得删除、跳过、弱化/);
	assert.match(prompt, /只点名测试文件或 acceptance\.md/);
	assert.match(prompt, /不得反复 edit/);
	assert.match(prompt, /最多运行一次确认失败/);
	assert.match(prompt, /禁止对同一失败反复 edit\/bash 直到超时/);
	assert.match(prompt, /禁止驱动真实硬件/);
});

test("verification-agent prompt is read-only and requires its own test run", () => {
	const prompt = new AgentPromptBuilder().build(request("verification"));
	assert.match(prompt, /全程只读/);
	assert.match(prompt, /亲自运行安全测试/);
	assert.match(prompt, /物理效果待确认必须记录为剩余风险，不能因此要求返工/);
	assert.match(prompt, /RDK_AGENT_RESULT: \{"status":"revision"/);
});

test("application-agent treats an action request as authorization to execute hardware once", () => {
	const applicationRequest = request("application");
	const prompt = new AgentPromptBuilder().build({ ...applicationRequest, userRequest: "摇一下耳朵" });
	assert.match(prompt, /## 用户指令\n摇一下耳朵/);
	assert.match(prompt, /动作式请求，本身就是对相应真实动作的一次明确授权/);
	assert.match(prompt, /前置检查通过后必须直接执行一次/);
	assert.match(prompt, /运行时已将当前输入判定为动作式请求/);
	assert.match(prompt, /设备不可达或动作必填参数缺失时返回 needs-human/);
	assert.match(prompt, /选择与用户指令匹配的一个或多个 Skill/);
	assert.match(prompt, /先用 read 完整读取每个选中的 SKILL.md/);
	assert.doesNotMatch(prompt, /未经人类明确确认不得驱动真实硬件/);
});

test("application-agent marks Skill questions as tool-enforced read-only requests", () => {
	const applicationRequest = request("application");
	const prompt = new AgentPromptBuilder().build({ ...applicationRequest, userRequest: "当前加载了哪些 Skill？" });
	assert.match(prompt, /运行时已将当前输入判定为只读查询/);
	assert.match(prompt, /Bash 工具层也会拒绝此类命令/);
	assert.doesNotMatch(prompt, /运行时已将当前输入判定为动作式请求/);
});

test("English Agent prompts require English prose while preserving result markers", () => {
	const englishRequest = { ...request("verification"), locale: "en" as const };
	const prompt = new AgentPromptBuilder().build(englishRequest);
	assert.match(prompt, /Finish with a concise English list/);
	assert.match(prompt, /All user-facing prose, including summaries, feedback, and questions, must be in English/);
	assert.match(prompt, /RDK_AGENT_RESULT: \{"status":"revision","feedback":"specific issue requiring revision"\}/);
	assert.doesNotMatch(prompt, /最后用简洁中文列出/);
});
