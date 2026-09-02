"""
swe_agent/patch.py — SEARCH/REPLACE block parser and applicator.

The patch engine: parses <<<SEARCH/===/>>>REPLACE blocks from model output,
then applies them to source via a 6-pass fuzzy-matching cascade:

  1. Exact match
  2. CRLF-normalized + trailing-whitespace stripped per line
  3. Tab ↔ 4-space equivalence
  4. Outer blank-line strip (model pads SEARCH with leading/trailing newlines)
  5. First-line anchor window:
       Pass 1 — exact anchor match, 60% threshold
       Pass 2 — paren-stripped anchor (handles signature drift), 50% / ≥2 lines
  6. Prefix-line match (model truncated single-line SEARCH)

All functions are pure (no I/O, no mutable state). Fully testable in isolation.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("determinex_swe")

_LINE_NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*\|\s?")


def _normalize_for_match(s: str) -> str:
    """Normalize a code string for fuzzy matching: CRLF→LF, trailing spaces stripped per line."""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(l.rstrip() for l in s.split("\n"))


def _strip_block_fences(text: str) -> str:
    """Remove markdown code fences that small models sometimes wrap around SEARCH/REPLACE content."""
    lines = text.split("\n")
    if lines and re.match(r"^\s*`{3}", lines[0]):
        lines = lines[1:]
    if lines and re.match(r"^\s*`{3}\s*$", lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines)


def _strip_line_number_prefixes(text: str) -> str:
    """
    Strip `NNN | ` line-number prefixes that models copy from the numbered edit window.
    e.g. `  60 |     separable_matrix = ...` → `    separable_matrix = ...`
    """
    lines = text.split("\n")
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return text
    if any(_LINE_NUM_PREFIX_RE.match(l) for l in non_empty):
        return "\n".join(
            _LINE_NUM_PREFIX_RE.sub("", l) if l.strip() and _LINE_NUM_PREFIX_RE.match(l) else l
            for l in lines
        )
    return text


def _parse_search_replace_blocks(raw: str) -> list[tuple[str, str]]:
    """
    Parse <<<SEARCH / === / >>>REPLACE block sequences from model output.
    Returns list of (search_text, replace_text) pairs.
    Rejects no-op blocks (search == replace after normalization).

    Two-pass parsing:
      Pass 1 (strict): exact delimiters — <<<SEARCH, ===, >>>REPLACE
      Pass 2 (lenient): handles model variations:
        - extra text on SEARCH/REPLACE marker lines (e.g. "<<<SEARCH: file.py")
        - longer separator runs ("====", "-----")
        - ">>>" without "REPLACE" keyword
    """

    def _build_blocks(pattern: re.Pattern) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for m in pattern.finditer(raw):
            search = _strip_line_number_prefixes(_strip_block_fences(m.group(1)))
            replace = _strip_line_number_prefixes(_strip_block_fences(m.group(2)))
            if search.strip() == replace.strip():
                log.debug("_parse_search_replace_blocks: rejecting no-op block")
                continue
            result.append((search, replace))
        return result

    # Pass 1: strict
    strict = re.compile(
        r"<<<\s*SEARCH\s*\n(.*?)\n===\s*\n(.*?)\n>>>\s*REPLACE",
        re.DOTALL,
    )
    blocks = _build_blocks(strict)
    if blocks:
        return blocks

    # Pass 2: lenient — handles format variations DeepSeek/Anthropic occasionally emit
    lenient = re.compile(
        r"<<<\s*SEARCH[^\n]*\n(.*?)\n={3,}[^\n]*\n(.*?)\n>{3}[^\n]*",
        re.DOTALL,
    )
    blocks = _build_blocks(lenient)
    if blocks:
        log.debug("_parse_search_replace_blocks: used lenient parser (%d block(s))", len(blocks))
    return blocks


def _apply_search_replace_blocks(
    source: str,
    blocks: list[tuple[str, str]],
) -> tuple[str, list[str]]:
    """
    Apply search/replace blocks to source. Returns (modified_source, failed_searches).

    Matching strategy (most to least strict, 6 passes):
      1. Exact match
      2. CRLF-normalized + trailing-whitespace stripped per line
      3. Tab ↔ 4-space equivalence
      4. Outer blank-line strip
      5. First-line anchor window (two sub-passes: exact anchor / paren-stripped anchor)
      6. Prefix-line match (single truncated SEARCH line)
    """
    result = source
    failed: list[str] = []

    for search, replace in blocks:
        # 0. Empty SEARCH -- only ever legal as "create this new file".
        # `"" in anything` is ALWAYS True, so without this guard an empty
        # SEARCH fell into pass 1 and did result.replace("", replace, 1),
        # splicing the replacement in at offset 0 with no separator and
        # silently corrupting the file (observed live: a local-agent turn
        # turned `def add(a,b):` into `return a - bdef add(a,b):`, a syntax
        # error written straight to disk). Fail closed on a non-empty file
        # rather than emit garbage -- the caller reports it as a skipped
        # block, which is honest and visible, instead of a broken source file.
        if not search.strip():
            if not result.strip():
                result = replace
            else:
                failed.append("<empty SEARCH against non-empty file>")
            continue

        # 1. Exact match
        if search in result:
            new_result = result.replace(search, replace, 1)
            if new_result != result:
                result = new_result
                continue
            log.debug("exact hit but no change — rejecting")
            failed.append(search[:60])
            continue

        # 2. Trailing-whitespace + CRLF normalized
        norm_src = _normalize_for_match(result)
        norm_srch = _normalize_for_match(search)
        if norm_srch and norm_srch in norm_src:
            idx = norm_src.find(norm_srch)
            orig_lines = result.split("\n")
            lines_before = norm_src[:idx].count("\n")
            match_lines = norm_srch.count("\n") + 1
            new_result = (
                "\n".join(orig_lines[:lines_before])
                + ("\n" if lines_before > 0 else "")
                + replace
                + ("\n" if lines_before + match_lines < len(orig_lines) else "")
                + "\n".join(orig_lines[lines_before + match_lines :])
            )
            if new_result != result:
                result = new_result
                log.debug("fuzzy match (trailing-ws) succeeded")
                continue

        # 3. Tab ↔ 4-space equivalence
        tab4_src = _normalize_for_match(result).replace("\t", "    ")
        tab4_srch = _normalize_for_match(search).replace("\t", "    ")
        if tab4_srch and tab4_srch in tab4_src:
            new_result = norm_src.replace(
                norm_srch if norm_srch in norm_src else tab4_srch, replace, 1
            )
            if new_result != result and new_result != norm_src:
                result = new_result
                log.debug("fuzzy match (tab≡4sp) succeeded")
                continue

        # 4. Outer blank-line strip
        search_stripped = search.strip("\n")
        if search_stripped and search_stripped != search and search_stripped in result:
            new_result = result.replace(search_stripped, replace, 1)
            if new_result != result:
                result = new_result
                log.debug("fuzzy match (outer-newline strip) succeeded")
                continue
        norm_stripped = _normalize_for_match(search_stripped)
        if norm_stripped and norm_stripped != norm_srch and norm_stripped in norm_src:
            idx = norm_src.find(norm_stripped)
            orig_lines = result.split("\n")
            lines_before = norm_src[:idx].count("\n")
            match_lines = norm_stripped.count("\n") + 1
            new_result = (
                "\n".join(orig_lines[:lines_before])
                + ("\n" if lines_before > 0 else "")
                + replace
                + ("\n" if lines_before + match_lines < len(orig_lines) else "")
                + "\n".join(orig_lines[lines_before + match_lines :])
            )
            if new_result != result:
                result = new_result
                log.debug("fuzzy match (outer-newline strip + norm) succeeded")
                continue

        # 5. First-line anchor window (two passes)
        #    Pass 1: exact anchor, 60% threshold
        #    Pass 2: paren-stripped anchor, 50% threshold, ≥2 lines
        search_lines_ne = [l for l in search.split("\n") if l.strip()]
        anchor_matched = False
        _MIN_ANCHOR_BASE = 8

        if search_lines_ne:
            anchor_norm = _normalize_for_match(search_lines_ne[0])
            anchor_base = anchor_norm.split("(")[0].rstrip()
            src_lines_all = result.split("\n")

            if anchor_norm:
                for pass_num in (1, 2):
                    if anchor_matched:
                        break
                    for si, src_line in enumerate(src_lines_all):
                        src_norm_si = _normalize_for_match(src_line)
                        if pass_num == 1:
                            if src_norm_si != anchor_norm:
                                continue
                            threshold, min_lines = 0.6, 1
                        else:
                            src_base_si = src_norm_si.split("(")[0].rstrip()
                            if (
                                len(anchor_base) < _MIN_ANCHOR_BASE
                                or src_base_si != anchor_base
                                or src_norm_si == anchor_norm
                            ):
                                continue
                            threshold, min_lines = 0.5, 2

                        window_size = len(search.split("\n"))
                        window_lines = src_lines_all[si : si + window_size]
                        window_norm = _normalize_for_match("\n".join(window_lines))
                        matching = sum(
                            1 for sl in search_lines_ne if _normalize_for_match(sl) in window_norm
                        )
                        if matching >= max(min_lines, int(len(search_lines_ne) * threshold)):
                            new_result = (
                                "\n".join(src_lines_all[:si])
                                + ("\n" if si > 0 else "")
                                + replace
                                + ("\n" if si + window_size < len(src_lines_all) else "")
                                + "\n".join(src_lines_all[si + window_size :])
                            )
                            if new_result != result:
                                result = new_result
                                log.debug(
                                    "fuzzy match (anchor-window pass=%d %d/%d) succeeded",
                                    pass_num,
                                    matching,
                                    len(search_lines_ne),
                                )
                                anchor_matched = True
                                break

        if anchor_matched:
            continue

        # 6. Prefix-line match — model truncated single-line SEARCH
        search_single = search.strip("\n")
        if "\n" not in search_single.strip() and search_single.strip():
            needle = _normalize_for_match(search_single)
            src_lines_all = result.split("\n")
            prefix_matched = False
            for si, src_line in enumerate(src_lines_all):
                src_norm = _normalize_for_match(src_line)
                if src_norm.startswith(needle) and len(src_norm) > len(needle):
                    new_result = (
                        "\n".join(src_lines_all[:si])
                        + ("\n" if si > 0 else "")
                        + replace
                        + ("\n" if si + 1 < len(src_lines_all) else "")
                        + "\n".join(src_lines_all[si + 1 :])
                    )
                    if new_result != result:
                        result = new_result
                        log.debug("fuzzy match (prefix-line) succeeded")
                        prefix_matched = True
                        break
            if prefix_matched:
                continue

        # 7. Comment-stripped match — model included a pure comment line (e.g.
        #    "# Replace x_NNNN separator...") that doesn't exist in the obfuscated
        #    source (comments are stripped during cloak obfuscation). Remove lines
        #    that are purely comment markers and retry the search with the remaining
        #    code lines. The replacement is applied as-is (it may legitimately add
        #    a comment back).
        _COMMENT_LINE_RE = re.compile(r"^\s*(?:#|//|/\*|\*)")
        search_no_comments = "\n".join(
            l for l in search.split("\n") if not _COMMENT_LINE_RE.match(l)
        )
        if search_no_comments.strip() and search_no_comments != search:
            if search_no_comments in result:
                new_result = result.replace(search_no_comments, replace, 1)
                if new_result != result:
                    result = new_result
                    log.debug("fuzzy match (comment-stripped) succeeded")
                    continue
            # Also try normalized version
            norm_no_comments = _normalize_for_match(search_no_comments)
            norm_result = _normalize_for_match(result)
            if norm_no_comments in norm_result:
                idx = norm_result.find(norm_no_comments)
                orig_lines = result.split("\n")
                norm_lines = norm_result.split("\n")
                # Find the line offset
                chars = 0
                start_line = 0
                for li, nl in enumerate(norm_lines):
                    if chars >= idx:
                        start_line = li
                        break
                    chars += len(nl) + 1
                n_lines = len(search_no_comments.split("\n"))
                new_result = (
                    "\n".join(orig_lines[:start_line])
                    + ("\n" if start_line > 0 else "")
                    + replace
                    + ("\n" if start_line + n_lines < len(orig_lines) else "")
                    + "\n".join(orig_lines[start_line + n_lines :])
                )
                if new_result != result:
                    result = new_result
                    log.debug("fuzzy match (comment-stripped+norm) succeeded")
                    continue

        failed.append(search[:60])
        log.debug("SEARCH not found: %r...", search[:80])

    return result, failed
