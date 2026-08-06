import assert from "node:assert/strict";
import test from "node:test";
import { podmanSandboxArguments } from "../../src/infra/podman-sandbox.ts";

const plan = { kind: "podman", image: "python:3.12-slim", network: "none" } as const;

test("Podman sandbox is offline, resource-limited and mounts only the workspace read-only", () => {
	const args = podmanSandboxArguments(
		"/tmp/workspace",
		"/tmp/workspace/examples",
		plan,
		"cd /tmp/workspace && PYTHONPATH=/tmp/workspace/examples python3 -m unittest",
	);
	assert.ok(args.includes("--network=none"));
	assert.ok(args.includes("--cap-drop=all"));
	assert.ok(args.includes("--read-only"));
	assert.ok(args.includes("--volume=/tmp/workspace:/workspace:ro"));
	assert.ok(args.includes("--workdir=/workspace/examples"));
	assert.ok(args.includes("--env=PYTHONDONTWRITEBYTECODE=1"));
	assert.equal(args.at(-4), "python:3.12-slim");
	assert.equal(args.at(-1), "cd /workspace && PYTHONPATH=/workspace/examples python3 -m unittest");
});

test("Podman sandbox rejects a working directory outside the workspace", () => {
	assert.throws(
		() => podmanSandboxArguments("/tmp/workspace", "/tmp/other", plan, "pwd"),
		/越出工作区/,
	);
});
