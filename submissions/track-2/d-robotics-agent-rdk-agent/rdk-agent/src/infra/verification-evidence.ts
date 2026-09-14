import { isNewCapabilityRequest } from "../domain/development-intent.ts";
import type { AgentExpectation, AgentRunResult } from "../shared/agent-runner.ts";
import { defaultLocale, localeText, type Locale } from "../shared/locale.ts";

export interface BashExecutionEvidence {
	command: string;
	output: string;
	failed: boolean;
}

export interface VerificationToolEvidence {
	bash: readonly BashExecutionEvidence[];
	scaffoldSucceeded?: boolean;
}

export interface TestEvidenceContext {
	locale?: Locale;
	userRequest?: string;
	iteration?: number;
}

const unittestCommand = /(?:^|[\s;&|])(?:[^\s;&|]+\/)?python(?:3(?:\.\d+)?)?\s+-m\s+unittest(?:\s|$)/iu;
const testInfrastructureFailure = /(?:ModuleNotFoundError|ImportError|FileNotFoundError|SyntaxError|No such file or directory|unrecognized arguments|Ran\s+0\s+tests?)/iu;
const targetBehaviorFailure = /(?:AssertionError|NotImplementedError)/u;

export function isUnittestCommand(command: string): boolean {
	return unittestCommand.test(command);
}

export function isTestExecution(execution: BashExecutionEvidence): boolean {
	return isUnittestCommand(execution.command);
}

function testExecutions(evidence: VerificationToolEvidence): readonly BashExecutionEvidence[] {
	return evidence.bash.filter(isTestExecution);
}

function isValidRedTest(execution: BashExecutionEvidence): boolean {
	return execution.failed
		&& /Ran\s+[1-9]\d*\s+tests?/u.test(execution.output)
		&& targetBehaviorFailure.test(execution.output)
		&& !testInfrastructureFailure.test(execution.output);
}

export function needsVerificationEvidenceRetry(
	result: AgentRunResult,
	expectation: AgentExpectation,
	evidence: VerificationToolEvidence,
): boolean {
	return expectation === "verification" && result.outcome === "completed" && testExecutions(evidence).length === 0;
}

export const verificationEvidenceRetryPrompt = `运行时拒绝了你刚才没有执行目标测试的 passed 结论。
现在不要继续读取或复述文件，必须立即调用 bash 工具，亲自运行上游交付中与当前阶段对应的精确 unittest 命令。
命令成功后才能返回 passed；命令失败则返回 revision 并给出真实错误。最后仍须输出单行 RDK_AGENT_RESULT。`;

export function verificationEvidenceRetryPromptForLocale(locale: Locale = defaultLocale): string {
	return localeText(
		locale,
		verificationEvidenceRetryPrompt,
		"The runtime rejected the previous passed result because the target test was not executed. Do not keep reading or restating files. Call the bash tool now and personally run the exact unittest command for this stage from the upstream delivery. Return passed only if the command succeeds; otherwise return revision with the real error. The final line must still be a single-line RDK_AGENT_RESULT.",
	);
}

export function needsTestExecutionEvidenceRetry(
	result: AgentRunResult,
	expectation: AgentExpectation,
	hasBashTool: boolean,
	evidence: VerificationToolEvidence,
): boolean {
	return expectation === "test"
		&& hasBashTool
		&& result.outcome === "completed"
		&& testExecutions(evidence).length === 0;
}

export const testExecutionEvidenceRetryPrompt = `运行时拒绝了你刚才没有真实执行目标测试的完成结论。
现在不要继续编辑文件，必须立即调用 bash 工具运行本阶段刚创建或修改的精确 unittest 测试，并根据真实输出重新报告：
- 明确的新增功能在第一轮必须先得到目标行为红测；写完测试立即通过属于意外绿测，不能交付；
- 修改、修复或测试既有功能时，绿色回归测试可以交付；
- 导入、路径、收集、fixture、策略拒绝或 mock 错误不是有效红测，必须先修复。
最后仍须输出单行 RDK_AGENT_RESULT。`;

export function testExecutionEvidenceRetryPromptForLocale(locale: Locale = defaultLocale): string {
	return localeText(
		locale,
		testExecutionEvidenceRetryPrompt,
		"The runtime rejected the previous completion because the target test was not actually executed. Do not edit more files. Call the bash tool now to run the exact unittest test created or changed in this stage, then report the real output. An explicit new capability must produce a target-behavior red test in its first iteration; a test that passes before implementation is an unexpected green and cannot be delivered. A green regression remains valid for changes, fixes, or tests of an existing capability. Import, path, collection, fixture, policy, or mock errors are not valid red tests. The final line must still be a single-line RDK_AGENT_RESULT.",
	);
}

function missingTestResult(result: AgentRunResult, locale: Locale): AgentRunResult {
	return {
		summary: result.summary,
		outcome: "needs-human",
		question: localeText(
			locale,
			"测试设计 Agent 没有运行本阶段的目标 unittest，无法确认有效红测或绿色回归。请补充方向后重试，或输入 /abort 终止。",
			"The test-design Agent did not run this stage's target unittest, so the runtime cannot confirm a valid red test or green regression. Provide guidance and retry, or enter /abort to stop.",
		),
	};
}

/** A Bash-capable test designer must execute the target test and preserve red-first semantics for new work. */
export function enforceTestExecutionEvidence(
	result: AgentRunResult,
	expectation: AgentExpectation,
	hasBashTool: boolean,
	evidence: VerificationToolEvidence,
	context: TestEvidenceContext = {},
): AgentRunResult {
	if (expectation !== "test" || !hasBashTool || result.outcome !== "completed") return result;
	const locale = context.locale ?? defaultLocale;
	const executions = testExecutions(evidence);
	if (executions.length === 0) return missingTestResult(result, locale);
	const finalExecution = executions.at(-1)!;
	const firstIteration = (context.iteration ?? 1) === 1;
	const explicitNewCapability = context.userRequest !== undefined && isNewCapabilityRequest(context.userRequest);
	const requiresInitialRed = firstIteration && (explicitNewCapability || evidence.scaffoldSucceeded === true);

	if (firstIteration && explicitNewCapability && !evidence.scaffoldSucceeded) {
		return {
			summary: result.summary,
			outcome: "needs-human",
			question: localeText(
				locale,
				"该指令要求新增功能，但本轮没有成功创建新的动作脚手架。请重试并先调用 action-package scaffold；运行时会备份同名历史动作，不应直接复用旧测试。",
				"This request creates a new capability, but no new action scaffold was created in this iteration. Retry and call action-package scaffold first; the runtime will archive a same-named historical action instead of reusing its old test.",
			),
		};
	}
	if (requiresInitialRed && !finalExecution.failed) {
		return {
			summary: result.summary,
			outcome: "needs-human",
			question: localeText(
				locale,
				"新增功能在实现前测试意外通过，已拒绝该绿测。测试可能没有覆盖目标行为，或工作区混入了已有实现；请修正测试或使用干净基线后重试。",
				"The new capability test passed before implementation, so the unexpected green was rejected. The test may not cover the target behavior, or the workspace may contain an existing implementation. Fix the test or retry from a clean baseline.",
			),
		};
	}
	if (finalExecution.failed && !isValidRedTest(finalExecution)) {
		return {
			summary: result.summary,
			outcome: "needs-human",
			question: localeText(
				locale,
				"目标测试失败，但不是由 AssertionError 或 NotImplementedError 表示的有效行为红测。请先修复导入、路径、fixture、策略或测试基础设施问题。",
				"The target test failed, but not with a valid target-behavior AssertionError or NotImplementedError. Fix import, path, fixture, policy, or test-infrastructure problems first.",
			),
		};
	}
	return result;
}

/** A verifier must run the target test, and no failed target-test run may be hidden by a later success. */
export function enforceVerificationEvidence(
	result: AgentRunResult,
	expectation: AgentExpectation,
	evidence: VerificationToolEvidence,
	locale: Locale = defaultLocale,
): AgentRunResult {
	if (expectation !== "verification" || result.outcome !== "completed") return result;
	const executions = testExecutions(evidence);
	if (executions.length === 0) {
		return {
			summary: result.summary,
			outcome: "revision",
			feedback: localeText(
				locale,
				"验证 Agent 没有运行目标 unittest，不能判定 passed。请执行约定的 mock/静态测试。",
				"The verification Agent did not run the target unittest and cannot report passed. Run the required mock or static test.",
			),
		};
	}
	if (executions.some((execution) => execution.failed)) {
		return {
			summary: result.summary,
			outcome: "revision",
			feedback: localeText(
				locale,
				"验证 Agent 的目标测试命令出现失败，却返回了 passed。后续成功命令不能覆盖先前失败；请修复后在新的验证轮中全部跑绿。",
				"A target test command failed, but the verification Agent returned passed. A later successful command cannot hide an earlier failure; fix it and rerun every target test successfully in a new verification iteration.",
			),
		};
	}
	return result;
}
