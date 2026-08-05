"""
determinex_cloak/transformer.py — Components 4 & 5: ASTTransformer + IssueTextTransformer.

Python AST-based identifier substitution (forward map).
Also handles comment stripping and docstring token substitution (Option D).
"""

from __future__ import annotations

import ast
import logging
import re

from .symbol_map import SymbolMap

log = logging.getLogger("determinex_cloak")


class _CloakTransformer(ast.NodeTransformer):
    """Substitute private identifier nodes using the forward symbol map."""

    def __init__(self, forward: dict[str, str]) -> None:
        self._f = forward

    def _s(self, name: str) -> str:
        return self._f.get(name, name)

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self._s(node.id)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.name = self._s(node.name)
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        node.name = self._s(node.name)
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = self._s(node.arg)
        self.generic_visit(node)
        return node

    def visit_Global(self, node: ast.Global) -> ast.Global:
        node.names = [self._s(n) for n in node.names]
        return node

    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.Nonlocal:
        node.names = [self._s(n) for n in node.names]
        return node


def _strip_inline_comment(line: str) -> str:
    """Strip trailing # comment, respecting string literals."""
    in_str: str | None = None
    i = 0
    while i < len(line):
        c = line[i]
        if in_str == "triple":
            for delim in ('"""', "'''"):
                if line[i : i + 3] == delim:
                    in_str = None
                    i += 3
                    break
            else:
                i += 1
        elif in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            for delim in ('"""', "'''"):
                if line[i : i + 3] == delim:
                    in_str = "triple"
                    i += 3
                    break
            else:
                if c in ('"', "'"):
                    in_str = c
                elif c == "#":
                    return line[:i].rstrip()
        i += 1
    return line


def _process_source_text(source: str, forward: dict[str, str]) -> str:
    """
    Option D docstring handling:
      - Strip inline # comments
      - Substitute private identifier tokens in triple-quoted strings

    Operates line-by-line. Tracks triple-quote state.
    """
    if not forward:
        return source

    sorted_keys = sorted(forward.keys(), key=len, reverse=True)
    _pattern = (
        re.compile(r"\b(?:" + "|".join(re.escape(k) for k in sorted_keys) + r")\b")
        if sorted_keys
        else None
    )

    def _subst(text: str) -> str:
        if _pattern is None:
            return text
        return _pattern.sub(lambda m: forward.get(m.group(), m.group()), text)

    lines = source.splitlines(keepends=True)
    result: list[str] = []
    in_triple = False
    triple_delim = ""

    for line in lines:
        if not in_triple:
            stripped = line.rstrip()
            entered = False
            for delim in ('"""', "'''"):
                count = stripped.count(delim)
                if count > 0 and count % 2 == 1:
                    in_triple = True
                    triple_delim = delim
                    entered = True
                    break

            if entered:
                result.append(_subst(line))
            else:
                eol = "\n" if line.endswith("\n") else ""
                stripped_line = line.rstrip("\n")
                # Pure comment line: obfuscate identifiers inside it but keep
                # the '#' structure so the obfuscated source round-trips cleanly
                # back to the original when restored. Stripping these to blank
                # causes a ~239-line diff on files like fitsrec.py, blowing the
                # 500-line patch guard on every attempt.
                if stripped_line.lstrip().startswith("#"):
                    result.append(_subst(stripped_line) + eol)
                else:
                    result.append(_strip_inline_comment(stripped_line) + eol)
        else:
            result.append(_subst(line))
            if triple_delim in line.rstrip():
                count = line.rstrip().count(triple_delim)
                if count % 2 == 1:
                    in_triple = False
                    triple_delim = ""

    return "".join(result)


def obfuscate_source(source: str, symbol_map: SymbolMap) -> str:
    """
    Format-preserving obfuscation pipeline for one Python source file.
    Phase 1: comment stripping + docstring token substitution (text-level)
    Phase 2: text-level word-boundary regex replacement for all private identifiers

    Does NOT use ast.unparse() — formatting is preserved exactly.
    """
    # FAIL-CLOSED INVARIANT: any obfuscation failure raises CloakObfuscationError.
    # The previous silent-fallthrough (`except ... return source`) leaked plaintext
    # source to the cloud API whenever obfuscation crashed. Callers (the SWE-bench
    # and ProgramBench agent loops) are required to catch this and abort the API
    # call rather than send unredacted source.
    try:
        processed = _process_source_text(source, symbol_map.forward)
        if not symbol_map.forward:
            return processed
        sorted_keys = sorted(symbol_map.forward.keys(), key=len, reverse=True)
        result = processed
        for key in sorted_keys:
            result = re.sub(r"\b" + re.escape(key) + r"\b", symbol_map.forward[key], result)
        return result
    except Exception as e:
        # Import here to avoid a top-level cycle (determinex_cloak/__init__.py
        # imports from transformer).
        from . import CloakObfuscationError

        log.error("Cloak: obfuscation FAILED — refusing to return plaintext: %s", e)
        raise CloakObfuscationError(
            path="",
            cause=e,
            source_len=len(source) if source else 0,
        ) from e


def obfuscate_issue_text(issue_text: str, symbol_map: SymbolMap) -> str:
    """
    Apply forward map to issue description / problem statement text.
    Length-descending sort prevents partial matches.
    """
    if not symbol_map.forward:
        return issue_text
    sorted_keys = sorted(symbol_map.forward.keys(), key=len, reverse=True)
    result = issue_text
    for key in sorted_keys:
        result = re.sub(r"\b" + re.escape(key) + r"\b", symbol_map.forward[key], result)
    return result
