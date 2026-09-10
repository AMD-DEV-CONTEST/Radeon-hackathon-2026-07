"""Round-4 patcher — final wording cleanup from the round-3 code-review:

  1. The INVARIANT comment in slash-commands.js is wrong: parse() does NOT
     lowercase the cmd token. Dispatch is case-insensitive (via the
     dispatch table / lookup) but `cmd: cmdRaw` returns the raw text.
     Correct the comment so a future maintainer doesn't "fix" parse()
     and accidentally break case-preserving consumers.

  2. The pop-count comment in tests/test_slash_commands.mjs oversells
     the assertion — it's a *floor*, not a strict count. Reword.
"""
import pathlib

# ── 1) slash-commands.js ─ INVARIANT comment correction ──────────────
p1 = pathlib.Path("mko/webui/static/js/slash-commands.js")
js = p1.read_text(encoding="utf-8")
old = (
    '  // INVARIANT: every row uses the canonical lowercase form (e.g. "/plan").\n'
    '  // `parse()` lowercases the cmd token, and tests slot both sides to\n'
    '  // lowercase before comparing so branded-case rows would trip the\n'
    '  // drift pin. If you want a different display casing for the help\n'
    '  // text, change `desc` — never change `cmd`.\n'
)
assert old in js, "INVARIANT anchor not found"
new = (
    '  // INVARIANT: every row uses the canonical lowercase form (e.g. "/plan").\n'
    '  // `parse()` is case-INSENSITIVE in its dispatch (so `/PLAN foo`\n'
    '  // resolves to type:"plan") but PRESERVES the original case of\n'
    '  // the command token in the `cmd` field — `/HELP` returns cmd:"HELP".\n'
    '  // Tests slot both sides to lowercase before comparing so branded-\n'
    '  // case rows in KNOWN_COMMANDS would still match. If you want\n'
    '  // different display casing in the help text, change `desc` —\n'
    '  // never change `cmd` (breakage mode: tests that rely on case-\n'
    '  // preserved cmd would silently break).\n'
)
js = js.replace(old, new, 1)
p1.write_text(js, encoding="utf-8")
print("slash-commands.js: INVARIANT comment corrected (parse preserves case, dispatch is case-insensitive)")

# ── 2) tests/test_slash_commands.mjs ─ pop-count comment reword ───────
p2 = pathlib.Path("tests/test_slash_commands.mjs")
t = p2.read_text(encoding="utf-8")
old = (
    '  // Pop-count pin: silent row removal would otherwise pass via a\n'
    '  // shorter loop. Bump the count when adding a new command.\n'
    '  assert.ok(\n'
    '    MKOSlash.KNOWN_COMMANDS.length >= 7,\n'
    '    "KNOWN_COMMANDS shrank below the floor — bump me when adding a command",\n'
    '  );\n'
)
assert old in t, "pop-count anchor not found"
new = (
    '  // Pop-count FLOOR — silent row removal trips this. Additions grow\n'
    '  // above the floor and pass without editing this assertion. Only\n'
    '  // shrinking is a regression (catches "I cleaned up an unused\n'
    '  // command" accidents).\n'
    '  assert.ok(\n'
    '    MKOSlash.KNOWN_COMMANDS.length >= 7,\n'
    '    "KNOWN_COMMANDS shrank below the floor — silent row removal",\n'
    '  );\n'
)
t = t.replace(old, new, 1)
p2.write_text(t, encoding="utf-8")
print("tests/test_slash_commands.mjs: pop-count comment reworded (floor not strict count)")
print("  total lines now:", len(t.splitlines()))
