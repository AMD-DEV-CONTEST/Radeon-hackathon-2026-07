import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { relative, resolve, sep } from "node:path";
import type { BashOperations } from "@earendil-works/pi-coding-agent";
import type { SshBwrapSandboxPlan } from "../domain/agent-profile.ts";

const sandboxWorkspaceRoot = "/workspace";

function shellQuote(value: string): string {
	return `'${value.replaceAll("'", `'"'"'`)}'`;
}

function validatePlan(plan: SshBwrapSandboxPlan): void {
	if (!/^[A-Za-z0-9._-]+$/.test(plan.host)) throw new Error("SSH bwrap host 格式不安全");
	if (!/^\/(?:[A-Za-z0-9._-]+\/)*[A-Za-z0-9._-]+$/.test(plan.remoteRoot)
		|| plan.remoteRoot.split("/").some((part) => part === "." || part === "..")) {
		throw new Error("SSH bwrap remoteRoot 必须是安全的板端绝对路径");
	}
	if (plan.network !== "none" || plan.hardwareAccess !== false) {
		throw new Error("SSH bwrap 开发沙箱必须断网且禁止硬件访问");
	}
	if (!Number.isInteger(plan.commandTimeoutSeconds) || plan.commandTimeoutSeconds <= 0) {
		throw new Error("SSH bwrap 单条命令超时必须是正整数");
	}
}

function workspaceLocation(workspaceRoot: string, path: string): { host: string; sandbox: string } {
	const root = resolve(workspaceRoot);
	const host = resolve(path);
	const offset = relative(root, host);
	if (offset === ".." || offset.startsWith(`..${sep}`)) {
		throw new Error(`板端 bwrap 工作目录越出工作区：${host}`);
	}
	return {
		host,
		sandbox: offset === "" ? sandboxWorkspaceRoot : `${sandboxWorkspaceRoot}/${offset.split(sep).join("/")}`,
	};
}

export function sshBwrapArchiveArguments(workspaceRoot: string): string[] {
	return [
		"-C",
		resolve(workspaceRoot),
		"--no-xattrs",
		"--exclude=.git",
		"--exclude=node_modules",
		"--exclude=target",
		"--exclude=__pycache__",
		"-cf",
		"-",
		".",
	];
}

export function sshBwrapRemoteScript(
	workspaceRoot: string,
	cwd: string,
	plan: SshBwrapSandboxPlan,
	command: string,
	runId: string,
	timeoutSeconds: number,
): string {
	validatePlan(plan);
	if (!/^[a-f0-9-]+$/.test(runId)) throw new Error("SSH bwrap run id 格式不安全");
	const root = resolve(workspaceRoot);
	const workingDirectory = workspaceLocation(root, cwd);
	const sandboxCommand = command.split(root).join(sandboxWorkspaceRoot);
	const instrumentedCommand = `printf '[rdk-agent 沙箱] backend=ssh-bwrap target=${plan.host} cwd=%s uid=%s network=none hardware=none\\n' "$PWD" "$(id -u)"\n${sandboxCommand}`;
	const remoteRoot = plan.remoteRoot.replace(/\/$/, "");
	const runDirectory = `${remoteRoot}/${runId}`;
	const stagingDirectory = `${runDirectory}.staging`;
	const unitName = `rdk-agent-sandbox-${runId.replaceAll("-", "")}`;
	const runtimeLimit = Math.max(1, Math.ceil(timeoutSeconds));

	return `set -eu
umask 022
remote_root=${shellQuote(remoteRoot)}
run_dir=${shellQuote(runDirectory)}
staging_dir=${shellQuote(stagingDirectory)}
cleanup() {
  rm -rf -- "$staging_dir" "$run_dir"
}
trap cleanup EXIT HUP INT TERM
mkdir -p -- "$remote_root"
rm -rf -- "$staging_dir" "$run_dir"
mkdir -- "$staging_dir"
tar --no-same-owner --no-same-permissions -xf - -C "$staging_dir"
chmod -R u=rwX,go=rX "$staging_dir"
mv -- "$staging_dir" "$run_dir"
set +e
systemd-run --quiet --wait --pipe --collect \
  --unit ${shellQuote(unitName)} \
  -p MemoryMax=512M -p CPUQuota=100% -p TasksMax=256 \
  -p RuntimeMaxSec=${runtimeLimit}s -p TimeoutStopSec=5s \
  bwrap --die-with-parent --new-session \
  --unshare-user --unshare-pid --unshare-ipc --unshare-uts --unshare-net \
  --uid 65534 --gid 65534 --clearenv \
  --setenv PATH /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  --setenv HOME /tmp --setenv PYTHONDONTWRITEBYTECODE 1 \
  --ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib \
  --dir /etc --ro-bind /etc/ld.so.cache /etc/ld.so.cache \
  --proc /proc --dev /dev --tmpfs /tmp \
  --ro-bind "$run_dir" ${sandboxWorkspaceRoot} \
  --chdir ${shellQuote(workingDirectory.sandbox)} \
  sh -lc ${shellQuote(instrumentedCommand)}
status=$?
set -e
exit "$status"`;
}

function killProcessGroup(child: ChildProcess): void {
	if (!child.pid) return;
	try {
		process.kill(-child.pid, "SIGKILL");
	} catch {
		child.kill("SIGKILL");
	}
}

/** Streams the latest host workspace snapshot to a disposable, hardware-free board sandbox. */
export function createSshBwrapSandboxOperations(
	workspaceRoot: string,
	plan: SshBwrapSandboxPlan,
): BashOperations {
	validatePlan(plan);
	return {
		exec(command, cwd, { onData, signal, timeout, env }) {
			const runId = randomUUID();
			const requestedTimeout = timeout !== undefined && timeout > 0 ? timeout : 300;
			const commandTimeout = Math.min(requestedTimeout, plan.commandTimeoutSeconds);
			// Let systemd-run report the command timeout before killing the SSH transport.
			const transportTimeout = Math.min(requestedTimeout, commandTimeout + 10);
			const remoteScript = sshBwrapRemoteScript(
				workspaceRoot,
				cwd,
				plan,
				command,
				runId,
				commandTimeout,
			);
			return new Promise((resolvePromise, reject) => {
				const childEnvironment = {
					...process.env,
					PATH: env?.PATH ?? process.env.PATH,
					// macOS installations commonly export C.UTF-8 even when bsdtar only
					// knows C; normalize it so Agent logs contain test output, not locale noise.
					LC_ALL: "C",
				};
				const remote = spawn(
					"ssh",
					["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", plan.host, remoteScript],
					{ detached: true, env: childEnvironment, stdio: ["pipe", "pipe", "pipe"] },
				);
				const archive = spawn("tar", sshBwrapArchiveArguments(workspaceRoot), {
					detached: true,
					env: childEnvironment,
					stdio: ["ignore", "pipe", "pipe"],
				});
				archive.stdout?.pipe(remote.stdin!);
				// SSH may reject before tar reaches EOF; the close handlers below carry
				// the useful exit status, so suppress a redundant EPIPE exception.
				remote.stdin?.on("error", () => undefined);

				let archiveCode: number | null | undefined;
				let remoteCode: number | null | undefined;
				let settled = false;
				let timedOut = false;
				let timeoutHandle: NodeJS.Timeout | undefined;

				const terminate = () => {
					killProcessGroup(archive);
					killProcessGroup(remote);
				};
				const fail = (error: Error) => {
					if (settled) return;
					settled = true;
					if (timeoutHandle) clearTimeout(timeoutHandle);
					signal?.removeEventListener("abort", abort);
					terminate();
					reject(error);
				};
				const finish = () => {
					if (settled || archiveCode === undefined || remoteCode === undefined) return;
					settled = true;
					if (timeoutHandle) clearTimeout(timeoutHandle);
					signal?.removeEventListener("abort", abort);
					if (signal?.aborted) reject(new Error("板端 bwrap 测试沙箱已取消"));
					else if (timedOut) reject(new Error(`板端 bwrap 测试沙箱传输超时：${transportTimeout} 秒（单条命令上限 ${commandTimeout} 秒）`));
					else resolvePromise({ exitCode: remoteCode === 0 ? archiveCode : remoteCode });
				};
				const abort = () => terminate();

				if (transportTimeout > 0) {
					timeoutHandle = setTimeout(() => {
						timedOut = true;
						terminate();
					}, transportTimeout * 1_000);
				}
				signal?.addEventListener("abort", abort, { once: true });
				remote.stdout?.on("data", onData);
				remote.stderr?.on("data", onData);
				archive.stderr?.on("data", onData);
				remote.on("error", (error) => fail(new Error(`无法启动板端 bwrap 测试沙箱：${error.message}`)));
				archive.on("error", (error) => fail(new Error(`无法打包板端测试快照：${error.message}`)));
				remote.on("close", (code) => {
					remoteCode = code;
					finish();
				});
				archive.on("close", (code) => {
					archiveCode = code;
					finish();
				});
			});
		},
	};
}
