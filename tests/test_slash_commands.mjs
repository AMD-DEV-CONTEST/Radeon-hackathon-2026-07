// ──────────────────────────────────────────────────────────────────────────
// MKO Slash Commands — Node test runner. Verifies the actual JS parser
// (no Python mirror, no fake reimplementation).
//
// Run:   node --test tests/test_slash_commands.mjs
// ──────────────────────────────────────────────────────────────────────────

import { test } from "node:test";
import assert from "node:assert/strict";

import slashModule from "../mko/webui/static/js/slash-commands.js";
// In Node, CommonJS module.exports is exposed as the default import.
const MKOSlash = slashModule.default ?? slashModule;

test("plain chat text returns null (no command)", () => {
  assert.equal(MKOSlash.parse("Hello world"), null);
  assert.equal(MKOSlash.parse("   not a slash command"), null);
});

test("non-string inputs return null", () => {
  assert.equal(MKOSlash.parse(null), null);
  assert.equal(MKOSlash.parse(undefined), null);
  assert.equal(MKOSlash.parse(42), null);
  assert.equal(MKOSlash.parse({}), null);
  assert.equal(MKOSlash.parse(""), null);
  // whitespace-only string after trim → null because it doesn't start with /
  assert.equal(MKOSlash.parse("   "), null);
});

test("slash mid-sentence is plain chat (commands must anchor the start)", () => {
  // Genuine mid-sentence slashes are NOT commands.
  assert.equal(MKOSlash.parse("Hello /plan foo"), null);
  assert.equal(MKOSlash.parse("I went to /the store"), null);
});

test("anchored slash with no whitespace is parsed as an unknown command", () => {
  // `/plan/inside` has no whitespace after the leading slash, so the
  // whole token is the command token. "plan/inside" isn't a known
  // command, so the parser returns {type: 'unknown'} (the chat layer
  // will surface a warning and fall through to plain chat).
  assert.deepEqual(MKOSlash.parse("/plan/inside"), {
    type: "unknown",
    cmd: "plan/inside",
    rest: "",
  });
});

test("bare / and /  are empty", () => {
  assert.deepEqual(MKOSlash.parse("/"), { type: "empty" });
  assert.deepEqual(MKOSlash.parse("/  "), { type: "empty" });
});

test("/plan <topic> → plan with agent 'planner'", () => {
  assert.deepEqual(MKOSlash.parse("/plan Ship the demo"), {
    type: "plan",
    cmd: "plan",
    topic: "Ship the demo",
    agent: "planner",
  });
});

test("/plan with no topic is plan_empty", () => {
  assert.deepEqual(MKOSlash.parse("/plan"), { type: "plan_empty", cmd: "plan" });
  assert.deepEqual(MKOSlash.parse("/plan   "), { type: "plan_empty", cmd: "plan" });
});

test("/plan preserves case in the seeded topic", () => {
  const out = MKOSlash.parse("/plan BMK Track 2 Submission");
  assert.equal(out.topic, "BMK Track 2 Submission");
});

test("/research <query> → research with agent 'research'", () => {
  assert.deepEqual(MKOSlash.parse("/research What is ROCm"), {
    type: "research",
    cmd: "research",
    query: "What is ROCm",
    agent: "research",
  });
});

test("/research with no query is research_empty", () => {
  assert.deepEqual(MKOSlash.parse("/research"), { type: "research_empty", cmd: "research" });
});

test("/summary <text> → summary with agent 'general'", () => {
  assert.deepEqual(MKOSlash.parse("/summary Some long essay to summarize."), {
    type: "summary",
    cmd: "summary",
    text: "Some long essay to summarize.",
    agent: "general",
  });
});

test("/summary with no text is summary_empty", () => {
  assert.deepEqual(MKOSlash.parse("/summary   "), { type: "summary_empty", cmd: "summary" });
});

test("/model <provider>/<model>", () => {
  assert.deepEqual(MKOSlash.parse("/model groq/llama-3.1-8b-instant"), {
    type: "model",
    cmd: "model",
    provider: "groq",
    model: "llama-3.1-8b-instant",
  });
});

test("/model <provider> only (no model → default)", () => {
  assert.deepEqual(MKOSlash.parse("/model ollama"), {
    type: "model",
    cmd: "model",
    provider: "ollama",
    model: null,
  });
});

test("/model trailing slash stripped (provider only)", () => {
  assert.deepEqual(MKOSlash.parse("/model groq/"), {
    type: "model",
    cmd: "model",
    provider: "groq",
    model: null,
  });
});

test("/model multi-slash keeps everything-after-first-slash in model", () => {
  // Realistic model names never contain slashes, but the parser
  // explicitly leaves it verbatim after the first slash.
  assert.deepEqual(MKOSlash.parse("/model groq/foo/bar"), {
    type: "model",
    cmd: "model",
    provider: "groq",
    model: "foo/bar",
  });
});

test("/model multiple trailing slashes all collapse to null model", () => {
  // Design pin — pin this so a future refactor doesn't accidentally
  // stop the collapse or extend it weirdly.
  assert.deepEqual(MKOSlash.parse("/model groq//"), {
    type: "model", cmd: "model", provider: "groq", model: null,
  });
  assert.deepEqual(MKOSlash.parse("/model groq///"), {
    type: "model", cmd: "model", provider: "groq", model: null,
  });
});

test("/model with unknown provider", () => {
  assert.deepEqual(MKOSlash.parse("/model notreal/foo"), {
    type: "model_unknown_provider",
    cmd: "model",
    provider: "notreal",
    model: "foo",
  });
  assert.deepEqual(MKOSlash.parse("/model notreal"), {
    type: "model_unknown_provider",
    cmd: "model",
    provider: "notreal",
    model: null,
  });
});

test("/provider known and unknown", () => {
  assert.deepEqual(MKOSlash.parse("/provider ollama"), {
    type: "provider",
    cmd: "provider",
    provider: "ollama",
  });
  assert.deepEqual(MKOSlash.parse("/provider notreal"), {
    type: "provider_unknown",
    cmd: "provider",
    provider: "notreal",
  });
});

test("/provider and /model with no arg are *empty types", () => {
  assert.deepEqual(MKOSlash.parse("/provider"), { type: "provider_empty", cmd: "provider" });
  assert.deepEqual(MKOSlash.parse("/model"), { type: "model_empty", cmd: "model" });
});

test("command token is case-insensitive", () => {
  assert.equal(MKOSlash.parse("/PLAN foo").type, "plan");
  assert.equal(MKOSlash.parse("/Research foo").type, "research");
  assert.equal(MKOSlash.parse("/SuMmary foo").type, "summary");
  assert.equal(MKOSlash.parse("/MODEL groq/foo").type, "model");
  assert.equal(MKOSlash.parse("/Provider ollama").type, "provider");
});

test("provider token is lowercased server-side; rest preserved verbatim", () => {
  // /model with mixed-case provider gets normalized in the parser output
  // (consumer renders as lowercase to match backend keys).
  const out = MKOSlash.parse("/model Anthropic/claude-3-5-haiku-20241022");
  assert.equal(out.provider, "anthropic");
  assert.equal(out.model, "claude-3-5-haiku-20241022");
});

test("quoted args are passed through verbatim (no quote-stripping in v1)", () => {
  assert.deepEqual(MKOSlash.parse('/plan "ship it"'), {
    type: "plan",
    cmd: "plan",
    topic: '"ship it"',
    agent: "planner",
  });
});

test("unknown command returns { type: 'unknown', cmd, rest }", () => {
  assert.deepEqual(MKOSlash.parse("/foobar something"), {
    type: "unknown",
    cmd: "foobar",
    rest: "something",
  });
  assert.deepEqual(MKOSlash.parse("/foobar"), {
    type: "unknown",
    cmd: "foobar",
    rest: "",
  });
});

test("formatConfirmation emits readable confirmation text", () => {
  assert.equal(
    MKOSlash.formatConfirmation({
      type: "model",
      provider: "groq",
      model: "llama-3.1-8b-instant",
    }),
    "✓ Switched model \u2192 groq / llama-3.1-8b-instant"
  );
  assert.equal(
    MKOSlash.formatConfirmation({ type: "model", provider: "ollama", model: null }),
    "✓ Switched provider \u2192 ollama (default model)"
  );
  assert.equal(
    MKOSlash.formatConfirmation({ type: "provider", provider: "groq" }),
    "✓ Switched provider \u2192 groq"
  );
  assert.equal(
    MKOSlash.formatConfirmation({ type: "plan", topic: "fix bug" }),
    '✓ Switched agent \u2192 Planner · topic: "fix bug"'
  );
  assert.equal(
    MKOSlash.formatConfirmation({ type: "summary", text: "hello world" }),
    '✓ Switched agent \u2192 General · summary text: "hello world"'
  );
  assert.equal(MKOSlash.formatConfirmation({ type: "unknown" }), null);
});

test("exposes KNOWN_PROVIDERS and KNOWN_AGENTS arrays", () => {
  assert.ok(Array.isArray(MKOSlash.KNOWN_PROVIDERS));
  assert.ok(MKOSlash.KNOWN_PROVIDERS.includes("ollama"));
  assert.ok(MKOSlash.KNOWN_PROVIDERS.includes("groq"));
  assert.ok(Array.isArray(MKOSlash.KNOWN_AGENTS));
  assert.ok(MKOSlash.KNOWN_AGENTS.includes("planner"));
  assert.ok(MKOSlash.KNOWN_AGENTS.includes("moe"));
});

test("/help → help type with KNOWN_COMMANDS list", () => {
  const out = MKOSlash.parse("/help");
  assert.equal(out.type, "help");
  assert.equal(out.cmd, "help");
  assert.ok(Array.isArray(out.commands));
  assert.ok(out.commands.length >= 5); // at least the original five
  const cmds = out.commands.map((c) => c.cmd);
  assert.ok(cmds.includes("/plan"));
  assert.ok(cmds.includes("/research"));
  assert.ok(cmds.includes("/summary"));
  assert.ok(cmds.includes("/model"));
  assert.ok(cmds.includes("/provider"));
  assert.ok(cmds.includes("/help"));
  assert.ok(cmds.includes("/commands"));
});

test("/commands is an alias of /help", () => {
  const a = MKOSlash.parse("/commands");
  const b = MKOSlash.parse("/help");
  assert.equal(a.type, "help");
  assert.equal(a.cmd, "commands");
  assert.equal(a.commands.length, b.commands.length);
});

test("/help is case-insensitive", () => {
  assert.equal(MKOSlash.parse("/HELP").type, "help");
  assert.equal(MKOSlash.parse("/Help").type, "help");
  assert.equal(MKOSlash.parse("/Commands").type, "help");
});

test("/help with extra args still resolves to help (rest ignored)", () => {
  // `/help topic` is the same as `/help` — we don't have per-command
  // deep help in v1.
  const a = MKOSlash.parse("/help");
  const b = MKOSlash.parse("/help topic");
  assert.equal(b.type, "help");
  assert.equal(b.commands.length, a.commands.length);
});

test("KNOWN_COMMANDS array is exposed for live help-text generation", () => {
  assert.ok(Array.isArray(MKOSlash.KNOWN_COMMANDS));
  assert.ok(MKOSlash.KNOWN_COMMANDS.length > 0);
  for (const entry of MKOSlash.KNOWN_COMMANDS) {
    assert.ok(typeof entry.cmd === "string" && entry.cmd.startsWith("/"),
      `KNOWN_COMMANDS entry has invalid cmd: ${JSON.stringify(entry)}`);
    assert.ok(typeof entry.desc === "string" && entry.desc.length > 0,
      `KNOWN_COMMANDS entry has invalid desc: ${JSON.stringify(entry)}`);
  }
});

test("formatHelp produces padded multi-line text", () => {
  const parsed = MKOSlash.parse("/help");
  const formatted = MKOSlash.formatHelp(parsed);
  assert.equal(typeof formatted, "string");
  assert.ok(formatted.includes("\n"));
  assert.ok(formatted.toLowerCase().includes("plan"));
  assert.ok(formatted.includes("/help"));
  assert.ok(formatted.includes("/commands"));
  assert.ok(formatted.includes("MKO Slash Commands"));
  // Shape-only invariants survive refactors of formatHelp:
  //   (a) header marker announces the help text,
  //   (b) output is multi-line (not a one-line dump),
  //   (c) every KNOWN_COMMANDS row appears as a substring,
  //   (d) every description appears as a substring.
  // Avoid asserting on raw line-count — that couples the test to
  // the current renderer shape and breaks on innocent refactors.
  // HELP_HEADER_CANDIDATES is an allowlist, not a tone lock: if you
  // rename the header to a new phrasing, ADD a candidate here. The
  // test exists to catch COMPLETELY missing headers — it does not
  // stop you from re-phrasing the help.
  const HELP_HEADER_CANDIDATES = [
    "MKO Slash Commands",
    "Slash Commands",
    "Available commands",
    "Commands",
  ];
  assert.ok(
    HELP_HEADER_CANDIDATES.some((m) => formatted.includes(m)),
    "formatHelp should announce itself with a header marker",
  );
  for (const entry of MKOSlash.KNOWN_COMMANDS) {
    assert.ok(
      formatted.includes(entry.cmd),
      `formatHelp should mention ${entry.cmd}`,
    );
    assert.ok(
      formatted.includes(entry.desc),
      `formatHelp should describe ${entry.cmd}`,
    );
  }
});

test("formatHelp returns null for non-help types", () => {
  assert.equal(MKOSlash.formatHelp({ type: "plan", topic: "x" }), null);
  assert.equal(MKOSlash.formatHelp({ type: "model", provider: "groq", model: null }), null);
  assert.equal(MKOSlash.formatHelp(null), null);
});


// ─── Source-of-truth meta-test ─────────────────────────────────────────────
// Adding a new slash command today requires editing three places:
//   1. KNOWN_COMMANDS row in slash-commands.js  (so /help shows it)
//   2. parse() branch in slash-commands.js       (so the grammar knows it)
//   3. case in handleSlashCommand() in app.js   (so it does something)
// This meta-test prevents forgetting #2 — a maintainer who adds a row
// to KNOWN_COMMANDS without a matching parse() branch will see this fail.
//
// Positive assertions go further: every row must parse as a command
// whose `cmd` field matches the row (so a missing branch can't be
// silently aliased to /help), and /help + /commands must hop to
// type:'help' explicitly (so a future refactor can't quietly change
// their return type without the test flagging it).
test("every KNOWN_COMMANDS row is also a parseable command (drift pin)", () => {
  // Pop-count FLOOR — silent row removal trips this. Additions grow
  // above the floor and pass without editing this assertion. Only
  // shrinking is a regression (catches "I cleaned up an unused
  // command" accidents).
  assert.ok(
    MKOSlash.KNOWN_COMMANDS.length >= 7,
    "KNOWN_COMMANDS shrank below the floor — silent row removal",
  );
  for (const entry of MKOSlash.KNOWN_COMMANDS) {
    const r = MKOSlash.parse(entry.cmd + " dummy-arg");
    assert.ok(r, `${entry.cmd} failed to parse at all`);
    assert.notEqual(
      r.type,
      "unknown",
      `${entry.cmd} returned type:'unknown' — KNOWN_COMMANDS has no matching parse() branch`,
    );
    assert.notEqual(
      r.type,
      "empty",
      `${entry.cmd} returned type:'empty' — parser needs a real branch for it`,
    );
    // Positive pin: the parsed cmd matches the row, stripped of "/".
    // Case-normalized on both sides so branded-case rows in
    // KNOWN_COMMANDS would still match (the canonical lowercase
    // invariant next to KNOWN_COMMANDS makes this defensive rather
    // than load-bearing).
    assert.equal(
      r.cmd,
      entry.cmd.slice(1).toLowerCase(),
      `${entry.cmd} parsed as cmd=${r.cmd} — aliasing is not allowed`,
    );
  }
  // /help and /commands hop to type:"help" explicitly.
  assert.equal(MKOSlash.parse("/help foo").type, "help");
  assert.equal(MKOSlash.parse("/commands foo").type, "help");
});
// ─── getSuggestions() — autocomplete dropdown filter ─────────────────────
//
// Pure function in slash-commands.js. Triggers the input dropdown pinning
// the rules in the JS file's grammar header:
//   - null  → no popup (non-slash input, or any whitespace in input)
//   - []    → hide cleanly (slash but no row matches)
//   - rows  → render those rows in KNOWN_COMMANDS display order
//
// NOTE: this filter is case-INSENSITIVE in matching but PRESERVES the
// canonical lowercase cmd string on the returned rows (the auto-accent
// copy is developer-controlled — slash-commands.js has an INVARIANT
// block next to KNOWN_COMMANDS pinning the lowercase form).

test("getSuggestions returns null when text is not a string", () => {
  assert.equal(MKOSlash.getSuggestions(null), null);
  assert.equal(MKOSlash.getSuggestions(undefined), null);
  assert.equal(MKOSlash.getSuggestions(123), null);
  assert.equal(MKOSlash.getSuggestions({}), null);
  assert.equal(MKOSlash.getSuggestions([]), null);
});

test("getSuggestions returns null when text does not start with /", () => {
  assert.equal(MKOSlash.getSuggestions(""), null);
  assert.equal(MKOSlash.getSuggestions("hello"), null);
  assert.equal(MKOSlash.getSuggestions("plan foo"), null);
  // Leading space then slash: NOT a slash command — null.
  assert.equal(MKOSlash.getSuggestions(" /plan"), null);
});

test("getSuggestions returns null when input contains any whitespace", () => {
  // The user has moved past the command-token stage; hide the popup.
  assert.equal(MKOSlash.getSuggestions("/plan foo"), null);
  assert.equal(MKOSlash.getSuggestions("/help "), null);     // trailing auto-space
  assert.equal(MKOSlash.getSuggestions("/\t"), null);
  assert.equal(MKOSlash.getSuggestions("/\n"), null);
});

test("getSuggestions('/') returns every row in display order", () => {
  const rows = MKOSlash.getSuggestions("/");
  assert.ok(Array.isArray(rows), "expected array");
  assert.equal(rows.length, MKOSlash.KNOWN_COMMANDS.length);
  rows.forEach((row, i) => {
    assert.equal(row.cmd, MKOSlash.KNOWN_COMMANDS[i].cmd,
      `row ${i} should match KNOWN_COMMANDS[${i}]`);
  });
});

test("getSuggestions case-insensitive prefix match", () => {
  const low  = MKOSlash.getSuggestions("/pl");
  const up   = MKOSlash.getSuggestions("/PL");
  const mixed = MKOSlash.getSuggestions("/Plan");
  assert.equal(low.length, 1);
  assert.equal(up.length, 1);
  assert.equal(mixed.length, 1);
  // Returned row's cmd is the canonical lowercase form.
  assert.equal(low[0].cmd, "/plan");
  assert.equal(up[0].cmd, "/plan");
  assert.equal(mixed[0].cmd, "/plan");
});

test("getSuggestions distinguishes /help vs /commands under prefix", () => {
  // /h matches ONLY /help, NOT /commands (which starts with /c).
  const h = MKOSlash.getSuggestions("/h");
  assert.equal(h.length, 1);
  assert.equal(h[0].cmd, "/help");
  // /c matches ONLY /commands.
  const c = MKOSlash.getSuggestions("/c");
  assert.equal(c.length, 1);
  assert.equal(c[0].cmd, "/commands");
});

test("getSuggestions returns [] when no row matches the prefix", () => {
  // /foobar starts with `/` but no row's cmd starts with "foobar".
  const matches = MKOSlash.getSuggestions("/foobar");
  assert.ok(Array.isArray(matches));
  assert.equal(matches.length, 0);
  // Same for a longer-but-unrelated prefix.
  assert.equal(MKOSlash.getSuggestions("/nope").length, 0);
});

test("getSuggestions returns all rows when prefix is exactly /", () => {
  // The /  test above already covers this; this one asserts ordering.
  const rows = MKOSlash.getSuggestions("/");
  const cmds = rows.map((r) => r.cmd);
  assert.deepEqual(cmds, [
    "/plan", "/research", "/summary",
    "/model", "/provider", "/help", "/commands",
  ]);
});

test("getSuggestions does not return unknown slash commands", () => {
  // /foobar should yield ZERO rows — there must be no slip-up like
  // returning a synthetic row that would let the UI show a fake match.
  assert.equal(MKOSlash.getSuggestions("/foobar").length, 0);
  assert.equal(MKOSlash.getSuggestions("/zz").length, 0);
});

test("getSuggestions drift pin: every matched row comes from KNOWN_COMMANDS", () => {
  // For each row that getSuggestions("/") returns, the same row exists
  // verbatim in MKOSlash.KNOWN_COMMANDS. Guards against a future
  // accidental source of truth split.
  const rows = MKOSlash.getSuggestions("/");
  assert.equal(rows.length, MKOSlash.KNOWN_COMMANDS.length);
  rows.forEach((row) => {
    const same = MKOSlash.KNOWN_COMMANDS.find((k) => k.cmd === row.cmd);
    assert.ok(same, `${row.cmd} not found in KNOWN_COMMANDS`);
    assert.equal(same.desc, row.desc);
  });
});

test("MKOSlash exports getSuggestions on its public surface", () => {
  assert.equal(typeof MKOSlash.getSuggestions, "function");
});

// -- Trailing-space autocomplete completion -------------------------
// /-help /-commands take no args but the autocompleter writes
// /-cmd + a trailing space. Pin that parse() still resolves to the
// help type (rest is intentionally ignored).

test("/help with single trailing space still resolves to help type", () => {
  const r = MKOSlash.parse("/help ");
  assert.equal(r.type, "help");
  assert.equal(r.cmd, "help");
});

test("/commands with single trailing space still resolves to help type", () => {
  const r = MKOSlash.parse("/commands ");
  assert.equal(r.type, "help");
  assert.equal(r.cmd, "commands");
});
