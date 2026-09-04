import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import {
  appendEvents,
  ingestClaim,
  ingestGit,
  ingestTestOutput,
  initSession,
  makeEvent,
  readStore,
  rebuildStore,
  sessionPaths,
  type GitIngestMode,
  type OutcomeCandidate,
  type PersistPaths,
  type SessionStore,
  type TestFramework,
} from "airecap-plus";
import type { ToolSpec } from "./llm.js";
import { scanMany, scanText, type PrivacyRisk } from "./privacy.js";
import { buildStructuredReport, renderReportMarkdown, type EvidenceReport } from "./report.js";

const execFileAsync = promisify(execFile);

export interface ToolContext {
  sessionId: string;
  cwd: string;
  root: string;
  modelName?: string;
  lastPrivacyRisks: PrivacyRisk[];
  lastReport?: EvidenceReport;
  lastMarkdown?: string;
}

export const TOOL_SPECS: ToolSpec[] = [
  {
    type: "function",
    function: {
      name: "git_diff",
      description:
        "Collect git changes (worktree/staged/commit) and append file_change evidence to the ledger.",
      parameters: {
        type: "object",
        properties: {
          mode: {
            type: "string",
            enum: ["worktree", "workdir", "staged", "commit"],
            default: "worktree",
          },
          commit: { type: "string", description: "Required when mode=commit" },
        },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "run_tests",
      description: "Run a test command, parse pass/fail, and append test_result evidence.",
      parameters: {
        type: "object",
        properties: {
          cmd: { type: "string", description: "Shell command, e.g. pytest -q tests/auth" },
          framework: {
            type: "string",
            enum: ["auto", "pytest", "vitest", "jest"],
            default: "auto",
          },
        },
        required: ["cmd"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "ingest_test_output",
      description: "Ingest already-captured test runner stdout without re-running tests.",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string" },
          cmd: { type: "string" },
          framework: { type: "string", enum: ["auto", "pytest", "vitest", "jest"] },
          exit_code: { type: "number" },
        },
        required: ["text"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "claim",
      description:
        "Record a user/agent claim about what was done. Does NOT mark verified by itself.",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string" },
          type: {
            type: "string",
            enum: [
              "feature",
              "bugfix",
              "problem",
              "decision",
              "spike",
              "refactor",
              "chore",
              "docs",
              "investigation",
            ],
          },
          kind: {
            type: "string",
            enum: ["completed", "fixed", "implemented", "works_now", "progress", "other"],
          },
          title: { type: "string" },
          actor: { type: "string", enum: ["user", "agent"] },
        },
        required: ["text"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "scan_privacy",
      description:
        "Scan git-changed files or provided text for emails/keys/secrets before public export.",
      parameters: {
        type: "object",
        properties: {
          paths: { type: "array", items: { type: "string" } },
          text: { type: "string" },
        },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "show_outcomes",
      description:
        "Read current L1 outcome ledger (statuses, scope, confidence). Source of truth for what is done.",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "end_session",
      description: "Close session: abandon unevidenced claims and finalize ledger.",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "render_report",
      description:
        "Render a deterministic evidence report from the L1 ledger + privacy risks. Prefer this over free-form claims.",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string" },
          narrative: {
            type: "string",
            description: "Optional short decision narrative; must not invent facts",
          },
        },
      },
    },
  },
];

function parseArgs(raw: string): Record<string, unknown> {
  if (!raw || !raw.trim()) return {};
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return { _parse_error: raw };
  }
}

function pathsOf(ctx: ToolContext): PersistPaths {
  return sessionPaths(ctx.sessionId, { cwd: ctx.cwd, root: ctx.root });
}

async function ensureSession(ctx: ToolContext): Promise<PersistPaths> {
  return initSession(ctx.sessionId, { cwd: ctx.cwd, root: ctx.root });
}

async function loadStore(ctx: ToolContext): Promise<SessionStore> {
  const paths = await ensureSession(ctx);
  const existing = await readStore(paths);
  if (existing) return existing;
  return rebuildStore(ctx.sessionId, { cwd: ctx.cwd, root: ctx.root });
}

async function refreshStore(ctx: ToolContext): Promise<SessionStore> {
  return rebuildStore(ctx.sessionId, { cwd: ctx.cwd, root: ctx.root });
}

function summarizeOutcomes(store: SessionStore) {
  return store.outcomes
    .filter((o) => o.status !== "superseded")
    .map((o: OutcomeCandidate) => ({
      id: o.id,
      title: o.title,
      type: o.type,
      status: o.status,
      confidence: o.confidence,
      paths: o.scope?.paths ?? [],
      commands: o.scope?.commands ?? [],
      anchors: o.verification_anchors ?? [],
      summary_blob: o.summary_blob,
      terminal_reason: o.terminal_reason,
    }));
}

function toGitMode(args: Record<string, unknown>): GitIngestMode {
  const mode = String(args.mode ?? "worktree");
  if (mode === "commit") {
    const sha = args.commit ? String(args.commit) : "";
    if (!sha) throw new Error("commit sha required when mode=commit");
    return { kind: "commit", sha };
  }
  if (mode === "staged") return { kind: "worktree", staged: true };
  // workdir is accepted as alias for worktree
  return { kind: "worktree", staged: false };
}

async function gitChangedPaths(cwd: string): Promise<string[]> {
  try {
    const { stdout } = await execFileAsync("git", ["status", "--porcelain"], {
      cwd,
      windowsHide: true,
    });
    return stdout
      .split(/\r?\n/)
      .map((l) => l.trimEnd())
      .filter(Boolean)
      .map((l) => l.replace(/^\s*[MADRCU?!]{1,2}\s+/, "").replace(/.*\s->\s/, ""))
      .filter(Boolean);
  } catch {
    return [];
  }
}

export async function executeTool(
  ctx: ToolContext,
  name: string,
  rawArgs: string,
): Promise<string> {
  const args = parseArgs(rawArgs);
  if (args._parse_error) {
    return JSON.stringify({
      ok: false,
      error: "invalid_json_arguments",
      raw: args._parse_error,
    });
  }

  try {
    switch (name) {
      case "git_diff": {
        await ensureSession(ctx);
        const mode = toGitMode(args);
        const events = await ingestGit({
          sessionId: ctx.sessionId,
          mode,
          cwd: ctx.cwd,
        });
        if (events.length) {
          await appendEvents(ctx.sessionId, events, { cwd: ctx.cwd, root: ctx.root });
        }
        const store = await refreshStore(ctx);
        const files = events.flatMap((e) => {
          const payload = e.payload as {
            paths?: Array<{ path: string; plus?: number; minus?: number }>;
          };
          return (payload.paths ?? []).map(
            (p) => `${p.path} (+${p.plus ?? 0}/-${p.minus ?? 0})`,
          );
        });
        return JSON.stringify({
          ok: true,
          mode,
          files,
          events_appended: events.length,
          outcomes: summarizeOutcomes(store),
        });
      }
      case "run_tests": {
        await ensureSession(ctx);
        const cmd = String(args.cmd ?? "");
        if (!cmd) return JSON.stringify({ ok: false, error: "cmd_required" });
        const framework = String(args.framework ?? "auto") as TestFramework;
        const candidates = [cmd];
        // Windows often has `python -m pytest` but no bare pytest on PATH.
        if (/^\s*pytest(\s|$)/i.test(cmd)) {
          candidates.push(cmd.replace(/^\s*pytest\b/i, "python -m pytest"));
          candidates.push(cmd.replace(/^\s*pytest\b/i, "py -m pytest"));
        }
        let stdout = "";
        let stderr = "";
        let exitCode = 0;
        let usedCmd = cmd;
        let ran = false;
        for (const candidate of candidates) {
          try {
            const res = await execFileAsync(candidate, [], {
              cwd: ctx.cwd,
              shell: true,
              windowsHide: true,
              maxBuffer: 8 * 1024 * 1024,
              timeout: 180_000,
            });
            stdout = String(res.stdout ?? "");
            stderr = String(res.stderr ?? "");
            usedCmd = candidate;
            exitCode = 0;
            ran = true;
            break;
          } catch (err) {
            const e = err as { stdout?: string; stderr?: string; code?: number | string };
            stdout = String(e.stdout ?? "");
            stderr = String(e.stderr ?? "");
            exitCode = typeof e.code === "number" ? e.code : 1;
            usedCmd = candidate;
            const missing =
              /not recognized|不是内部或外部命令|No module named|cannot find/i.test(
                `${stdout}\n${stderr}`,
              );
            if (!missing) {
              ran = true;
              break;
            }
          }
        }
        if (!ran && !stdout && !stderr) {
          stderr = `failed to run test command candidates: ${candidates.join(" | ")}`;
          exitCode = 1;
        }
        const text = [stdout, stderr].filter(Boolean).join("\n");
        const events = ingestTestOutput({
          sessionId: ctx.sessionId,
          text,
          cmd: usedCmd,
          framework,
          exitCode,
        });
        if (events.length) {
          await appendEvents(ctx.sessionId, events, { cwd: ctx.cwd, root: ctx.root });
        }
        const store = await refreshStore(ctx);
        const payload = (events[0]?.payload ?? {}) as {
          suite_status?: string;
          tests?: Array<{ name: string; status: string }>;
        };
        return JSON.stringify({
          ok: true,
          cmd: usedCmd,
          exit_code: exitCode,
          suite_status: payload.suite_status,
          tests: payload.tests ?? [],
          events_appended: events.length,
          outcomes: summarizeOutcomes(store),
          stdout_tail: text.slice(-2000),
        });
      }
      case "ingest_test_output": {
        await ensureSession(ctx);
        const text = String(args.text ?? "");
        const events = ingestTestOutput({
          sessionId: ctx.sessionId,
          text,
          cmd: args.cmd ? String(args.cmd) : undefined,
          framework: (args.framework ? String(args.framework) : "auto") as TestFramework,
          exitCode: typeof args.exit_code === "number" ? args.exit_code : undefined,
        });
        if (events.length) {
          await appendEvents(ctx.sessionId, events, { cwd: ctx.cwd, root: ctx.root });
        }
        const store = await refreshStore(ctx);
        return JSON.stringify({
          ok: true,
          payload: events[0]?.payload ?? null,
          events_appended: events.length,
          outcomes: summarizeOutcomes(store),
        });
      }
      case "claim": {
        await ensureSession(ctx);
        const text = String(args.text ?? "");
        if (!text) return JSON.stringify({ ok: false, error: "text_required" });
        const event = ingestClaim({
          sessionId: ctx.sessionId,
          text,
          typeHint: args.type ? (String(args.type) as never) : undefined,
          claimKind: args.kind ? (String(args.kind) as never) : undefined,
          titleHint: args.title ? String(args.title) : undefined,
          actor: args.actor === "agent" ? "agent" : "user",
        });
        await appendEvents(ctx.sessionId, [event], { cwd: ctx.cwd, root: ctx.root });
        const store = await refreshStore(ctx);
        return JSON.stringify({
          ok: true,
          note: "Claim recorded. Status will not become verified without test/verification evidence.",
          outcomes: summarizeOutcomes(store),
        });
      }
      case "scan_privacy": {
        let risks: PrivacyRisk[] = [];
        if (typeof args.text === "string" && args.text) {
          risks = scanText(args.text);
        } else {
          const filePaths = Array.isArray(args.paths)
            ? args.paths.map(String)
            : await gitChangedPaths(ctx.cwd);
          const files: Array<{ path: string; content: string }> = [];
          for (const p of filePaths.slice(0, 40)) {
            try {
              const abs = path.isAbsolute(p) ? p : path.join(ctx.cwd, p);
              const content = await readFile(abs, "utf8");
              files.push({ path: p, content });
            } catch {
              // skip missing/binary
            }
          }
          risks = scanMany(files);
        }
        ctx.lastPrivacyRisks = risks;
        return JSON.stringify({ ok: true, risks, risk_count: risks.length });
      }
      case "show_outcomes": {
        const store = await loadStore(ctx);
        return JSON.stringify({
          ok: true,
          session_id: store.session_id,
          focus_outcome_id: store.focus_outcome_id,
          outcomes: summarizeOutcomes(store),
          orphan_event_ids: store.orphan_event_ids,
          store_path: pathsOf(ctx).storePath,
        });
      }
      case "end_session": {
        await ensureSession(ctx);
        const endEvt = makeEvent({
          session_id: ctx.sessionId,
          actor: "system",
          kind: "session_end",
          signal: "high",
          payload: { reason: "normal", apply_ab2: true },
        });
        await appendEvents(ctx.sessionId, [endEvt], { cwd: ctx.cwd, root: ctx.root });
        const store = await refreshStore(ctx);
        return JSON.stringify({ ok: true, outcomes: summarizeOutcomes(store) });
      }
      case "render_report": {
        const store = await loadStore(ctx);
        if (!ctx.lastPrivacyRisks.length) {
          try {
            const filePaths = await gitChangedPaths(ctx.cwd);
            const files: Array<{ path: string; content: string }> = [];
            for (const p of filePaths.slice(0, 40)) {
              try {
                const content = await readFile(path.join(ctx.cwd, p), "utf8");
                files.push({ path: p, content });
              } catch {
                /* ignore */
              }
            }
            ctx.lastPrivacyRisks = scanMany(files);
          } catch {
            /* ignore */
          }
        }
        const report = buildStructuredReport({
          store,
          privacyRisks: ctx.lastPrivacyRisks,
          model: ctx.modelName,
          title: args.title ? String(args.title) : undefined,
          narrative: args.narrative ? String(args.narrative) : undefined,
        });
        const markdown = renderReportMarkdown(report);
        ctx.lastReport = report;
        ctx.lastMarkdown = markdown;
        return JSON.stringify({ ok: true, report, markdown });
      }
      default:
        return JSON.stringify({ ok: false, error: `unknown_tool:${name}` });
    }
  } catch (err) {
    return JSON.stringify({
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    });
  }
}
