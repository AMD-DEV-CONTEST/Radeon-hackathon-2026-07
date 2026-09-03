#!/usr/bin/env node
/**
 * Run one command through an existing Jupyter terminal websocket.
 *
 * The command runs in a subshell so `exit` cannot close the interactive
 * terminal. This helper attaches to an already-running terminal and closes
 * only its own websocket connection. It never creates, interrupts, or shuts
 * down a remote terminal process.
 */

import { randomUUID } from "node:crypto";

function usage() {
  return [
    "Usage:",
    "  run_jupyter_terminal_command.mjs --url <wss-url> --command <shell> [--timeout-ms <ms>]",
    "",
    "The remote command's exit code becomes this process's exit code.",
  ].join("\n");
}

function parseArgs(argv) {
  const result = {
    command: null,
    timeoutMs: 600_000,
    url: null,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      process.stdout.write(`${usage()}\n`);
      process.exit(0);
    }
    const value = argv[index + 1];
    if (argument === "--url" || argument === "--command" || argument === "--timeout-ms") {
      if (value === undefined) {
        throw new Error(`missing value for ${argument}`);
      }
      index += 1;
      if (argument === "--url") {
        result.url = value;
      } else if (argument === "--command") {
        result.command = value;
      } else {
        result.timeoutMs = Number(value);
      }
      continue;
    }
    throw new Error(`unknown argument: ${argument}`);
  }
  if (typeof result.url !== "string" || !result.url.startsWith("wss://")) {
    throw new Error("--url must be a wss:// URL");
  }
  if (typeof result.command !== "string" || result.command.length === 0) {
    throw new Error("--command must be non-empty");
  }
  if (!Number.isInteger(result.timeoutMs) || result.timeoutMs < 1_000) {
    throw new Error("--timeout-ms must be an integer of at least 1000");
  }
  return result;
}

function stripAnsi(value) {
  return value.replace(
    // ANSI CSI and OSC sequences emitted by xterm/bash prompts.
    // eslint-disable-next-line no-control-regex
    /\u001b(?:\][^\u0007]*(?:\u0007|\u001b\\)|\[[0-?]*[ -/]*[@-~])/g,
    "",
  );
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const nonce = randomUUID().replaceAll("-", "");
  const startMarker = `__MANTIS_TERMINAL_START_${nonce}__`;
  const doneMarker = `__MANTIS_TERMINAL_DONE_${nonce}__`;
  const payload = [
    `printf '\\n${startMarker}\\n'`,
    "(",
    args.command,
    ")",
    "__mantis_terminal_rc=$?",
    `printf '\\n${doneMarker}%s\\n' "$__mantis_terminal_rc"`,
    "",
  ].join("\n");

  await new Promise((resolve, reject) => {
    const socket = new WebSocket(args.url);
    let settled = false;
    let started = false;
    let output = "";
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        socket.close();
        const error = new Error(`remote command timed out after ${args.timeoutMs} ms`);
        error.exitCode = 124;
        reject(error);
      }
    }, args.timeoutMs);

    function finish(error, exitCode) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      socket.close();
      if (error) {
        reject(error);
      } else {
        process.exitCode = exitCode;
        resolve();
      }
    }

    socket.addEventListener("open", () => {
      socket.send(JSON.stringify(["stdin", payload.replaceAll("\n", "\r")]));
    });
    socket.addEventListener("message", (event) => {
      let frame;
      try {
        frame = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (!Array.isArray(frame) || frame[0] !== "stdout" || typeof frame[1] !== "string") {
        return;
      }
      output += stripAnsi(frame[1]).replaceAll("\r", "");
      const startBoundary = `\n${startMarker}\n`;
      if (!started && output.includes(startBoundary)) {
        started = true;
        output = output.slice(output.indexOf(startBoundary) + startBoundary.length);
      }
      if (!started) {
        return;
      }
      const match = output.match(new RegExp(`\\n${doneMarker}(\\d+)\\n`));
      if (match) {
        process.stdout.write(output.slice(0, match.index));
        finish(null, Number(match[1]));
        return;
      }
      const retainedLength = doneMarker.length + 16;
      if (output.length > retainedLength) {
        process.stdout.write(output.slice(0, -retainedLength));
        output = output.slice(-retainedLength);
      }
    });
    socket.addEventListener("error", () => {
      const error = new Error("Jupyter terminal websocket error");
      error.exitCode = 125;
      finish(error);
    });
    socket.addEventListener("close", () => {
      if (!settled) {
        const error = new Error("Jupyter terminal websocket closed before the receipt marker");
        error.exitCode = 125;
        finish(error);
      }
    });
  });
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = Number.isInteger(error.exitCode) ? error.exitCode : 2;
});
