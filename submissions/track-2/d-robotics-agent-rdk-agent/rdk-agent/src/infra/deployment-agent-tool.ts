import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { access, cp, mkdir, readFile, rename, stat } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";
import { Type } from "typebox";
import { parse } from "yaml";
import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { AgentProfile, SkillDeploymentPlan, SshDeploymentPlan } from "../domain/agent-profile.ts";
import { defaultLocale, localeText, type Locale } from "../shared/locale.ts";

interface ProcessResult {
	stdout: string;
	stderr: string;
}

interface InstalledRemoteArtifact {
	host: string;
	target: string;
	staged: string;
	backup: string;
	recursive: boolean;
}

const deployParameters = Type.Object({});

function processError(command: string, args: readonly string[], code: number | null, stderr: string): Error {
	return new Error(`${command} ${args.join(" ")} 失败（exit=${code ?? "signal"}）：${stderr.trim() || "无错误输出"}`);
}

function runProcess(command: string, args: readonly string[], signal?: AbortSignal): Promise<ProcessResult> {
	return new Promise((resolvePromise, reject) => {
		const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
		let stdout = "";
		let stderr = "";
		const abort = (): void => {
			child.kill("SIGTERM");
		};
		signal?.addEventListener("abort", abort, { once: true });
		child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
			stdout += chunk;
		});
		child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
			stderr += chunk;
		});
		child.once("error", reject);
		child.once("close", (code) => {
			signal?.removeEventListener("abort", abort);
			if (signal?.aborted) reject(new Error(`${command} 已中止`));
			else if (code === 0) resolvePromise({ stdout, stderr });
			else reject(processError(command, args, code, stderr));
		});
	});
}

function workspaceFile(workspaceRoot: string, configuredPath: string): string {
	const root = resolve(workspaceRoot);
	const absolute = resolve(root, configuredPath);
	const workspacePath = relative(root, absolute);
	if (workspacePath === "" || workspacePath === ".." || workspacePath.startsWith(`..${sep}`)) {
		throw new Error(`部署源文件越出工作区：${configuredPath}`);
	}
	return absolute;
}

async function sha256(path: string): Promise<string> {
	return createHash("sha256").update(await readFile(path)).digest("hex");
}

export function validateSkillPackage(contents: string, expectedName: string): void {
	const lines = contents.replace(/^\uFEFF/, "").split(/\r?\n/);
	if (lines[0] !== "---") throw new Error("Skill 的 SKILL.md 缺少起始 YAML frontmatter（---）");
	const closing = lines.indexOf("---", 1);
	if (closing < 0) throw new Error("Skill 的 SKILL.md 缺少结束 YAML frontmatter（---）");
	let metadata: unknown;
	try {
		metadata = parse(lines.slice(1, closing).join("\n"));
	} catch (error) {
		throw new Error(`Skill 的 YAML frontmatter 无法解析：${error instanceof Error ? error.message : String(error)}`);
	}
	if (typeof metadata !== "object" || metadata === null || Array.isArray(metadata)) {
		throw new Error("Skill 的 YAML frontmatter 必须是对象");
	}
	const values = metadata as Record<string, unknown>;
	if (values.name !== expectedName) throw new Error(`Skill name 必须是 ${expectedName}`);
	if (typeof values.description !== "string" || values.description.trim() === "") {
		throw new Error("Skill description 必须是非空字符串");
	}
	if (lines.slice(closing + 1).join("\n").trim() === "") throw new Error("Skill 正文不能为空");
}

async function rollbackRemote(installed: readonly InstalledRemoteArtifact[], signal?: AbortSignal): Promise<void> {
	for (const artifact of [...installed].reverse()) {
		const command = artifact.recursive
			? `set -eu; rm -rf ${artifact.target}; if [ -e ${artifact.backup} ]; then mv -f ${artifact.backup} ${artifact.target}; fi; rm -rf ${artifact.staged}`
			: `set -eu; if [ -f ${artifact.backup} ]; then mv -f ${artifact.backup} ${artifact.target}; else rm -f ${artifact.target}; fi; rm -f ${artifact.staged}`;
		await runProcess("ssh", [artifact.host, command], signal).catch(() => undefined);
	}
}

async function deploySsh(workspaceRoot: string, plan: SshDeploymentPlan, signal?: AbortSignal): Promise<string> {
	const stamp = `${Date.now()}-${process.pid}`;
	const installed: InstalledRemoteArtifact[] = [];
	const stagedPaths: string[] = [];
	const receipt: string[] = [];
	try {
		for (const artifact of plan.artifacts) {
			const source = workspaceFile(workspaceRoot, artifact.source);
			const sourceStat = await stat(source);
			if (artifact.recursive ? !sourceStat.isDirectory() : !sourceStat.isFile()) {
				throw new Error(`部署源不是${artifact.recursive ? "目录" : "文件"}：${artifact.source}`);
			}
			const targetDirectory = dirname(artifact.target);
			const staged = `${artifact.target}.rdk-agent-${stamp}.tmp`;
			const backup = `${artifact.target}.rdk-agent-${stamp}.bak`;
			const state = { host: plan.host, target: artifact.target, staged, backup, recursive: Boolean(artifact.recursive) };

			await runProcess("ssh", [plan.host, `mkdir -p ${targetDirectory}`], signal);
			await runProcess("scp", artifact.recursive ? ["-q", "-r", "--", source, `${plan.host}:${staged}`] : ["-q", "--", source, `${plan.host}:${staged}`], signal);
			stagedPaths.push(staged);
			const preparation = [
				`chmod${artifact.recursive ? " -R" : ""} ${artifact.mode} ${staged}`,
				...(artifact.owner ? [`chown -R ${artifact.owner} ${staged}`] : []),
				...(artifact.recursive
					? [`find ${staged} -type f -name '*.py' -exec python3 -m py_compile {} +`]
					: artifact.target.endsWith(".py") ? [`python3 -m py_compile ${staged}`] : []),
			];
			await runProcess("ssh", [plan.host, `set -eu; ${preparation.join("; ")}`], signal);
			await runProcess(
				"ssh",
				[
					plan.host,
					`set -eu; had_existing=0; if [ -e ${artifact.target} ] || [ -L ${artifact.target} ]; then mv ${artifact.target} ${backup}; had_existing=1; fi; if ! mv ${staged} ${artifact.target}; then if [ "$had_existing" -eq 1 ]; then mv ${backup} ${artifact.target}; fi; exit 1; fi`,
				],
				signal,
			);
			installed.push(state);
			if (artifact.recursive) {
				receipt.push(`${artifact.source}/ -> ${plan.host}:${artifact.target}/ backup=${backup}`);
			} else {
				const localHash = await sha256(source);
				const remoteHash = (await runProcess("ssh", [plan.host, `sha256sum ${artifact.target}`], signal)).stdout.trim().split(/\s+/)[0];
				if (localHash !== remoteHash) throw new Error(`部署校验和不一致：${artifact.target}`);
				receipt.push(`${artifact.source} -> ${plan.host}:${artifact.target} sha256=${localHash} backup=${backup}`);
			}
		}
		if (plan.restartService) {
			await runProcess("ssh", [plan.host, `systemctl restart ${plan.restartService} && systemctl is-active --quiet ${plan.restartService}`], signal);
			receipt.push(`service restarted: ${plan.restartService}`);
		}
		return receipt.join("\n");
	} catch (error) {
		await rollbackRemote(installed, signal);
		for (const staged of stagedPaths) {
			await runProcess("ssh", [plan.host, `rm -rf ${staged}`], signal).catch(() => undefined);
		}
		if (plan.restartService && installed.length > 0) {
			await runProcess("ssh", [plan.host, `systemctl restart ${plan.restartService}`], signal).catch(() => undefined);
		}
		throw error;
	}
}

async function deploySkill(workspaceRoot: string, skillDirectory: string, plan: SkillDeploymentPlan): Promise<string> {
	const source = workspaceFile(workspaceRoot, plan.source);
	if (!(await stat(source)).isDirectory()) throw new Error(`Skill 部署源不是目录：${plan.source}`);
	const skillFile = resolve(source, "SKILL.md");
	await access(skillFile);
	validateSkillPackage(await readFile(skillFile, "utf8"), plan.skillName);
	const destination = resolve(skillDirectory, plan.skillName);
	if (resolve(source) === destination) return `Skill 已位于运行目录：${destination}`;

	await mkdir(skillDirectory, { recursive: true });
	const stamp = `${Date.now()}-${process.pid}`;
	const staged = resolve(skillDirectory, `.${plan.skillName}.rdk-agent-${stamp}.tmp`);
	const backup = resolve(skillDirectory, `.${plan.skillName}.rdk-agent-${stamp}.bak`);
	let hadExisting = false;
	try {
		await access(destination);
		hadExisting = true;
	} catch {
		hadExisting = false;
	}
	if (plan.runtimeFiles) {
		if (hadExisting) await cp(destination, staged, { recursive: true, errorOnExist: true });
		else await mkdir(staged, { recursive: true });
		for (const configuredFile of plan.runtimeFiles) {
			const sourceFile = resolve(source, configuredFile);
			const sourceRelative = relative(source, sourceFile);
			if (sourceRelative === ".." || sourceRelative.startsWith(`..${sep}`)) {
				throw new Error(`Skill 运行时文件越出交付目录：${configuredFile}`);
			}
			if (!(await stat(sourceFile)).isFile()) throw new Error(`Skill 运行时交付物不是文件：${configuredFile}`);
			const stagedFile = resolve(staged, configuredFile);
			await mkdir(dirname(stagedFile), { recursive: true });
			await cp(sourceFile, stagedFile, { force: true });
		}
	} else {
		await cp(source, staged, { recursive: true, errorOnExist: true });
	}
	validateSkillPackage(await readFile(resolve(staged, "SKILL.md"), "utf8"), plan.skillName);
	if (hadExisting) await rename(destination, backup);
	try {
		await rename(staged, destination);
	} catch (error) {
		if (hadExisting) await rename(backup, destination).catch(() => undefined);
		throw error;
	}
	const files = plan.runtimeFiles ? ` runtimeFiles=${plan.runtimeFiles.join(",")}` : "";
	return `${plan.source} -> ${destination}${files}${hadExisting ? ` backup=${backup}` : ""}`;
}

export function createDeploymentToolDefinition(
	workspaceRoot: string,
	skillDirectory: string,
	profile: AgentProfile,
	locale: Locale = defaultLocale,
): ToolDefinition<any, any, any> {
	const plan = profile.deployment;
	if (!plan) throw new Error(`${profile.id} 未配置 deployment`);
	return {
		name: "deploy",
		label: "deploy",
		description: "Deploy the already verified artifacts using the stage's fixed, allowlisted delivery plan. This tool takes no arguments and never edits source files.",
		promptSnippet: "Deploy verified artifacts with the configured immutable delivery plan",
		promptGuidelines: ["Call deploy exactly once after reviewing the upstream delivery; report its receipt verbatim."],
		parameters: deployParameters,
		async execute(_toolCallId, _params, signal) {
			const receipt = plan.kind === "ssh"
				? await deploySsh(workspaceRoot, plan, signal)
				: await deploySkill(workspaceRoot, skillDirectory, plan);
			return {
				content: [{
					type: "text",
					text: `${localeText(locale, "部署成功", "Deployment succeeded")}\n${receipt}`,
				}],
				details: undefined,
			};
		},
	};
}
