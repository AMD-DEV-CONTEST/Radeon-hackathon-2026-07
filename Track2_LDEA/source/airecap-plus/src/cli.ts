#!/usr/bin/env node
/**
 * S-tier CLI:
 *   airecap init|append|replay|show|list
 *   airecap ingest-git   <session_id> [--staged|--commit sha|--range a b]
 *   airecap ingest-test  <session_id> [file|-] [--framework auto|pytest|vitest|jest]
 *   airecap claim        <session_id> <text...> [--type bugfix] [--kind fixed]
 *   airecap end          <session_id>
 *
 * Root dir: ./.airecap  (override with --root <path>)
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  ingestClaim,
  ingestGit,
  ingestTestOutput,
  parseClaimKind,
  parseOutcomeType,
  type GitIngestMode,
  type TestFramework,
} from "./ingest/index.js";
import {
  appendEvents,
  initSession,
  listSessions,
  loadEventsFromFile,
  rebuildStore,
  readEvents,
  readStore,
  sessionPaths,
} from "./persist.js";
import type { Event, OutcomeCandidate } from "./types.js";
import { makeEvent } from "./ingest/ids.js";

function usage(code = 1): never {
  const msg = `airecap — L0/L1 session tool (rules@1.2)

Usage:
  airecap init <session_id>
  airecap append <session_id> <file|->
  airecap replay <session_id>
  airecap show <session_id> [--json]
  airecap list
  airecap end <session_id>

Ingest:
  airecap ingest-git <session_id> [--staged | --commit <sha> | --range <a> <b>]
                                  [--cwd <repo>] [--outcome <id>] [--revert] [--dry-run]
  airecap ingest-test <session_id> [file|-]
                                  [--framework auto|pytest|vitest|jest]
                                  [--cmd <repro>] [--exit-code <n>]
                                  [--outcome <id>] [--dry-run]
  airecap claim <session_id> <text...>
                                  [--type bugfix|feature|...] [--kind fixed|progress|...]
                                  [--title <t>] [--scope p1,p2] [--outcome <id>]
                                  [--actor user|agent] [--dry-run]

Options:
  --root <path>   Data root (default: ./.airecap)
  --cwd <path>    Working directory (git repo / relative --root)
  -h, --help      Show help
`;
  console.error(msg);
  process.exit(code);
}

type Flags = Record<string, string | boolean | string[]>;

function parseArgs(argv: string[]) {
  const flags: Flags = {};
  const pos: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "-h" || a === "--help") flags.help = true;
    else if (
      a === "--json" ||
      a === "--dry-run" ||
      a === "--staged" ||
      a === "--revert"
    ) {
      flags[a.slice(2)] = true;
    } else if (
      a === "--root" ||
      a === "--cwd" ||
      a === "--commit" ||
      a === "--framework" ||
      a === "--cmd" ||
      a === "--exit-code" ||
      a === "--outcome" ||
      a === "--type" ||
      a === "--kind" ||
      a === "--title" ||
      a === "--scope" ||
      a === "--actor"
    ) {
      const v = argv[++i];
      if (!v) usage();
      flags[a.slice(2)] = v;
    } else if (a === "--range") {
      const from = argv[++i];
      const to = argv[++i];
      if (!from || !to) usage();
      flags.range = [from, to];
    } else if (a.startsWith("--")) {
      console.error(`unknown flag: ${a}`);
      usage();
    } else pos.push(a);
  }
  return { flags, pos };
}

function rootOpts(flags: Flags) {
  return {
    cwd: typeof flags.cwd === "string" ? flags.cwd : process.cwd(),
    root: typeof flags.root === "string" ? flags.root : undefined,
  };
}

function flagStr(flags: Flags, k: string): string | undefined {
  const v = flags[k];
  return typeof v === "string" ? v : undefined;
}

function printOutcomes(outcomes: OutcomeCandidate[]): void {
  if (outcomes.length === 0) {
    console.log("(no outcomes)");
    return;
  }
  for (const o of outcomes) {
    const conf = `${o.confidence.toFixed(2)} raw=${o.confidence_raw.toFixed(2)} clamp=${o.clamp_reason}`;
    console.log(
      `- [${o.status}] ${o.type} ${o.title}  (${o.id})  conf ${conf}`,
    );
    if (o.terminal_reason) console.log(`    terminal: ${o.terminal_reason}`);
    if (o.scope.paths.length) {
      console.log(
        `    paths: ${o.scope.paths.slice(0, 8).join(", ")}${o.scope.paths.length > 8 ? "…" : ""}`,
      );
    }
    console.log(`    ${o.summary_blob}`);
  }
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString("utf8");
}

async function parseAppendInput(src: string): Promise<Event[]> {
  if (src === "-") {
    const text = (await readStdin()).trim();
    if (!text) return [];
    if (text.startsWith("[")) return JSON.parse(text) as Event[];
    if (text.startsWith("{") && !text.includes("\n{")) {
      return [JSON.parse(text) as Event];
    }
    return text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => JSON.parse(l) as Event);
  }
  const abs = path.resolve(src);
  return loadEventsFromFile(abs);
}

async function commitEvents(
  sid: string,
  events: Event[],
  opts: { cwd: string; root?: string },
  dryRun: boolean,
): Promise<void> {
  if (events.length === 0) {
    console.error("no events produced");
    process.exit(2);
  }
  for (const e of events) {
    if (!e.session_id) (e as { session_id: string }).session_id = sid;
  }
  if (dryRun) {
    for (const e of events) console.log(JSON.stringify(e));
    return;
  }
  const { paths, store, appended } = await appendEvents(sid, events, opts);
  console.log(`appended ${appended}/${events.length} → ${paths.eventsPath}`);
  console.log(
    `store: ${store.outcomes.length} outcomes, status=${store.status}, focus=${store.focus_outcome_id ?? "—"}`,
  );
  printOutcomes(store.outcomes);
}

async function main(): Promise<void> {
  const { flags, pos } = parseArgs(process.argv.slice(2));
  if (flags.help || pos.length === 0) usage(flags.help ? 0 : 1);

  const cmd = pos[0]!;
  const opts = rootOpts(flags);
  const dryRun = flags["dry-run"] === true;

  if (cmd === "list") {
    const ids = await listSessions(opts);
    if (ids.length === 0) console.log("(no sessions)");
    else for (const id of ids) console.log(id);
    return;
  }

  if (cmd === "init") {
    const sid = pos[1];
    if (!sid) usage();
    const paths = await initSession(sid, opts);
    console.log(`initialized ${paths.sessionDir}`);
    return;
  }

  if (cmd === "append") {
    const sid = pos[1];
    const file = pos[2];
    if (!sid || !file) usage();
    const events = await parseAppendInput(file);
    await commitEvents(sid, events, opts, dryRun);
    return;
  }

  if (cmd === "replay") {
    const sid = pos[1];
    if (!sid) usage();
    const store = await rebuildStore(sid, opts);
    const paths = sessionPaths(sid, opts);
    const n = (await readEvents(paths)).length;
    console.log(`replayed ${n} events → ${paths.storePath}`);
    console.log(
      `store: ${store.outcomes.length} outcomes, status=${store.status}`,
    );
    printOutcomes(store.outcomes);
    return;
  }

  if (cmd === "show") {
    const sid = pos[1];
    if (!sid) usage();
    const paths = sessionPaths(sid, opts);
    let store = await readStore(paths);
    if (!store) store = await rebuildStore(sid, opts);
    if (flags.json) {
      console.log(JSON.stringify(store, null, 2));
      return;
    }
    console.log(
      `session ${store.session_id}  [${store.status}]  ${store.aggregator_version}`,
    );
    console.log(
      `events_seen=${store.counters.events_seen} high=${store.counters.high_signal_seen} orphans=${store.orphan_event_ids.length}`,
    );
    console.log(
      `focus=${store.focus_outcome_id ?? "—"}  active_goal=${store.active_goal_id ?? "—"}`,
    );
    if (store.goals.length) {
      console.log("goals:");
      for (const g of store.goals) {
        console.log(`  - [${g.status}] ${g.statement.slice(0, 80)}`);
      }
    }
    console.log("outcomes:");
    printOutcomes(store.outcomes);
    return;
  }

  if (cmd === "end") {
    const sid = pos[1];
    if (!sid) usage();
    const ev = makeEvent({
      session_id: sid,
      actor: "system",
      kind: "session_end",
      payload: { reason: "normal", apply_ab2: true },
    });
    await commitEvents(sid, [ev], opts, dryRun);
    return;
  }

  if (cmd === "ingest-git") {
    const sid = pos[1];
    if (!sid) usage();
    let mode: GitIngestMode = { kind: "worktree", staged: false };
    if (flags.staged) mode = { kind: "worktree", staged: true };
    const commit = flagStr(flags, "commit");
    if (commit) mode = { kind: "commit", sha: commit };
    if (Array.isArray(flags.range)) {
      mode = { kind: "range", from: flags.range[0]!, to: flags.range[1]! };
    }
    const events = await ingestGit({
      sessionId: sid,
      cwd: opts.cwd,
      mode,
      isRevert: flags.revert === true,
      outcomeId: flagStr(flags, "outcome"),
    });
    await commitEvents(sid, events, opts, dryRun);
    return;
  }

  if (cmd === "ingest-test") {
    const sid = pos[1];
    if (!sid) usage();
    const src = pos[2] ?? "-";
    const text =
      src === "-"
        ? await readStdin()
        : await readFile(path.resolve(opts.cwd, src), "utf8");
    const fw = (flagStr(flags, "framework") ?? "auto") as TestFramework;
    const exitRaw = flagStr(flags, "exit-code");
    const events = ingestTestOutput({
      sessionId: sid,
      text,
      framework: fw,
      cmd: flagStr(flags, "cmd"),
      exitCode: exitRaw !== undefined ? Number(exitRaw) : undefined,
      outcomeId: flagStr(flags, "outcome"),
    });
    await commitEvents(sid, events, opts, dryRun);
    return;
  }

  if (cmd === "claim") {
    const sid = pos[1];
    const textParts = pos.slice(2);
    if (!sid || textParts.length === 0) usage();
    const text = textParts.join(" ");
    const type = parseOutcomeType(flagStr(flags, "type"));
    const kind = parseClaimKind(flagStr(flags, "kind"));
    if (flagStr(flags, "type") && !type) {
      console.error(`invalid --type ${flagStr(flags, "type")}`);
      process.exit(2);
    }
    if (flagStr(flags, "kind") && !kind) {
      console.error(`invalid --kind ${flagStr(flags, "kind")}`);
      process.exit(2);
    }
    const scopeRaw = flagStr(flags, "scope");
    const actorRaw = flagStr(flags, "actor");
    const actor =
      actorRaw === "agent" || actorRaw === "user" ? actorRaw : "user";
    const ev = ingestClaim({
      sessionId: sid,
      text,
      claimKind: kind,
      typeHint: type,
      titleHint: flagStr(flags, "title"),
      outcomeId: flagStr(flags, "outcome"),
      scopePaths: scopeRaw
        ? scopeRaw
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        : undefined,
      actor,
    });
    await commitEvents(sid, [ev], opts, dryRun);
    return;
  }

  console.error(`unknown command: ${cmd}`);
  usage();
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
