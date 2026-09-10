/* ──────────────────────────────────────────────────────────────────────────
 * MKO Slash Commands — pure parser.
 * UMD-style: `window.MKOSlash` in browsers, `module.exports` in Node.
 *
 * Grammar (pin this — tests in tests/test_slash_commands.mjs mirror it):
 *   /                          → { type: 'empty' }
 *   /plan <topic>              → { type: 'plan',      cmd, topic,  agent: 'planner'  }
 *   /plan                      → { type: 'plan_empty', cmd }
 *   /research <query>          → { type: 'research',  cmd, query,  agent: 'research' }
 *   /research                  → { type: 'research_empty', cmd }
 *   /summary <text>            → { type: 'summary',   cmd, text,   agent: 'general'  }
 *   /summary                   → { type: 'summary_empty', cmd }
 *   /help                      → { type: 'help', cmds: KNOWN_COMMANDS }
 *   /help <anything>           → { type: 'help', cmds: KNOWN_COMMANDS }   (rest ignored)
 *   /commands                  → alias of /help
 *   /model <provider>[/<model>]→ { type: 'model', cmd, provider, model }
 *                                (model: null when only provider is given;
 *                                 trailing `/` is stripped; multiple `/`
 *                                 keep everything-after-the-first as model)
 *   /model <unknown>[/<model>] → { type: 'model_unknown_provider', cmd, provider, model }
 *   /model                     → { type: 'model_empty', cmd }
 *   /provider <provider>       → { type: 'provider', cmd, provider }
 *   /provider <unknown>        → { type: 'provider_unknown', cmd, provider }
 *   /provider                  → { type: 'provider_empty', cmd }
 *   /foobar <anything>         → { type: 'unknown', cmd, rest }    (sent as plain chat)
 *   Hello /plan foo            → null                              (slash not at start)
 *
 * The command token (`plan`, `PLAN`, `Plan`, ...) is matched
 * case-insensitively; provider, model, and seeded text are PRESERVED
 * in the original case the user typed.
 *
 * Adding a command: append to KNOWN_COMMANDS, update the dispatch in
 * parse(), update handleSlashCommand() in app.js. /help auto-includes
 * the new command because it reads KNOWN_COMMANDS directly.
 *
 * Autocomplete (used by the chat input dropdown):
 *   getSuggestions(text)
 *     → null   text doesn't start with `/`, or contains any whitespace
 *              (user has moved past the command-token stage)
 *              -- note: app.js's applySuggestion writes "/cmd" + a trailing space, so a trailing-space newline also
 *              immediately closes the popup. This rule is load-bearing.
 *     → []     starts with `/` but no command matches (caller hides UI)
 *     → rows[] one or more KNOWN_COMMANDS rows whose `cmd` (sans the
 *              leading `/`) starts with the typed prefix, case-insensitive,
 *              in KNOWN_COMMANDS display order.
 *   The leading `/` is mandatory — leading whitespace (` /plan`) is
 *   treated as plain chat, no popup.
 * ────────────────────────────────────────────────────────────────────────── */

(function (factory) {
  "use strict";
  const exported = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = exported;
  }
  if (typeof window !== "undefined") {
    window.MKOSlash = exported;
  }
})(function () {
  "use strict";

  const KNOWN_AGENTS = ["general", "planner", "research", "reasoner",
                        "actor", "memory", "rag", "moe"];

  // Single source of truth: every command the parser knows about, with
  // a one-line description that `/help` renders. Order = display order.
  // Adding a new slash command? Append here, add the parse() branch,
  // and add the case in handleSlashCommand() in app.js. /help picks
  // this up automatically.
  // INVARIANT: every row uses the canonical lowercase form (e.g. "/plan").
  // `parse()` is case-INSENSITIVE in its dispatch (so `/PLAN foo`
  // resolves to type:"plan") but PRESERVES the original case of
  // the command token in the `cmd` field — `/HELP` returns cmd:"HELP".
  // Tests slot both sides to lowercase before comparing so branded-
  // case rows in KNOWN_COMMANDS would still match. If you want
  // different display casing in the help text, change `desc` —
  // never change `cmd` (breakage mode: tests that rely on case-
  // preserved cmd would silently break).
  const KNOWN_COMMANDS = [
    { cmd: "/plan",      desc: "Switch agent → Planner; seed input with <topic>." },
    { cmd: "/research",  desc: "Switch agent → Researcher; seed input with <query>." },
    { cmd: "/summary",   desc: "Switch agent → General; seed input with text to summarize." },
    { cmd: "/model",     desc: "Swap provider/model · /model <provider>[/<model>]" },
    { cmd: "/provider",  desc: "Swap provider · /provider <name>" },
    { cmd: "/help",      desc: "Show this help · /commands is terse alias." },
    { cmd: "/commands",  desc: "Terse alias of /help." },
  ];

  const KNOWN_PROVIDERS = ["ollama", "groq", "huggingface", "openai", "anthropic"];

  function parse(text) {
    if (typeof text !== "string") return null;
    const trimmed = text.trim();
    if (!trimmed.startsWith("/")) return null;
    if (trimmed === "" || trimmed === "/") return { type: "empty" };

    // Strip leading slash, split into (command, rest) on first whitespace.
    const body = trimmed.slice(1);
    const wsIdx = body.search(/\s/);
    const cmdRaw = wsIdx === -1 ? body : body.slice(0, wsIdx);
    const rest = wsIdx === -1 ? "" : body.slice(wsIdx + 1).trim();

    // The COMMAND token is matched case-insensitively; everything else
    // (provider, model, seeded text) is preserved verbatim.
    const cmd = cmdRaw.toLowerCase();

    if (cmd === "plan") {
      if (!rest) return { type: "plan_empty", cmd: cmdRaw };
      return { type: "plan", cmd: cmdRaw, topic: rest, agent: "planner" };
    }
    if (cmd === "research") {
      if (!rest) return { type: "research_empty", cmd: cmdRaw };
      return { type: "research", cmd: cmdRaw, query: rest, agent: "research" };
    }
    if (cmd === "summary") {
      if (!rest) return { type: "summary_empty", cmd: cmdRaw };
      return { type: "summary", cmd: cmdRaw, text: rest, agent: "general" };
    }
    if (cmd === "help" || cmd === "commands") {
      // Rest is intentionally ignored — users can write `/help topic`
      // for free and we still show the same canonical list.
      return { type: "help", cmd: cmdRaw, commands: KNOWN_COMMANDS };
    }
    if (cmd === "model") {
      if (!rest) return { type: "model_empty", cmd: cmdRaw };
      // Split provider/model on FIRST slash. Strip trailing slash on the
      // rest; everything-after-the-first-slash is the model name verbatim
      // (model names never contain slashes in practice).
      const slashIdx = rest.indexOf("/");
      let provider, model;
      if (slashIdx === -1) {
        provider = rest;
        model = null;
      } else {
        provider = rest.slice(0, slashIdx);
        const after = rest.slice(slashIdx + 1).replace(/\/+$/, "");
        model = after === "" ? null : after;
      }
      const providerLc = provider.toLowerCase().trim();
      if (!KNOWN_PROVIDERS.includes(providerLc)) {
        return { type: "model_unknown_provider", cmd: cmdRaw, provider: providerLc, model: model };
      }
      return { type: "model", cmd: cmdRaw, provider: providerLc, model: model };
    }
    if (cmd === "provider") {
      if (!rest) return { type: "provider_empty", cmd: cmdRaw };
      const providerLc = rest.toLowerCase().trim();
      if (!KNOWN_PROVIDERS.includes(providerLc)) {
        return { type: "provider_unknown", cmd: cmdRaw, provider: providerLc };
      }
      return { type: "provider", cmd: cmdRaw, provider: providerLc };
    }

    // Unknown slash command — pass through as plain chat with a warning.
    return { type: "unknown", cmd: cmdRaw, rest: rest };
  }

  function formatConfirmation(parsed) {
    switch (parsed.type) {
      case "model":
        return parsed.model
          ? `✓ Switched model → ${parsed.provider} / ${parsed.model}`
          : `✓ Switched provider → ${parsed.provider} (default model)`;
      case "provider":
        return `✓ Switched provider → ${parsed.provider}`;
      case "plan":
        return `✓ Switched agent → Planner · topic: "${parsed.topic}"`;
      case "research":
        return `✓ Switched agent → Researcher · query: "${parsed.query}"`;
      case "summary":
        return `✓ Switched agent → General · summary text: "${truncate(parsed.text, 60)}"`;
      case "help":
        return parsed.commands.length + " commands available. /commands for the same list.";
      default:
        return null;
    }
  }

  // Render the help body as a fixed-width-ish list. Two columns,
  // left = command (padded), right = description.
  function formatHelp(parsed) {
    if (!parsed || parsed.type !== "help") return null;
    // Find the widest command so columns line up nicely.
    var w = 0;
    for (var i = 0; i < parsed.commands.length; i++) {
      if (parsed.commands[i].cmd.length > w) w = parsed.commands[i].cmd.length;
    }
    var lines = ["MKO Slash Commands", "─".repeat(w + 2)];
    for (var j = 0; j < parsed.commands.length; j++) {
      var c = parsed.commands[j];
      lines.push(c.cmd + " ".repeat(Math.max(1, w + 2 - c.cmd.length)) + c.desc);
    }
    return lines.join("\n");
  }

  function truncate(s, n) {
    if (!s) return "";
    return s.length > n ? s.slice(0, n - 1) + "\u2026" : s;
  }

  // Suggest matching KNOWN_COMMANDS rows for the slash-command
  // autocomplete dropdown. Pure: no DOM, no state. Pin the exact rules
  // in tests/test_slash_commands.mjs (search for "getSuggestions").
  function getSuggestions(text) {
    if (typeof text !== "string") return null;
    if (!text.startsWith("/")) return null;
    // Once the user types any whitespace (including the trailing space
    // we ourselves insert on autocomplete), they have moved past the
    // command-token stage — hide the popup.
    if (/\s/.test(text)) return null;
    // Empty prefix ("/") matches everything; non-empty prefix filters
    // case-insensitively against the cmd token with its leading `/`
    // stripped for comparison. Preserves KNOWN_COMMANDS display order.
    const prefix = text.slice(1).toLowerCase();
    const matches = KNOWN_COMMANDS.filter(function (c) {
      return c.cmd.slice(1).toLowerCase().startsWith(prefix);
    });
    return matches;  // [] when nothing matches; caller hides UI.
  }

  return {
    parse: parse,
    formatConfirmation: formatConfirmation,
    formatHelp: formatHelp,
    getSuggestions: getSuggestions,
    KNOWN_PROVIDERS: KNOWN_PROVIDERS,
    KNOWN_AGENTS: KNOWN_AGENTS,
    KNOWN_COMMANDS: KNOWN_COMMANDS,
  };
});
