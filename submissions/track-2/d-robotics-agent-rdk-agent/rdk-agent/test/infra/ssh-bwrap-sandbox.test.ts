import assert from "node:assert/strict";
import test from "node:test";
import { sshBwrapArchiveArguments, sshBwrapRemoteScript } from "../../src/infra/ssh-bwrap-sandbox.ts";

const plan = {
	kind: "ssh-bwrap",
	host: "x5-root",
	remoteRoot: "/userdata/rdk-agent/runs",
	network: "none",
	hardwareAccess: false,
	commandTimeoutSeconds: 30,
} as const;

test("board sandbox snapshots the workspace and exposes only a read-only, hardware-free runtime", () => {
	const script = sshBwrapRemoteScript(
		"/tmp/workspace",
		"/tmp/workspace/examples/plugins/servo",
		plan,
		"cd /tmp/workspace && PYTHONPATH=/tmp/workspace python3 -m unittest",
		"01234567-89ab-cdef-0123-456789abcdef",
		42,
	);
	assert.match(script, /run_dir='\/userdata\/rdk-agent\/runs\/01234567-89ab-cdef-0123-456789abcdef'/);
	assert.match(script, /trap cleanup EXIT HUP INT TERM/);
	assert.match(script, /--unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-net/);
	assert.match(script, /--uid 65534 --gid 65534 --clearenv/);
	assert.match(script, /--ro-bind "\$run_dir" \/workspace/);
	assert.match(script, /--chdir '\/workspace\/examples\/plugins\/servo'/);
	assert.match(script, /\[rdk-agent 沙箱\] backend=ssh-bwrap target=x5-root/);
	assert.match(script, /uid=%s network=none hardware=none/);
	assert.match(script, /cd \/workspace && PYTHONPATH=\/workspace python3 -m unittest/);
	assert.match(script, /MemoryMax=512M/);
	assert.match(script, /RuntimeMaxSec=42s/);
	assert.doesNotMatch(script, /--ro-bind \/ \/(?:\s|$)/);
	assert.doesNotMatch(script, /\/sys|\/dev\/gpio|\/dev\/mem|spidev/);
});

test("board sandbox archive excludes local build and dependency directories", () => {
	const args = sshBwrapArchiveArguments("/tmp/workspace");
	assert.deepEqual(args.slice(0, 2), ["-C", "/tmp/workspace"]);
	assert.ok(args.includes("--no-xattrs"));
	assert.ok(args.includes("--exclude=.git"));
	assert.ok(args.includes("--exclude=node_modules"));
	assert.ok(args.includes("--exclude=target"));
	assert.equal(args.at(-1), ".");
});

test("board sandbox rejects a working directory outside the workspace", () => {
	assert.throws(
		() => sshBwrapRemoteScript("/tmp/workspace", "/tmp/other", plan, "pwd", "0123abcd", 30),
		/越出工作区/,
	);
});
