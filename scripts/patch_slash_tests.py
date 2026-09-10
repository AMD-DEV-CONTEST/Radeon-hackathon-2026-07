"""One-off patcher for tests/test_slash_commands.mjs.

Why a script: the heredoc through bash escapes \\n in conflicting ways.
A real .py file on disk handles the newlines cleanly.
"""
import pathlib

p = pathlib.Path("tests/test_slash_commands.mjs")
t = p.read_text(encoding="utf-8")

# Tighten the existing formatHelp test: add line-count + every-row assertion.
anchor = (
    'test("formatHelp produces padded multi-line text", () => {\n'
    '  const parsed = MKOSlash.parse("/help");\n'
    '  const formatted = MKOSlash.formatHelp(parsed);\n'
    '  assert.equal(typeof formatted, "string");\n'
    '  assert.ok(formatted.includes("\\n"));\n'
    '  assert.ok(formatted.toLowerCase().includes("plan"));\n'
    '  assert.ok(formatted.includes("/help"));\n'
    '  assert.ok(formatted.includes("/commands"));\n'
    '  assert.ok(formatted.includes("MKO Slash Commands"));\n'
    '});'
)
assert anchor in t, "formatHelp anchor not found verbatim"

replacement = (
    'test("formatHelp produces padded multi-line text", () => {\n'
    '  const parsed = MKOSlash.parse("/help");\n'
    '  const formatted = MKOSlash.formatHelp(parsed);\n'
    '  assert.equal(typeof formatted, "string");\n'
    '  assert.ok(formatted.includes("\\n"));\n'
    '  assert.ok(formatted.toLowerCase().includes("plan"));\n'
    '  assert.ok(formatted.includes("/help"));\n'
    '  assert.ok(formatted.includes("/commands"));\n'
    '  assert.ok(formatted.includes("MKO Slash Commands"));\n'
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
t = t.replace(anchor, replacement, 1)

# Append a meta-test that KNOWN_COMMANDS entries are all parseable.
append = '''

// ─── Source-of-truth meta-test ─────────────────────────────────────────────
// Adding a new slash command today requires editing three places:
//   1. KNOWN_COMMANDS row in slash-commands.js  (so /help shows it)
//   2. parse() branch in slash-commands.js       (so the grammar knows it)
//   3. case in handleSlashCommand() in app.js   (so it does something)
// This meta-test prevents forgetting #2 — a maintainer who adds a row
// to KNOWN_COMMANDS without a matching parse() branch will see this fail.
test("every KNOWN_COMMANDS row is also a parseable command (drift pin)", () => {
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
  }
});
'''
t += append

p.write_text(t, encoding="utf-8")
print("test_slash_commands.mjs patched")
print("  total lines now:", len(t.splitlines()))
