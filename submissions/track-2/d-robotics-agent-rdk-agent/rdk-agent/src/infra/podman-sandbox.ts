import { spawn } from "node:child_process";
import { relative, resolve, sep } from "node:path";
import type { BashOperations } from "@earendil-works/pi-coding-agent";
import type { PodmanSandboxPlan } from "../domain/agent-profile.ts";

function insideWorkspace(workspaceRoot: string, path: string): string {
	const root = resolve(workspaceRoot);
	const absolute = resolve(path);
	const offset = relative(root, absolute);
	if (offset === ".." || offset.startsWith(`..${sep}`)) {
		throw new Error(`Podman 工作目录越出工作区：${absolute}`);
	}
	return absolute;
}

const containerWorkspaceRoot = "/workspace";

function containerPath(workspaceRoot: string, hostPath: string): string {
	const offset = relative(workspaceRoot, hostPath);
	if (offset === "") return containerWorkspaceRoot;
	return `${containerWorkspaceRoot}/${offset.split(sep).join("/")}`;
}

export function podmanSandboxArguments(
	workspaceRoot: string,
	cwd: string,
	plan: PodmanSandboxPlan,
	command: string,
): string[] {
	const root = resolve(workspaceRoot);
	const workingDirectory = insideWorkspace(root, cwd);
	const containerWorkingDirectory = containerPath(root, workingDirectory);
	// Pi prompts expose the real workspace root, so models may put that absolute
	// path in cd/PYTHONPATH arguments. The Podman VM (notably on macOS) does not
	// guarantee that a deep host path can also be used as a container mount point.
	const containerCommand = command.split(root).join(containerWorkspaceRoot);
	return [
		"run",
		"--rm",
		"--pull=never",
		`--network=${plan.network}`,
		"--cap-drop=all",
		"--security-opt=no-new-privileges",
		"--pids-limit=256",
		"--memory=512m",
		"--cpus=1",
		"--read-only",
		"--tmpfs=/tmp:rw,nosuid,nodev,size=64m",
		"--env=HOME=/tmp",
		"--env=PYTHONDONTWRITEBYTECODE=1",
		`--volume=${root}:${containerWorkspaceRoot}:ro`,
		`--workdir=${containerWorkingDirectory}`,
		plan.image,
		"sh",
		"-lc",
		containerCommand,
	];
}

export function createPodmanSandboxOperations(workspaceRoot: string, plan: PodmanSandboxPlan): BashOperations {
	return {
		exec(command, cwd, { onData, signal, timeout, env }) {
			const args = podmanSandboxArguments(workspaceRoot, cwd, plan, command);
			return new Promise((resolvePromise, reject) => {
				const child = spawn("podman", args, {
					detached: true,
					env: { PATH: env?.PATH ?? process.env.PATH },
					stdio: ["ignore", "pipe", "pipe"],
				});
				let timedOut = false;
				let timeoutHandle: NodeJS.Timeout | undefined;
				const terminate = () => {
					if (!child.pid) return;
					try {
						process.kill(-child.pid, "SIGKILL");
					} catch {
						child.kill("SIGKILL");
					}
				};
				if (timeout !== undefined && timeout > 0) {
					timeoutHandle = setTimeout(() => {
						timedOut = true;
						terminate();
					}, timeout * 1000);
				}
				const abort = () => terminate();
				signal?.addEventListener("abort", abort, { once: true });
				child.stdout?.on("data", onData);
				child.stderr?.on("data", onData);
				child.on("error", (error) => reject(new Error(`无法启动 Podman 测试沙箱：${error.message}`)));
				child.on("close", (code) => {
					if (timeoutHandle) clearTimeout(timeoutHandle);
					signal?.removeEventListener("abort", abort);
					if (signal?.aborted) reject(new Error("Podman 测试沙箱已取消"));
					else if (timedOut) reject(new Error(`Podman 测试沙箱超时：${timeout} 秒`));
					else resolvePromise({ exitCode: code });
				});
			});
		},
	};
}
