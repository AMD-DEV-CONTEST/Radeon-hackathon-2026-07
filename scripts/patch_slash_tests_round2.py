"""Patch tests/test_slash_commands.mjs per code-review round-2 feedback.

Two surgical edits:
  1. Replace brittle line-count assertion with shape-only invariants.
  2. Tighten the drift-pin meta-test with positive cmd assertions and
     explicit type:'help' expectations for /help and /commands.
"""
import pathlib

p = pathlib.Path("tests/test_slash_commands.mjs")
t = p.read_text(encoding="utf-8")

# ── Edit 1: brittle → shape-only invariants ────────────────────────────
old = (
    '  // Stronger: every KNOWN_COMMANDS row is rendered, and line-count is\n'
    '  // at least N+1 (N rows + header + footer). If a maintainer drops a\n'
    '  // row or breaks padding, this trips.\n'
    '  for (const entry of MKOSlash.KNOWN_COMMANDS) {\n'
    '    assert.ok(\n'
    '      formatted.includes(entry.cmd),\n'
    '      `formatHelp should mention ${entry.cmd}`,\n'
    '    );\n'
    '  }\n'
    '  const lines = formatted.split("\\n").length;\n'
    '  assert.ok(\n'
    '    lines >= MKOSlash.KNOWN_COMMANDS.length + 1,\n'
    '    `formatHelp should have >= ${MKOSlash.KNOWN_COMMANDS.length + 1}` +\n'
    '      ` lines, got ${lines}`,\n'
    '  );\n'
    '});'
)
assert old in t, "brittle assertion block not found"
new = (
    '  // Shape-only invariants survive refactors of formatHelp:\n'
    '  //   (a) header marker announces the help text,\n'
    '  //   (b) output is multi-line (not a one-line dump),\n'
    '  //   (c) every KNOWN_COMMANDS row appears as a substring,\n'
    '  //   (d) every description appears as a substring.\n'
    '  // Avoid asserting on raw line-count — that couples the test to\n'
    '  // the current renderer shape and breaks on innocent refactors.\n'
    '  const headerMarkers = [\n'
    '    "MKO Slash Commands",\n'
    '    "Slash Commands",\n'
    '    "Available commands",\n'
    '    "Commands",\n'
    '  ];\n'
    '  assert.ok(\n'
    '    headerMarkers.some((m) => formatted.includes(m)),\n'
    '    "formatHelp should announce itself with a header marker",\n'
    '  );\n'
    '  for (const entry of MKOSlash.KNOWN_COMMANDS) {\n'
    '    assert.ok(\n'
    '      formatted.includes(entry.cmd),\n'
    '      `formatHelp should mention ${entry.cmd}`,\n'
    '    );\n'
    '    assert.ok(\n'
    '      formatted.includes(entry.desc),\n'
    '      `formatHelp should describe ${entry.cmd}`,\n'
    '    );\n'
    '  }\n'
    '});'
)
t = t.replace(old, new, 1)

# ── Edit 2: tighten drift pin with positive assertions ──────────────────
old_meta = (
    '// ─── Source-of-truth meta-test ─────────────────────────────────────────────\n'
    '// Adding a new slash command today requires editing three places:\n'
    '//   1. KNOWN_COMMANDS row in slash-commands.js  (so /help shows it)\n'
    '//   2. parse() branch in slash-commands.js       (so the grammar knows it)\n'
    '//   3. case in handleSlashCommand() in app.js   (so it does something)\n'
    '// This meta-test prevents forgetting #2 — a maintainer who adds a row\n'
    '// to KNOWN_COMMANDS without a matching parse() branch will see this fail.\n'
    'test("every KNOWN_COMMANDS row is also a parseable command (drift pin)", () => {\n'
    '  for (const entry of MKOSlash.KNOWN_COMMANDS) {\n'
    '    const r = MKOSlash.parse(entry.cmd + " dummy-arg");\n'
    '    assert.ok(r, `${entry.cmd} failed to parse at all`);\n'
    '    assert.notEqual(\n'
    '      r.type,\n'
    '      "unknown",\n'
    '      `${entry.cmd} returned type:\'unknown\' — KNOWN_COMMANDS has no matching parse() branch`,\n'
    '    );\n'
    '    assert.notEqual(\n'
    '      r.type,\n'
    '      "empty",\n'
    '      `${entry.cmd} returned type:\'empty\' — parser needs a real branch for it`,\n'
    '    );\n'
    '  }\n'
    '});'
)
assert old_meta in t, "drift-pin block not found"
new_meta = (
    '// ─── Source-of-truth meta-test ─────────────────────────────────────────────\n'
    '// Adding a new slash command today requires editing three places:\n'
    '//   1. KNOWN_COMMANDS row in slash-commands.js  (so /help shows it)\n'
    '//   2. parse() branch in slash-commands.js       (so the grammar knows it)\n'
    '//   3. case in handleSlashCommand() in app.js   (so it does something)\n'
    '// This meta-test prevents forgetting #2 — a maintainer who adds a row\n'
    '// to KNOWN_COMMANDS without a matching parse() branch will see this fail.\n'
    '//\n'
    '// Positive assertions go further: every row must parse as a command\n'
    '// whose `cmd` field matches the row (so a missing branch can\'t be\n'
    '// silently aliased to /help), and /help + /commands must hop to\n'
    '// type:\'help\' explicitly (so a future refactor can\'t quietly change\n'
    '// their return type without the test flagging it).\n'
    'test("every KNOWN_COMMANDS row is also a parseable command (drift pin)", () => {\n'
    '  for (const entry of MKOSlash.KNOWN_COMMANDS) {\n'
    '    const r = MKOSlash.parse(entry.cmd + " dummy-arg");\n'
    '    assert.ok(r, `${entry.cmd} failed to parse at all`);\n'
    '    assert.notEqual(\n'
    '      r.type,\n'
    '      "unknown",\n'
    '      `${entry.cmd} returned type:\'unknown\' — KNOWN_COMMANDS has no matching parse() branch`,\n'
    '    );\n'
    '    assert.notEqual(\n'
    '      r.type,\n'
    '      "empty",\n'
    '      `${entry.cmd} returned type:\'empty\' — parser needs a real branch for it`,\n'
    '    );\n'
    '    // Positive pin: the parsed cmd matches the row, stripped of "/".\n'
    '    assert.equal(\n'
    '      r.cmd,\n'
    '      entry.cmd.slice(1),\n'
    '      `${entry.cmd} parsed as cmd=${r.cmd} — aliasing is not allowed`,\n'
    '    );\n'
    '  }\n'
    '  // /help and /commands hop to type:"help" explicitly.\n'
    '  assert.equal(MKOSlash.parse("/help foo").type, "help");\n'
    '  assert.equal(MKOSlash.parse("/commands foo").type, "help");\n'
    '});'
)
t = t.replace(old_meta, new_meta, 1)

p.write_text(t, encoding="utf-8")
print("tests/test_slash_commands.mjs patched (round 2)")
print("  total lines now:", len(t.splitlines()))
