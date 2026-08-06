import {
	cpSync,
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	renameSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import type { WorkspaceConfiguration } from "../shared/agent-configuration.ts";

const metadataFile = ".rdk-agent-workspace.json";

export interface ResolvedWorkspace {
	root: string;
	kind: "managed" | "external";
	description: string;
	created: boolean;
}

interface WorkspaceMetadata {
	schemaVersion: 1;
	id: string;
	templateVersion: number;
	templateDirectory: string;
	createdAt: string;
}

function defaultStateDirectory(): string {
	const stateHome = process.env.XDG_STATE_HOME ?? join(homedir(), ".local", "state");
	return join(stateHome, "rdk-agent");
}

function validateRequiredPaths(root: string, requiredPaths: readonly string[]): void {
	const missing = requiredPaths.filter((path) => !existsSync(join(root, path)));
	if (missing.length > 0) throw new Error(`托管工作区不完整，缺少：${missing.join(", ")}；工作区：${root}`);
}

export class ManagedWorkspaceResolver {
	private readonly stateDirectory: string;

	constructor(stateDirectory = defaultStateDirectory()) {
		this.stateDirectory = stateDirectory;
	}

	resolve(configuration: WorkspaceConfiguration, explicitRoot?: string): ResolvedWorkspace {
		if (explicitRoot) {
			const root = resolve(explicitRoot);
			if (!existsSync(root)) throw new Error(`外部源码工作区不存在：${root}`);
			return { root, kind: "external", description: `外部源码工作区 ${root}`, created: false };
		}
		if (configuration.kind === "current-directory") {
			const root = resolve(process.cwd());
			return { root, kind: "external", description: `当前目录工作区 ${root}`, created: false };
		}

		const root = join(this.stateDirectory, "workspaces", configuration.id, `v${configuration.version}`);
		if (existsSync(root)) {
			this.validateMetadata(root, configuration.id, configuration.version);
			validateRequiredPaths(root, configuration.requiredPaths);
			return { root, kind: "managed", description: `内置模板托管工作区 ${root}`, created: false };
		}

		const parent = dirname(root);
		mkdirSync(parent, { recursive: true });
		const stagingDirectory = mkdtempSync(join(parent, ".provision-"));
		const stagedWorkspace = join(stagingDirectory, "workspace");
		try {
			cpSync(configuration.templateDirectory, stagedWorkspace, { recursive: true, errorOnExist: true });
			const metadata: WorkspaceMetadata = {
				schemaVersion: 1,
				id: configuration.id,
				templateVersion: configuration.version,
				templateDirectory: configuration.templateDirectory,
				createdAt: new Date().toISOString(),
			};
			writeFileSync(join(stagedWorkspace, metadataFile), `${JSON.stringify(metadata, null, 2)}\n`, { flag: "wx" });
			validateRequiredPaths(stagedWorkspace, configuration.requiredPaths);
			renameSync(stagedWorkspace, root);
		} finally {
			rmSync(stagingDirectory, { recursive: true, force: true });
		}
		return { root, kind: "managed", description: `内置模板托管工作区 ${root}`, created: true };
	}

	private validateMetadata(root: string, id: string, version: number): void {
		const path = join(root, metadataFile);
		if (!existsSync(path)) throw new Error(`拒绝复用来源不明的托管工作区：${root}`);
		let metadata: Partial<WorkspaceMetadata>;
		try {
			metadata = JSON.parse(readFileSync(path, "utf8")) as Partial<WorkspaceMetadata>;
		} catch (error) {
			throw new Error(`托管工作区元数据损坏：${path}：${error instanceof Error ? error.message : String(error)}`);
		}
		if (metadata.schemaVersion !== 1 || metadata.id !== id || metadata.templateVersion !== version) {
			throw new Error(`托管工作区元数据与配置不匹配：${root}`);
		}
	}
}
