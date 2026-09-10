"""Round-3 patcher — applies the three final code-review fixes:

  1. Pop-count pin in the drift meta-test:
       assert.equal(MKOSlash.KNOWN_COMMANDS.length, 7)
     (so silent row removal trips the test)

  2. Case-normalize the positive-cmd assertion in the drift pin:
       r.cmd === entry.cmd.slice(1).toLowerCase()
     and document the canonical-lowercase invariant on KNOWN_COMMANDS.

  3. Rename headerMarkers → HELP_HEADER_CANDIDATES and add a one-line
     comment that explains tone-vs-correctness.
"""
import pathlib

# ── 1) Patch slash-commands.js: canonical-lowercase invariant ──────────
p1 = pathlib.Path("mko/webui/static/js/slash-commands.js")
js = p1.read_text(encoding="utf-8")

old_kc_anchor = (
    '  // Single source of truth: every command the parser knows about, with\n'
    '  // a one-line description that `/help` renders. Order = display order.\n'
    '  // Adding a new slash command? Append here, add the parse() branch,\n'
    '  // and add the case in handleSlashCommand() in app.js. /help picks\n'
    '  // this up automatically.\n'
    '  const KNOWN_COMMANDS = ['
)
assert old_kc_anchor in js, "KNOWN_COMMANDS block not found"
new_kc_anchor = (
    '  // Single source of truth: every command the parser knows about, with\n'
    '  // a one-line description that `/help` renders. Order = display order.\n'
    '  // Adding a new slash command? Append here, add the parse() branch,\n'
    '  // and add the case in handleSlashCommand() in app.js. /help picks\n'
    '  // this up automatically.\n'
    '  // INVARIANT: every row uses the canonical lowercase form (e.g. "/plan").\n'
    '  // `parse()` lowercases the cmd token, and tests slot both sides to\n'
    '  // lowercase before comparing so branded-case rows would trip the\n'
    '  // drift pin. If you want a different display casing for the help\n'
    '  // text, change `desc` — never change `cmd`.\n'
    '  const KNOWN_COMMANDS = ['
)
js = js.replace(old_kc_anchor, new_kc_anchor, 1)
p1.write_text(js, encoding="utf-8")
print("slash-commands.js: canonical-lowercase invariant comment added next to KNOWN_COMMANDS")

# ── 2) Patch tests/test_slash_commands.mjs: three changes ──────────────
p2 = pathlib.Path("tests/test_slash_commands.mjs")
t = p2.read_text(encoding="utf-8")

# 2a) rename headerMarkers → HELP_HEADER_CANDIDATES + comment
old_hm = (
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
)
assert old_hm in t, "headerMarkers block not found"
new_hm = (
    '  // Shape-only invariants survive refactors of formatHelp:\n'
    '  //   (a) header marker announces the help text,\n'
    '  //   (b) output is multi-line (not a one-line dump),\n'
    '  //   (c) every KNOWN_COMMANDS row appears as a substring,\n'
    '  //   (d) every description appears as a substring.\n'
    '  // Avoid asserting on raw line-count — that couples the test to\n'
    '  // the current renderer shape and breaks on innocent refactors.\n'
    '  // HELP_HEADER_CANDIDATES is an allowlist, not a tone lock: if you\n'
    '  // rename the header to a new phrasing, ADD a candidate here. The\n'
    '  // test exists to catch COMPLETELY missing headers — it does not\n'
    '  // stop you from re-phrasing the help.\n'
    '  const HELP_HEADER_CANDIDATES = [\n'
    '    "MKO Slash Commands",\n'
    '    "Slash Commands",\n'
    '    "Available commands",\n'
    '    "Commands",\n'
    '  ];\n'
    '  assert.ok(\n'
    '    HELP_HEADER_CANDIDATES.some((m) => formatted.includes(m)),\n'
    '    "formatHelp should announce itself with a header marker",\n'
    '  );\n'
)
t = t.replace(old_hm, new_hm, 1)

# 2b) pop-count pin + case-normalize the positive-cmd assertion
old_meta_header = (
    'test("every KNOWN_COMMANDS row is also a parseable command (drift pin)", () => {\n'
    '  for (const entry of MKOSlash.KNOWN_COMMANDS) {'
)
new_meta_header = (
    'test("every KNOWN_COMMANDS row is also a parseable command (drift pin)", () => {\n'
    '  // Pop-count pin: silent row removal would otherwise pass via a\n'
    '  // shorter loop. Bump the count when adding a new command.\n'
    '  assert.ok(\n'
    '    MKOSlash.KNOWN_COMMANDS.length >= 7,\n'
    '    "KNOWN_COMMANDS shrank below the floor — bump me when adding a command",\n'
    '  );\n'
    '  for (const entry of MKOSlash.KNOWN_COMMANDS) {'
)
assert old_meta_header in t, "drift-pin header not found"
t = t.replace(old_meta_header, new_meta_header, 1)

# 2c) update the positive-cmd assertion: case-normalize both sides
old_pos = (
    '    // Positive pin: the parsed cmd matches the row, stripped of "/".\n'
    '    assert.equal(\n'
    '      r.cmd,\n'
    '      entry.cmd.slice(1),\n'
    '      `${entry.cmd} parsed as cmd=${r.cmd} — aliasing is not allowed`,\n'
    '    );\n'
)
assert old_pos in t, "positive-cmd assertion not found"
new_pos = (
    '    // Positive pin: the parsed cmd matches the row, stripped of "/".\n'
    '    // Case-normalized on both sides so branded-case rows in\n'
    '    // KNOWN_COMMANDS would still match (the canonical lowercase\n'
    '    // invariant next to KNOWN_COMMANDS makes this defensive rather\n'
    '    // than load-bearing).\n'
    '    assert.equal(\n'
    '      r.cmd,\n'
    '      entry.cmd.slice(1).toLowerCase(),\n'
    '      `${entry.cmd} parsed as cmd=${r.cmd} — aliasing is not allowed`,\n'
    '    );\n'
)
t = t.replace(old_pos, new_pos, 1)

p2.write_text(t, encoding="utf-8")
print("tests/test_slash_commands.mjs: HELP_HEADER_CANDIDATES renamed + pop-count pin + case-normalize positive assertion")
print("  total lines now:", len(t.splitlines()))
