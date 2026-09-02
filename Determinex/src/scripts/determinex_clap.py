#!/usr/bin/env python3
"""Determinex clap-emulation helper.

Most ProgramBench tools are Rust binaries built on `clap`, whose argument-error
output is byte-for-byte regular. Reimplementations kept hand-rolling these error
strings per tool and guessing the metavars -- the single biggest avoidable
failure class (e.g. hex had 80x parametrized `a value is required ...` tests).

This module produces clap-exact errors and parses a small option spec, so a
reimpl declares its surface once (ideally seeded from
determinex_term_extractor's extracted flags + metavars) and inherits correct
behavior for: unknown flag, missing value, invalid value, possible-values.

Not a full clap clone -- just the high-frequency, exactly-specified surface.
Tools with bespoke help/usage still print their own help text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRY_HELP = "\n\nFor more information, try '--help'.\n"


def err_unexpected(arg: str, *, tip: str | None = None) -> str:
    s = f"error: unexpected argument '{arg}' found\n"
    if tip:
        s += f"\n  tip: {tip}\n"
    return s + "\nFor more information, try '--help'.\n"


def err_value_required(flag: str, metavar: str) -> str:
    return f"error: a value is required for '{flag} <{metavar}>'{TRY_HELP}"


def err_invalid_value(val: str, flag: str, metavar: str, possible: list[str] | None = None) -> str:
    s = f"error: invalid value '{val}' for '{flag} <{metavar}>'"
    if possible:
        s += f"\n  [possible values: {', '.join(possible)}]"
    return s + TRY_HELP


def err_invalid_value_pos(val: str, argname: str, possible: list[str] | None = None) -> str:
    """Invalid value for a positional <ARG>."""
    s = f"error: invalid value '{val}' for '<{argname}>'"
    if possible:
        s += f"\n  [possible values: {', '.join(possible)}]"
    return s + TRY_HELP


@dataclass
class Opt:
    short: str | None  # e.g. "c"
    long: str | None  # e.g. "cols"
    metavar: str | None  # e.g. "columns"; None => boolean flag
    possible: list[str] | None = None
    is_int: bool = False
    is_float: bool = False
    dest: str | None = None

    @property
    def takes_value(self):
        return self.metavar is not None

    @property
    def name(self):
        return self.dest or (self.long or self.short)

    def display(self):
        return f"--{self.long}" if self.long else f"-{self.short}"


@dataclass
class ClapError(Exception):
    message: str
    code: int = 2


@dataclass
class Parser:
    opts: list = field(default_factory=list)
    allow_positionals: int = 99
    _by_long: dict = field(default_factory=dict, init=False)
    _by_short: dict = field(default_factory=dict, init=False)

    def add(
        self,
        short=None,
        long=None,
        metavar=None,
        possible=None,
        is_int=False,
        is_float=False,
        dest=None,
    ):
        o = Opt(short, long, metavar, possible, is_int, is_float, dest)
        self.opts.append(o)
        if long:
            self._by_long[long] = o
        if short:
            self._by_short[short] = o
        return self

    def _coerce(self, o: Opt, val: str):
        if o.possible and val not in o.possible:
            raise ClapError(err_invalid_value(val, o.display(), o.metavar, o.possible))
        if o.is_int:
            try:
                return int(val)
            except ValueError:
                raise ClapError(err_invalid_value(val, o.display(), o.metavar))
        if o.is_float:
            try:
                return float(val)
            except ValueError:
                raise ClapError(err_invalid_value(val, o.display(), o.metavar))
        return val

    def parse(self, argv: list[str]):
        """Return (values: dict, positionals: list). Raises ClapError(rc=2)."""
        values: dict = {}
        positionals: list[str] = []
        i = 0
        end = False
        while i < len(argv):
            a = argv[i]
            if end:
                positionals.append(a)
                i += 1
                continue
            if a == "--":
                end = True
                i += 1
                continue
            if a.startswith("--"):
                key, eq, inline = a[2:].partition("=")
                o = self._by_long.get(key)
                if o is None:
                    raise ClapError(err_unexpected(a))
                if not o.takes_value:
                    values[o.name] = True
                elif eq:
                    values[o.name] = self._coerce(o, inline)
                else:
                    if i + 1 >= len(argv):
                        raise ClapError(err_value_required(o.display(), o.metavar))
                    values[o.name] = self._coerce(o, argv[i + 1])
                    i += 1
            elif a.startswith("-") and len(a) > 1:
                chars = a[1:]
                j = 0
                while j < len(chars):
                    ch = chars[j]
                    o = self._by_short.get(ch)
                    if o is None:
                        raise ClapError(err_unexpected(a if len(chars) == 1 else f"-{ch}"))
                    if not o.takes_value:
                        values[o.name] = True
                        j += 1
                        continue
                    rest = chars[j + 1 :]
                    if rest:
                        values[o.name] = self._coerce(o, rest)
                    else:
                        if i + 1 >= len(argv):
                            raise ClapError(err_value_required(o.display(), o.metavar))
                        values[o.name] = self._coerce(o, argv[i + 1])
                        i += 1
                    break
            else:
                positionals.append(a)
            i += 1
        if len(positionals) > self.allow_positionals:
            raise ClapError(err_unexpected(positionals[self.allow_positionals]))
        return values, positionals


def from_terms(terms: dict) -> Parser:
    """Seed a Parser from a determinex_term_extractor term dict (best-effort):
    every `--flag <metavar>` template becomes a value-taking option."""
    p = Parser()
    seen = set()
    for item in terms.get("value_required_templates", []):
        tmpl = item["term"]  # e.g. "--cols <columns>"
        if " <" in tmpl and tmpl.endswith(">"):
            flag, meta = tmpl.split(" <", 1)
            meta = meta[:-1]
            longname = flag.lstrip("-")
            if longname not in seen and flag.startswith("--"):
                p.add(long=longname, metavar=meta)
                seen.add(longname)
    return p


if __name__ == "__main__":
    # tiny self-test
    p = Parser().add(short="c", long="cols", metavar="columns", is_int=True)
    p.add(short="f", long="format", metavar="format", possible=["o", "x", "X", "b"])
    try:
        p.parse(["--cols"])
    except ClapError as e:
        assert "a value is required for '--cols <columns>'" in e.message, e.message
    try:
        p.parse(["-f", "z"])
    except ClapError as e:
        assert "invalid value 'z' for '--format <format>'" in e.message
        assert "[possible values: o, x, X, b]" in e.message
    v, pos = p.parse(["-c", "4", "file.txt"])
    assert v["cols"] == 4 and pos == ["file.txt"]
    print("determinex_clap self-test OK")
