import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { YamlAgentConfigurationLoader } from "../../infra/yaml-agent-configuration-loader.ts";
import { ManagedWorkspaceResolver } from "../../infra/managed-workspace.ts";
import { localeText, parseLocale, type Locale } from "../../shared/locale.ts";
import { runHeadless } from "../cli/headless-runner.ts";
import { OrchestrationApp } from "./orchestration-app.ts";

interface CliOptions {
	workspaceRoot?: string;
	configDirectory: string;
	headlessRun?: { modeId: string; request: string };
	locale: Locale;
	helpRequested: boolean;
}

function parseArgs(args: readonly string[]): CliOptions {
	const sourceDirectory = dirname(fileURLToPath(import.meta.url));
	const bundledConfigDirectory = resolve(sourceDirectory, "../../../config");
	let configDirectory = process.env.RDK_AGENT_CONFIG_DIR ?? bundledConfigDirectory;
	let workspaceRoot: string | undefined;
	let workspaceProvided = false;
	let headlessRun: CliOptions["headlessRun"];
	let cliLocale: Locale | undefined;
	let helpRequested = false;

	for (let index = 0; index < args.length; index++) {
		const argument = args[index];
		if (argument === "--lang") {
			const value = args[index + 1];
			if (!value) throw new Error("--lang 需要语言参数 / --lang requires a language value");
			cliLocale = parseLocale(value);
			index++;
		} else if (argument === "--config-dir") {
			const value = args[index + 1];
			if (!value) throw new Error("--config-dir 需要目录参数");
			configDirectory = value;
			index++;
		} else if (argument === "--workspace") {
			const value = args[index + 1];
			if (!value) throw new Error("--workspace 需要目录参数");
			if (workspaceProvided) throw new Error("只能指定一个 workspace");
			workspaceRoot = value;
			workspaceProvided = true;
			index++;
		} else if (argument === "--run") {
			const modeId = args[index + 1];
			const request = args[index + 2];
			if (!modeId || !request) throw new Error("--run 需要 <mode-id> 和 <用户指令>");
			if (headlessRun) throw new Error("只能指定一次 --run");
			headlessRun = { modeId, request };
			index += 2;
		} else if (argument === "-h" || argument === "--help") {
			helpRequested = true;
		} else if (argument?.startsWith("-")) {
			throw new Error(`未知参数：${argument}`);
		} else if (workspaceProvided) {
			throw new Error("只能指定一个 workspace");
		} else if (argument) {
			workspaceRoot = argument;
			workspaceProvided = true;
		}
	}

	return {
		workspaceRoot: workspaceRoot ? resolve(workspaceRoot) : undefined,
		configDirectory: resolve(configDirectory),
		headlessRun,
		locale: cliLocale ?? parseLocale(process.env.RDK_AGENT_LANG),
		helpRequested,
	};
}

function printHelp(locale: Locale): void {
	console.log(localeText(
		locale,
		"用法: rdk-agent [--lang <zh|en>] [--config-dir <dir>] [--workspace <dir>|workspace] [--run <mode-id> <用户指令>]",
		"Usage: rdk-agent [--lang <zh|en>] [--config-dir <dir>] [--workspace <dir>|workspace] [--run <mode-id> <user-request>]",
	));
	console.log(localeText(
		locale,
		"不指定 workspace 时使用配置中的内置模板托管工作区。",
		"When workspace is omitted, the managed workspace from the bundled template is used.",
	));
}

try {
	const options = parseArgs(process.argv.slice(2));
	if (options.helpRequested) printHelp(options.locale);
	else {
		const configuration = new YamlAgentConfigurationLoader().load(options.configDirectory, options.locale);
		const workspace = new ManagedWorkspaceResolver().resolve(configuration.workspace, options.workspaceRoot);
		if (options.headlessRun) {
			const succeeded = await runHeadless(workspace, configuration, options.headlessRun.modeId, options.headlessRun.request);
			process.exitCode = succeeded ? 0 : 1;
		} else new OrchestrationApp(workspace, configuration).start();
	}
} catch (error) {
	console.error(error instanceof Error ? error.message : String(error));
	process.exit(1);
}
