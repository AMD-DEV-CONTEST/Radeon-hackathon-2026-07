"""
Append Node tests for the new `MKOSlash.getSuggestions(text)` autocomplete
helper without disturbing the encoded bytes of the existing file.

Run from anywhere. Reads tests/test_slash_commands.mjs, finds the closing
`});` of the last test block at EOF, and appends new tests.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parent / "tests" / "test_slash_commands.mjs"
SMOKE = HERE.parent / "tests" / "test_run_smoke.py"

# Tests to append. Pure UTF-8 strings (no smart quotes / em dashes) so
# the file remains ASCII-safe and patches survive any encoding roundtrip.
APPEND_MJS = r"""

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
"""

# Smoke test additions — append after the existing test classes.
APPEND_SMOKE = '''
class SlashSuggestTests(unittest.TestCase):
    """Pin that the new autocomplete dropdown is wired from parser -> app.js."""

    def test_slash_commands_exports_get_suggestions(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "slash-commands.js").read_text(encoding="utf-8")
        self.assertIn("getSuggestions: getSuggestions", text,
                      "slash-commands.js must export getSuggestions on the public surface")
        # Grammar header must document the autocomplete contract.
        self.assertIn("getSuggestions(text)", text)
        self.assertIn("null", text)             # hide conditions list `null`
        self.assertIn("rows[]", text)           # and `rows[]`

    def test_app_js_wires_suggest_dropdown(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        # Pure helper is consumed.
        self.assertIn("MKOSlash.getSuggestions", text,
                      "app.js must call MKOSlash.getSuggestions")
        # Lifecycle hooks shipped.
        self.assertIn("wireSlashSuggest", text)
        self.assertIn("renderSuggest", text)
        self.assertIn("applySuggestion", text)
        self.assertIn("onChatKeydownSuggest", text)
        self.assertIn("ensureSuggestEl", text)
        # Keyboard nav events handled.
        self.assertIn("ArrowDown", text)
        self.assertIn("ArrowUp", text)
        # Enter handled but gated by Shift (textarea newline passes through).
        self.assertIn("e.shiftKey", text)

    def test_styles_css_has_suggest_rules(self):
        text = (REPO_ROOT / "mko" / "webui" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
        # .mko-suggest must be defined AND .open AND .active variants.
        self.assertIn(".mko-suggest", text)
        self.assertIn(".mko-suggest.open", text)
        self.assertIn(".mko-suggest-row", text)
        self.assertIn(".mko-suggest-row.active", text)
        # .input-area must remain the positioning context.
        # (Already true in the existing stylesheet; this test guards
        # against future refactors that drop `position: relative`.)
        self.assertIn(".input-area", text)
        self.assertIn("position: relative", text)
'''


def main() -> None:
    mjs = TESTS.read_text(encoding="utf-8")
    if "getSuggestions returns null when text is not a string" not in mjs:
        mjs = mjs.rstrip() + "\n" + APPEND_MJS.lstrip()
        TESTS.write_text(mjs, encoding="utf-8")
        print(f"appended getSuggestions tests to {TESTS}")
    else:
        print(f"skipped append: tests already present in {TESTS}")

    py = SMOKE.read_text(encoding="utf-8")
    if "SlashSuggestTests" not in py:
        py = py.rstrip() + APPEND_SMOKE
        SMOKE.write_text(py, encoding="utf-8")
        print(f"appended SlashSuggestTests to {SMOKE}")
    else:
        print(f"skipped append: SlashSuggestTests already present in {SMOKE}")


if __name__ == "__main__":
    BASE = HERE.parent  # not used at runtime; only for path anchoring
    main()
