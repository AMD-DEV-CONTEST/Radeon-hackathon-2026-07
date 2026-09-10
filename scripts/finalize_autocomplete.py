"""Finalize the slash-command autocomplete feature: grammar header
cross-reference, trailing-space parse tests, and doc updates.

Reads/updates files in UTF-8 explicitly so box-drawing / em-dash chars in
the existing slash-commands.js grammar header do not get re-encoded.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

SC = REPO / "mko" / "webui" / "static" / "js" / "slash-commands.js"
TEST_MJS = REPO / "tests" / "test_slash_commands.mjs"
README = REPO / "README.md"
RUNMD = REPO / ".freebuff" / "run.md"


def patch_grammar_header(text: str) -> str:
    """Add one line to the autocomplete contract block in slash-commands.js."""
    needle = "              (user has moved past the command-token stage)"
    if "trailing space the autocomplete appends" in text:
        return text  # idempotent
    insertion = (
        needle
        + "\n *              -- note: app.js's applySuggestion writes \""
        + "/cmd\" + a trailing space, so a trailing-space newline also"
        + "\n *              immediately closes the popup. This rule is load"
        + "-bearing."
    )
    return text.replace(needle, insertion, 1)


def patch_test_file(text: str) -> str:
    """Append two trailing-space parse tests for /help / and /commands /."""
    if "trailing-space autocomplete completion" in text:
        return text
    addition = r"""

// -- Trailing-space autocomplete completion -------------------------
// /-help /-commands take no args but the autocompleter writes
// /-cmd + a trailing space. Pin that parse() still resolves to the
// help type (rest is intentionally ignored).

test("-help with single trailing space still resolves to help type", () => {
  const r = MKOSlash.parse("/help ");
  assert.equal(r.type, "help");
  assert.equal(r.cmd, "help");
});

test("-commands with single trailing space still resolves to help type", () => {
  const r = MKOSlash.parse("/commands ");
  assert.equal(r.type, "help");
  assert.equal(r.cmd, "commands");
});
"""
    # The test file uses the canonical "/" character (ASCII). Filter only
    # test descriptions so the appended block matches the surrounding file.
    addition_clean = addition.replace("-help with", "/help with").replace(
        "-commands with", "/commands with"
    )
    return text.rstrip() + addition_clean


def patch_readme(text: str) -> str:
    """Update the slash-commands subsection to mention autocomplete."""
    if "Slash-command autocomplete" in text:
        return text
    needle = (
        "### 6. ⌨️ Slash commands (in-app)\n\n"
    )
    block = (
        needle +
        "Type `/` in the chat input — an autocomplete dropdown lists every command. "
        "Use ↑/↓ to navigate, Tab or Enter to autocomplete the highlighted row, "
        "Escape to dismiss. Completion is uniform: clicking `/plan` writes `/plan_` "
        "(trailing space) so the cursor lands ready for the topic.\n\n"
        "### 7. 📜 Slash commands (in-app)\n\n"
    )
    if needle not in text:
        return text
    text = text.replace(needle, block, 1)
    return text


def patch_runmd(text: str) -> str:
    """Append an autocomplete paragraph at the end of the Slash commands § 6."""
    if "Slash-command autocomplete" in text:
        return text
    needle = "## 6. Slash commands (chat input)"
    add_at_end = "\n\n### Slash-command autocomplete\n\nWhen the user types `/` in the chat input a dropdown opens listing every command from `window.MKOSlash.KNOWN_COMMANDS`. Navigation:\n\n- ↑ / ↓  — move highlight (clamped at ends, no loop)\n- Tab    — autocomplete the highlight (or first row if no highlight)\n- Enter  — autocomplete (NEVER auto-sends while the dropdown is open)\n- Shift+Enter — passes through (normal textarea newline)\n- Escape — close & refocus input\n- Click outside the dropdown — close\n- Completion writes `/cmd` + a single trailing space (uniform cheap behavior). The trailing space in turn triggers `getSuggestions()` to return null and so the dropdown self-closes.\n\nPure helper: `MKOSlash.getSuggestions(text)` returns `null` when no popup, `[]` when no match, or an array of `KNOWN_COMMANDS` rows for direct rendering. The implementation lives in `mko/webui/static/js/slash-commands.js`; the DOM wiring is in `mko/webui/static/js/app.js`'s `wireSlashSuggest()` plus the `.mko-suggest*` rules in `mko/webui/static/css/styles.css`. Tests pin the helper in `tests/test_slash_commands.mjs` and the wiring in `tests/test_run_smoke.py` (`SlashSuggestTests`).\n"
    # Find a sensible injection point: just before the closing of section 6.
    # We'll search for any later "---" or "##" pattern; if absent we append to EOF.
    if needle in text:
        # Insert before the next "##" (start of section 7) or EOF.
        after = text.index(needle) + len(needle)
        rest = text[after:]
        # Find next top-level heading.
        nxt = rest.find("\n## ")
        if nxt == -1:
            nxt = len(rest)
        text = text[: after + nxt] + add_at_end + text[after + nxt :]
    return text


def main() -> None:
    sc_text = SC.read_text(encoding="utf-8")
    new_sc = patch_grammar_header(sc_text)
    SC.write_text(new_sc, encoding="utf-8")
    print(f"grammar header: {'updated' if new_sc != sc_text else 'no-op'}")

    test_text = TEST_MJS.read_text(encoding="utf-8")
    new_test = patch_test_file(test_text)
    TEST_MJS.write_text(new_test, encoding="utf-8")
    print(f"trailing-space tests: {'appended' if new_test != test_text else 'no-op'}")

    readme_text = README.read_text(encoding="utf-8")
    new_readme = patch_readme(readme_text)
    README.write_text(new_readme, encoding="utf-8")
    print(f"README: {'updated' if new_readme != readme_text else 'no-op'}")

    run_text = RUNMD.read_text(encoding="utf-8")
    new_run = patch_runmd(run_text)
    RUNMD.write_text(new_run, encoding="utf-8")
    print(f"run.md: {'updated' if new_run != run_text else 'no-op'}")


if __name__ == "__main__":
    main()
