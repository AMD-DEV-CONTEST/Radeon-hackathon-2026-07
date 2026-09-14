import { join } from "node:path";
import type { AgentExpectation, AgentRunRequest, Delivery } from "../shared/agent-runner.ts";
import { isReadOnlyApplicationRequest } from "../domain/application-intent.ts";
import { defaultLocale, localeText, outputLanguageInstruction, type Locale } from "../shared/locale.ts";

const maxPriorDeliveryCharacters = 6_000;

const roleContracts: Readonly<Record<AgentExpectation, string>> = {
	test: `## 本阶段硬约束：测试设计
- 只允许新增或修改测试、验收场景、测试夹具；禁止修改生产代码、plugin.toml 和最终 SKILL.md。
- 必须产出当前 Agent 配置所要求的本阶段专属交付物；不得拿上一个循环的测试文件冒充当前阶段测试。
- 首轮先写能执行的最小测试：用户明确要求新增/创建/实现新功能时，必须调用 scaffold 创建本轮新脚手架；同名历史动作会被运行时可恢复地备份。随后必须先得到因目标行为未实现而失败的有效红测；若新脚手架的测试在实现前直接通过，必须报告 needs-human 指出意外绿测。只有修改、修复或测试既有功能时，绿色回归测试才可直接交付。
- 模块导入、测试收集、fixture、路径或 mock 配置失败永远不是有效红测，必须先修到目标断言能够执行。
- 测试涉及工作区中的注册表、动态模块或环境变量时，必须先从源码确认 loader 的实际路径与格式，并在命令中显式设置所需环境变量；误读板端默认路径或凭空假设导入器都属于 fixture/测试缺陷，不是有效红测。
- 当前 Agent 配置包含 bash 工具时，交付前必须亲自运行本阶段刚创建或修改的精确测试文件；没有真实命令输出不得报告红测或绿测。
- 后续轮次必须处理最新验证反馈；验证 Agent 指出测试缺陷时必须实际修改并重跑测试，不能重复报告同一个已知问题。
- 禁止为让测试变绿而 monkey patch 待实现的方法，禁止在子进程中触发真实硬件。`,
coding: `## 本阶段硬约束：实现
- 以测试 Agent 的交付为不可随意改写的契约，只修改本阶段生产交付物。
- 返工反馈如果只点名测试文件或 acceptance.md，且没有指出本阶段生产交付物缺陷，只需核对生产交付仍满足契约后直接完成；不得反复 edit 一个无需变更的文件。对应问题应由本轮测试设计 Agent 修订。
- 编辑前先确认功能是否已经存在；已满足测试时不改文件，禁止重复添加类、方法、动作映射或 main。已有文件优先使用最小 edit，禁止用整文件 write 拼接内容。
- 运行上游给出的精确测试命令直到变绿；不得删除、跳过、弱化或把待实现逻辑写进测试。
- 如果测试引用了仓库中不存在、且与现有架构冲突的虚构契约，不得通过新增别名、重复集合或兼容层迎合错误测试。最多运行一次确认失败，随后停止编辑并在交付中明确指出测试缺陷，让验证 Agent 判定返工；禁止对同一失败反复 edit/bash 直到超时。
- 不得根据 Python 包的常见写法臆造模块路径或加载器；注册字段的精确格式必须以当前入口源码的 loader 实现为准。测试失败时先核对 loader、环境变量、文件路径和注册字段，再判断是否确属框架缺失。
- 只能做静态、mock 或模拟验证，禁止驱动真实硬件。无法满足测试时返回 needs-human，不要篡改测试。`,
	verification: `## 本阶段硬约束：独立验证
- 全程只读，禁止修改任何文件。
- 逐项核对用户指令、上游测试与实现，并亲自运行安全测试；只看代码或只相信上游描述都不能判定通过。
- 任一 Bash 检查失败时必须返回 revision，不能把失败归因为“非本阶段责任”后返回 passed。先从入口源码验证 loader、环境变量、文件路径和注册字段；只有证明当前阶段无权修复且缺少真实外部依赖时才返回 needs-human。
- 所有约定测试通过且没有弱测试、绕过 CLI 或硬件副作用时才返回 passed；可修复问题返回 revision。`,
	deployment: `## 本阶段硬约束：确定性交付
- 只部署上游已经通过验证的交付物；禁止修改源代码、测试、manifest 或 Skill。
- 必须调用一次 deploy 工具执行配置中固定的部署计划，并逐项核对工具返回的目标路径、校验和或备份位置。
- deploy 失败时不得改用 scp、ssh、cp 等方式绕过工具策略；应返回 needs-human 并附上真实错误。
- 部署阶段只做语法、清单、帮助或无硬件检查，不得执行真实舵机动作。`,
	application: `## 本阶段硬约束：应用验收
- 从严格 Skill 白名单中根据 name 和 description 选择与用户指令匹配的一个或多个 Skill，先用 read 完整读取每个选中的 SKILL.md，再按其中的自然语言映射执行最终 CLI 调用。没有匹配 Skill 时不得改用白名单外能力。
- 用户在机器人应用模式输入“摇一下耳朵”“站起来”“先动左手再动右手”等动作式请求，本身就是对相应真实动作的一次明确授权。前置检查通过后必须直接执行一次，不得再次索要“确认真机”，也不得只运行 plugins list 或 --help 就宣布完成。
- 用户只询问能力、命令或状态时才保持只读；缺少 Skill、设备不可达或动作必填参数缺失时返回 needs-human。`,
};

export class AgentPromptBuilder {
	build(request: AgentRunRequest): string {
		const locale = request.locale ?? defaultLocale;
		const history = this.deliveryHistory(request.previousDeliveries, locale);
		const iteration = request.iteration === undefined ? "" : `\n\n## 当前循环\n第 ${request.iteration} 次 TDD 迭代`;
		const retryRule = request.expectation === "test" && (request.iteration ?? 1) > 1
			? "\n\n## 返工轮强制规则\n这是返工轮。必须以最近的 verification 反馈为首要任务，修掉测试夹具/导入/断言问题并重跑；不得把相同失败再次当作红测完成。"
			: "";
		const executionBoundary = request.expectation === "application"
			? isReadOnlyApplicationRequest(request.userRequest)
				? "运行时已将当前输入判定为只读查询。只能读取 Skill、查看列表、帮助和状态，严禁执行任何可能驱动硬件的动作命令；Bash 工具层也会拒绝此类命令。"
				: "运行时已将当前输入判定为动作式请求，并授权执行对应真机动作一次；完成必要的只读前置检查后直接执行一次。"
				: request.expectation === "deployment"
					? "当前是部署阶段：允许按固定 deploy 计划写入目标环境，但禁止执行真实动作。"
					: "开发态的静态、mock、模拟和帮助验证，与部署后的真实硬件效果是两个验收边界。只要用户没有要求本阶段驱动真机，物理效果待确认必须记录为剩余风险，不能因此要求返工或人类提供真机输出。";
		const writable = request.profile.writePaths.length === 0 ? "无（只读）" : request.profile.writePaths.join(", ");
		const skillWhitelist = request.profile.skills.length > 0 ? request.profile.skills.join(", ") : "无";
		const skillFiles = request.profile.skills.length > 0
			? request.profile.skills.map((name) => `- ${name}: ${join(request.skillDirectory, name, "SKILL.md")}`).join("\n")
			: "- 无";
		const skillRule = request.profile.skills.length > 0
			? "只能使用这里列出的 Skill。必须根据当前用户指令选择匹配项，并在使用前通过 read 读取下面给出的精确绝对路径；一条用户指令可选择多个。不得猜测 Skill 位于业务工作区，不得默认固定使用列表第一项。"
			: "当前阶段没有配置 Skill，不得自行发现或使用全局、项目或其他 Agent 的 Skill。";
		const toolCallBudget = request.profile.maxToolCalls === undefined
			? "工具调用次数不设上限"
			: `工具调用上限为 ${request.profile.maxToolCalls} 次`;
		const sandboxBoundary = request.profile.sandbox?.kind === "podman"
			? `Bash 命令在离线 Podman 容器 ${request.profile.sandbox.image} 中执行；工作区以只读方式挂载，HOME 和 /tmp 位于临时容器内。容器只保证 Python 3.12 标准库，不提供 pytest 或板端 Hobot.GPIO；Python 测试必须使用 unittest 并在导入生产模块前 mock 板端模块，不得安装依赖。read/edit/write 仍由宿主进程执行并受 writePaths 白名单约束；write 可递归创建白名单内的父目录，Bash 保持只读，所以不要在 Bash 中运行 mkdir。不要探测或依赖开发机 Python、HOME、SSH 凭据或全局包。`
			: "Bash 命令在宿主环境执行。";
		const deliverySummaryInstruction = localeText(
			locale,
			"在工作目录内完成本阶段。最后用简洁中文列出：交付文件、调用方式、验证结果和未解决风险。",
			"Complete this stage in the working directory. Finish with a concise English list of delivered files, usage, verification results, and unresolved risks.",
		);
		return `## 当前阶段\nAgent ID：${request.profile.id}\nAgent 名称：${request.profile.name}\n工作区绝对根目录：${request.workspaceRoot}\n后文所有 writePaths 均为相对于该根目录的路径；调用 read/edit/write 时优先原样使用工作区相对路径，禁止自行删减路径前缀。\n必须完成该 Agent 外置 systemPrompt 指定的专属交付，不能用其他阶段已有文件替代。\n\n## 用户指令\n${request.userRequest}\n\n## 上游交付\n${history}${iteration}\n\n${roleContracts[request.expectation]}${retryRule}\n\n${executionBoundary}\n\n## 执行环境\n${sandboxBoundary}\n\n## Skill 白名单\n${skillWhitelist}\n${skillRule}\n可读取的 Skill 文件：\n${skillFiles}\n\n${toolCallBudget}，阶段超时为 ${request.profile.timeoutSeconds} 秒。先定位最小文件集合，避免扫描或改动无关目录。\n\n## 当前 Agent 的唯一任务（优先级最高）\n${request.profile.systemPrompt}\n\n工具层允许写入的唯一路径范围：${writable}\n即使完整用户指令提到了下游 CLI、Skill 或部署，你也只能完成上面的当前任务。不要尝试写入白名单外路径；路径被拒绝时先按这里列出的相对路径纠正，不能把自己的路径错误升级为人类授权问题。下游 Agent 会接手其他交付。\n\n${deliverySummaryInstruction}\n\n## Output language\n${outputLanguageInstruction(locale)}\n\n${this.resultContract(request.expectation, locale)}`;
	}

	private deliveryHistory(deliveries: readonly Delivery[], locale: Locale = defaultLocale): string {
		if (deliveries.length === 0) {
			return localeText(locale, "无：你是流水线的第一个 Agent。", "None: you are the first Agent in the pipeline.");
		}
		return deliveries
			.map((delivery) => `### ${delivery.stageId}\n${delivery.summary.slice(-maxPriorDeliveryCharacters)}`)
			.join("\n\n");
	}

	private resultContract(expectation: AgentExpectation, locale: Locale = defaultLocale): string {
		if (expectation === "verification") {
			return localeText(locale, `回复的最后一行必须是以下三种之一，JSON 必须保持单行：
RDK_AGENT_RESULT: {"status":"passed"}
RDK_AGENT_RESULT: {"status":"revision","feedback":"需要返工的具体问题"}
RDK_AGENT_RESULT: {"status":"needs-human","question":"需要人类回答的问题"}`, `The final line of the response must be exactly one of the following single-line JSON results:
RDK_AGENT_RESULT: {"status":"passed"}
RDK_AGENT_RESULT: {"status":"revision","feedback":"specific issue requiring revision"}
RDK_AGENT_RESULT: {"status":"needs-human","question":"question for the user"}`);
		}
		return localeText(locale, `回复的最后一行必须是以下两种之一，JSON 必须保持单行：
RDK_AGENT_RESULT: {"status":"completed"}
RDK_AGENT_RESULT: {"status":"needs-human","question":"需要人类回答的问题"}`, `The final line of the response must be exactly one of the following single-line JSON results:
RDK_AGENT_RESULT: {"status":"completed"}
RDK_AGENT_RESULT: {"status":"needs-human","question":"question for the user"}`);
	}
}
