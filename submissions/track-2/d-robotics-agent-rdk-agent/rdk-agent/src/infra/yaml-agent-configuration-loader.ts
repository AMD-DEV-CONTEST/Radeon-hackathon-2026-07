import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { parse } from "yaml";
import type {
	AgentProfile,
	ActionPackagePlan,
	DeliveryValidationPlan,
	DeploymentPlan,
	SandboxExecutionPlan,
	SshDeploymentArtifact,
} from "../domain/agent-profile.ts";
import type { OrchestrationMode, TddLoopDefinition } from "../domain/orchestration-mode.ts";
import type {
	AgentConfiguration,
	AgentConfigurationLoader,
	RequestIntakeConfiguration,
	WorkspaceConfiguration,
} from "../shared/agent-configuration.ts";
import { defaultLocale, type Locale } from "../shared/locale.ts";

type UnknownRecord = Record<string, unknown>;

export class YamlAgentConfigurationLoader implements AgentConfigurationLoader {
	load(configDirectory: string, locale: Locale = defaultLocale): AgentConfiguration {
		const resolvedDirectory = resolve(configDirectory);
		const configPath = join(resolvedDirectory, "agents.yaml");
		if (!existsSync(configPath)) throw new Error(`Agent 配置不存在：${configPath}`);

		const document: unknown = parse(readFileSync(configPath, "utf8"));
		const root = this.record(document, "agents.yaml");
		if (root.version !== 2) throw new Error("agents.yaml 的 version 当前必须为 2；请参考随程序提供的新配置");
		if (!Array.isArray(root.agents) || root.agents.length === 0) {
			throw new Error("agents.yaml 至少需要配置一个 Agent");
		}

		const profiles = root.agents.map((value, index) => this.profile(value, index, locale));
		const ids = profiles.map((profile) => profile.id);
		if (new Set(ids).size !== ids.length) throw new Error("agents.yaml 中的 Agent id 不能重复");
		const profileIds = new Set(ids);
		if (!Array.isArray(root.modes) || root.modes.length === 0) throw new Error("agents.yaml 至少需要配置一个模式");
		const modes = root.modes.map((value, index) => this.mode(value, index, profileIds, locale));
		const modeIds = modes.map((mode) => mode.id);
		if (new Set(modeIds).size !== modeIds.length) throw new Error("agents.yaml 中的模式 id 不能重复");
		const defaultModeId = this.string(root.defaultMode, "defaultMode");
		if (!modeIds.includes(defaultModeId)) throw new Error(`defaultMode 引用了不存在的模式：${defaultModeId}`);
		const workspace = this.workspace(root.workspace, resolvedDirectory);
		const intake = this.intake(root.intake, locale);

		const skillDirectory = join(resolvedDirectory, "skills");
		for (const profile of profiles) {
			for (const skill of profile.skills) {
				const skillPath = join(skillDirectory, skill, "SKILL.md");
				if (!existsSync(skillPath)) throw new Error(`${profile.id} 配置的 Skill 不存在：${skillPath}`);
			}
		}

		return { configDirectory: resolvedDirectory, skillDirectory, profiles, modes, defaultModeId, workspace, intake, locale };
	}

	private intake(value: unknown, locale: Locale): RequestIntakeConfiguration {
		if (value === undefined) {
			return {
				autoStartConfidence: 0.9,
				timeoutSeconds: 30,
				developmentScope: "只有用户指令明确要求新增、修改、修复、测试或部署当前机器人能力时，才启动受支持的研发流程。",
			};
		}
		const raw = this.record(value, "intake");
		const autoStartConfidence = raw.autoStartConfidence === undefined
			? 0.9
			: this.probability(raw.autoStartConfidence, "intake.autoStartConfidence");
		const timeoutSeconds = this.optionalPositiveInteger(raw.timeoutSeconds, "intake.timeoutSeconds", 30);
		const chineseDevelopmentScope = raw.developmentScope === undefined
			? "只有用户指令明确要求新增、修改、修复、测试或部署当前机器人能力时，才启动受支持的研发流程。"
			: this.string(raw.developmentScope, "intake.developmentScope");
		const englishDevelopmentScope = raw.developmentScopeEn === undefined
			? undefined
			: this.string(raw.developmentScopeEn, "intake.developmentScopeEn");
		const developmentScope = locale === "en" ? englishDevelopmentScope ?? chineseDevelopmentScope : chineseDevelopmentScope;
		return { autoStartConfidence, timeoutSeconds, developmentScope };
	}

	private workspace(value: unknown, configDirectory: string): WorkspaceConfiguration {
		if (value === undefined) return { kind: "current-directory", requiredPaths: [] };
		const raw = this.record(value, "workspace");
		const requiredPaths = this.optionalStringArray(raw.requiredPaths, "workspace.requiredPaths")
			.map((path, index) => this.relativePath(path, `workspace.requiredPaths[${index}]`));
		const kind = raw.kind === undefined ? "current-directory" : this.string(raw.kind, "workspace.kind");
		if (kind === "current-directory") return { kind, requiredPaths };
		if (kind !== "managed-template") throw new Error(`workspace.kind 不支持：${kind}`);
		const id = this.identifier(raw.id, "workspace.id");
		const version = this.positiveInteger(raw.version, "workspace.version");
		const template = this.relativePath(raw.template, "workspace.template");
		const templateDirectory = resolve(configDirectory, template);
		if (!existsSync(templateDirectory)) throw new Error(`workspace.template 不存在：${templateDirectory}`);
		for (const path of requiredPaths) {
			if (!existsSync(join(templateDirectory, path))) throw new Error(`workspace.template 缺少必需文件：${path}`);
		}
		return { kind, id, version, templateDirectory, requiredPaths };
	}

	private mode(value: unknown, index: number, profileIds: ReadonlySet<string>, locale: Locale): OrchestrationMode {
		const label = `modes[${index}]`;
		const raw = this.record(value, label);
		const id = this.identifier(raw.id, `${label}.id`);
		const name = this.localizedString(raw, "name", label, locale);
		const type = this.string(raw.type, `${label}.type`);
		if (type === "robot-application") {
			const agentId = this.identifier(raw.agent, `${label}.agent`);
			this.requireAgent(agentId, `${label}.agent`, profileIds);
			return { id, name, type, agentId };
		}
		if (type !== "robot-development") throw new Error(`${label}.type 不支持：${type}`);
		if (!Array.isArray(raw.loops) || raw.loops.length === 0) throw new Error(`${label}.loops 至少需要一个 TDD 循环`);
		const loops = raw.loops.map((loop, loopIndex) => this.loop(loop, `${label}.loops[${loopIndex}]`, profileIds, locale));
		const loopIds = loops.map((loop) => loop.id);
		if (new Set(loopIds).size !== loopIds.length) throw new Error(`${label}.loops 的 id 不能重复`);
		const acceptanceAgentIds = this.optionalStringArray(raw.acceptanceAgents, `${label}.acceptanceAgents`).map((agentId, agentIndex) => {
			const normalized = this.identifier(agentId, `${label}.acceptanceAgents[${agentIndex}]`);
			this.requireAgent(normalized, `${label}.acceptanceAgents[${agentIndex}]`, profileIds);
			return normalized;
		});
		const deliveryAgentIds = this.optionalStringArray(raw.deliveryAgents, `${label}.deliveryAgents`).map((agentId, agentIndex) => {
			const normalized = this.identifier(agentId, `${label}.deliveryAgents[${agentIndex}]`);
			this.requireAgent(normalized, `${label}.deliveryAgents[${agentIndex}]`, profileIds);
			return normalized;
		});
		const stageIds = [
			...loops.flatMap((loop) => [loop.id, ...(loop.deploymentAgentId ? [loop.deploymentAgentId] : [])]),
			...deliveryAgentIds,
			...acceptanceAgentIds,
		];
		if (new Set(stageIds).size !== stageIds.length) {
			throw new Error(`${label} 的 TDD、交付和验收阶段 id 不能重复`);
		}
		return { id, name, type, loops, deliveryAgentIds, acceptanceAgentIds };
	}

	private loop(value: unknown, label: string, profileIds: ReadonlySet<string>, locale: Locale): TddLoopDefinition {
		const raw = this.record(value, label);
		const testAgentId = this.identifier(raw.testAgent, `${label}.testAgent`);
		const codingAgentId = this.identifier(raw.codingAgent, `${label}.codingAgent`);
		const verificationAgentId = this.identifier(raw.verificationAgent, `${label}.verificationAgent`);
		this.requireAgent(testAgentId, `${label}.testAgent`, profileIds);
		this.requireAgent(codingAgentId, `${label}.codingAgent`, profileIds);
		this.requireAgent(verificationAgentId, `${label}.verificationAgent`, profileIds);
		const deploymentAgentId = raw.deploymentAgent === undefined
			? undefined
			: this.identifier(raw.deploymentAgent, `${label}.deploymentAgent`);
		if (deploymentAgentId) this.requireAgent(deploymentAgentId, `${label}.deploymentAgent`, profileIds);
		return {
			id: this.identifier(raw.id, `${label}.id`),
			name: this.localizedString(raw, "name", label, locale),
			deliverable: this.localizedString(raw, "deliverable", label, locale),
			testAgentId,
			codingAgentId,
			verificationAgentId,
			maxIterations: this.positiveInteger(raw.maxIterations, `${label}.maxIterations`),
			deploymentAgentId,
		};
	}

	private profile(value: unknown, index: number, locale: Locale): AgentProfile {
		const label = `agents[${index}]`;
		const raw = this.record(value, label);
		const id = this.identifier(raw.id, `${label}.id`);
		const tools = this.stringArray(raw.tools, `${label}.tools`);
		const writePaths = this.optionalStringArray(raw.writePaths, `${label}.writePaths`);
		if ((tools.includes("write") || tools.includes("edit")) && writePaths.length === 0) {
			throw new Error(`${label}.writePaths 在启用 edit/write 时不能为空`);
		}
		const deployment = raw.deployment === undefined ? undefined : this.deployment(raw.deployment, `${label}.deployment`);
		const actionPackage = raw.actionPackage === undefined ? undefined : this.actionPackage(raw.actionPackage, `${label}.actionPackage`);
		const validation = raw.validation === undefined ? undefined : this.validation(raw.validation, `${label}.validation`);
		const sandbox = raw.sandbox === undefined ? undefined : this.sandbox(raw.sandbox, `${label}.sandbox`);
		if (tools.includes("deploy") !== Boolean(deployment)) {
			throw new Error(`${label} 的 deploy 工具与 deployment 配置必须同时存在`);
		}
		if (tools.includes("action-package") !== Boolean(actionPackage)) {
			throw new Error(`${label} 的 action-package 工具与 actionPackage 配置必须同时存在`);
		}
		return {
			id,
			name: this.localizedString(raw, "name", label, locale),
			description: this.localizedString(raw, "description", label, locale),
			tools,
			skills: this.stringArray(raw.skills, `${label}.skills`),
			systemPrompt: this.string(raw.systemPrompt, `${label}.systemPrompt`),
			writePaths,
			timeoutSeconds: this.optionalPositiveInteger(raw.timeoutSeconds, `${label}.timeoutSeconds`, 300),
			maxToolCalls: this.optionalPositiveIntegerValue(raw.maxToolCalls, `${label}.maxToolCalls`),
			sandbox,
			deployment,
			actionPackage,
			validation,
		};
	}

	private actionPackage(value: unknown, label: string): ActionPackagePlan {
		const raw = this.record(value, label);
		const operations = this.stringArray(raw.operations, `${label}.operations`);
		if (operations.length === 0) throw new Error(`${label}.operations 至少需要一个操作`);
		const allowed = new Set(["scaffold", "validate", "build"]);
		for (const operation of operations) {
			if (!allowed.has(operation)) throw new Error(`${label}.operations 不支持：${operation}`);
		}
		if (new Set(operations).size !== operations.length) throw new Error(`${label}.operations 不能重复`);
		return { operations: operations as ActionPackagePlan["operations"] };
	}

	private sandbox(value: unknown, label: string): SandboxExecutionPlan {
		const raw = this.record(value, label);
		const kind = this.string(raw.kind, `${label}.kind`);
		if (kind !== "podman") throw new Error(`${label}.kind 不支持：${kind}`);
		const image = this.string(raw.image, `${label}.image`);
		if (!/^[A-Za-z0-9][A-Za-z0-9._/:@-]*$/.test(image)) throw new Error(`${label}.image 格式不安全`);
		const network = this.string(raw.network, `${label}.network`);
		if (network !== "none") throw new Error(`${label}.network 当前必须为 none`);
		return { kind, image, network };
	}

	private validation(value: unknown, label: string): DeliveryValidationPlan | undefined {
		const raw = this.record(value, label);
		const kind = this.string(raw.kind, `${label}.kind`);
		// Early v2 configurations exposed this marker even though executable
		// Python evidence is now enforced by the normal TDD runner. Treat only
		// this exact retired kind as an absent validation plan so customized
		// configurations remain loadable while the installer migrates the file.
		if (kind === "servo-python-test") return undefined;
		if (kind !== "skill-contract") throw new Error(`${label}.kind 不支持：${kind}`);
		const evidenceFiles = this.stringArray(raw.evidenceFiles, `${label}.evidenceFiles`).map((path, index) =>
			this.relativePath(path, `${label}.evidenceFiles[${index}]`),
		);
		if (evidenceFiles.length === 0) throw new Error(`${label}.evidenceFiles 至少需要一个测试文件`);
		return {
			kind,
			source: this.relativePath(raw.source, `${label}.source`),
			skillName: this.identifier(raw.skillName, `${label}.skillName`),
			manifest: this.relativePath(raw.manifest, `${label}.manifest`),
			entrypointSource: this.relativePath(raw.entrypointSource, `${label}.entrypointSource`),
			evidenceFiles,
			baselineSkillName: this.identifier(raw.baselineSkillName, `${label}.baselineSkillName`),
		};
	}

	private deployment(value: unknown, label: string): DeploymentPlan {
		const raw = this.record(value, label);
		const kind = this.string(raw.kind, `${label}.kind`);
		if (kind === "skill") {
			let runtimeFiles: readonly string[] | undefined;
			if (raw.runtimeFiles !== undefined) {
				if (!Array.isArray(raw.runtimeFiles) || raw.runtimeFiles.length === 0) {
					throw new Error(`${label}.runtimeFiles 必须是非空数组`);
				}
				runtimeFiles = raw.runtimeFiles.map((item, index) =>
					this.relativePath(item, `${label}.runtimeFiles[${index}]`));
				if (!runtimeFiles.includes("SKILL.md")) {
					throw new Error(`${label}.runtimeFiles 必须包含 SKILL.md`);
				}
			}
			return {
				kind,
				source: this.relativePath(raw.source, `${label}.source`),
				skillName: this.identifier(raw.skillName, `${label}.skillName`),
				runtimeFiles,
			};
		}
		if (kind !== "ssh") throw new Error(`${label}.kind 不支持：${kind}`);
		const host = this.string(raw.host, `${label}.host`);
		if (!/^[A-Za-z0-9._-]+$/.test(host)) throw new Error(`${label}.host 包含不安全字符`);
		if (!Array.isArray(raw.artifacts) || raw.artifacts.length === 0) {
			throw new Error(`${label}.artifacts 至少需要一个部署文件`);
		}
		const artifacts: SshDeploymentArtifact[] = raw.artifacts.map((item, index) => {
			const artifact = this.record(item, `${label}.artifacts[${index}]`);
			const target = this.string(artifact.target, `${label}.artifacts[${index}].target`);
			if (!/^\/[A-Za-z0-9._/-]+$/.test(target) || target.includes("/../")) {
				throw new Error(`${label}.artifacts[${index}].target 必须是安全的绝对路径`);
			}
			const mode = artifact.mode === undefined ? "0644" : this.string(artifact.mode, `${label}.artifacts[${index}].mode`);
			if (!/^0[0-7]{3}$/.test(mode)) throw new Error(`${label}.artifacts[${index}].mode 必须是四位八进制权限`);
			const recursive = artifact.recursive === undefined ? false : this.boolean(artifact.recursive, `${label}.artifacts[${index}].recursive`);
			const owner = artifact.owner === undefined ? undefined : this.string(artifact.owner, `${label}.artifacts[${index}].owner`);
			if (owner !== undefined && !/^[a-z_][a-z0-9_-]*(?::[a-z_][a-z0-9_-]*)?$/.test(owner)) {
				throw new Error(`${label}.artifacts[${index}].owner 必须是安全的 user 或 user:group`);
			}
			return {
				source: this.relativePath(artifact.source, `${label}.artifacts[${index}].source`),
				target,
				mode,
				recursive,
				...(owner === undefined ? {} : { owner }),
			};
		});
		const restartService = raw.restartService === undefined ? undefined : this.string(raw.restartService, `${label}.restartService`);
		if (restartService !== undefined && !/^[a-z0-9@_.-]+\.service$/.test(restartService)) {
			throw new Error(`${label}.restartService 必须是安全的 systemd service 名称`);
		}
		return { kind, host, artifacts, ...(restartService === undefined ? {} : { restartService }) };
	}

	private relativePath(value: unknown, label: string): string {
		const path = this.string(value, label).replace(/^\.\//, "");
		if (path.startsWith("/") || path.split("/").includes("..")) {
			throw new Error(`${label} 必须是工作区相对路径`);
		}
		return path;
	}

	private identifier(value: unknown, label: string): string {
		const id = this.string(value, label);
		if (!/^[a-z][a-z0-9-]*$/.test(id)) throw new Error(`${label} 只能使用小写字母、数字和连字符`);
		return id;
	}

	private boolean(value: unknown, label: string): boolean {
		if (typeof value !== "boolean") throw new Error(`${label} 必须是布尔值`);
		return value;
	}

	private requireAgent(agentId: string, label: string, profileIds: ReadonlySet<string>): void {
		if (!profileIds.has(agentId)) throw new Error(`${label} 引用了不存在的 Agent：${agentId}`);
	}

	private positiveInteger(value: unknown, label: string): number {
		if (typeof value !== "number" || !Number.isInteger(value) || value < 1) throw new Error(`${label} 必须是正整数`);
		return value;
	}

	private probability(value: unknown, label: string): number {
		if (typeof value !== "number" || !Number.isFinite(value) || value <= 0 || value > 1) {
			throw new Error(`${label} 必须是大于 0 且不超过 1 的数字`);
		}
		return value;
	}

	private optionalPositiveInteger(value: unknown, label: string, fallback: number): number {
		return value === undefined ? fallback : this.positiveInteger(value, label);
	}

	private optionalPositiveIntegerValue(value: unknown, label: string): number | undefined {
		return value === undefined ? undefined : this.positiveInteger(value, label);
	}

	private record(value: unknown, label: string): UnknownRecord {
		if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} 必须是对象`);
		return value as UnknownRecord;
	}

	private string(value: unknown, label: string): string {
		if (typeof value !== "string" || value.trim() === "") throw new Error(`${label} 必须是非空字符串`);
		return value.trim();
	}

	private localizedString(raw: UnknownRecord, key: string, label: string, locale: Locale): string {
		const base = this.string(raw[key], `${label}.${key}`);
		const englishKey = `${key}En`;
		const english = raw[englishKey] === undefined
			? undefined
			: this.string(raw[englishKey], `${label}.${englishKey}`);
		return locale === "en" ? english ?? base : base;
	}

	private stringArray(value: unknown, label: string): readonly string[] {
		if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) {
			throw new Error(`${label} 必须是字符串数组`);
		}
		return value.map((item) => String(item).trim());
	}

	private optionalStringArray(value: unknown, label: string): readonly string[] {
		return value === undefined ? [] : this.stringArray(value, label);
	}
}
