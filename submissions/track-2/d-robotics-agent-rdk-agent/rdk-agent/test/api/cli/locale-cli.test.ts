import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { join, resolve } from "node:path";
import test from "node:test";

const projectDirectory = resolve(import.meta.dirname, "../../..");
const launcher = join(projectDirectory, "deploy/rdk-agent");

function runHelp(args: readonly string[], environmentLocale?: string): string {
	const environment: NodeJS.ProcessEnv = { ...process.env };
	delete environment.RDK_AGENT_LANG;
	if (environmentLocale !== undefined) environment.RDK_AGENT_LANG = environmentLocale;
	const result = spawnSync(launcher, args, {
		cwd: projectDirectory,
		encoding: "utf8",
		env: environment,
	});
	assert.equal(result.status, 0, result.stderr);
	return result.stdout;
}

test("launcher help defaults to Chinese and accepts RDK_AGENT_LANG", () => {
	assert.match(runHelp(["--help"]), /^\u7528\u6cd5: rdk-agent/mu);
	assert.match(runHelp(["--help"], "en"), /^Usage: rdk-agent/mu);
});

test("--lang takes precedence over the environment regardless of option order", () => {
	assert.match(runHelp(["--lang", "en", "--help"], "zh"), /^Usage: rdk-agent/mu);
	assert.match(runHelp(["--help", "--lang", "en"], "invalid-environment-value"), /^Usage: rdk-agent/mu);
	assert.match(runHelp(["--lang", "zh", "--help"], "en"), /^\u7528\u6cd5: rdk-agent/mu);
});
