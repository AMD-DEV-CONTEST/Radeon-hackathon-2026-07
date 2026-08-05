"""
Regression test for the "gron -u" bug: propose_probes() strips a model-echoed program
name from the front of an exploration invocation. Found live during a real
determinex_reimpl_drive run on gron -- the model ignored the "flags only, after the
program name" instruction and returned lines like "gron -u", so every resulting Probe's
argv was ['gron', '-u'] instead of ['-u']. The reference binary then treated 'gron' as a
positional filename argument and errored with "open gron: no such file or directory" --
a nonsense assertion that made every downstream verified-search station score 0.00
trying to byte-match a bogus filesystem error instead of real CLI behavior.
"""

from __future__ import annotations

import determinex_observe as OBS


def _fake_generate(lines):
    def generate(prompt, temp):
        return "\n".join(lines)

    return generate


def test_propose_probes_strips_leading_program_name_token():
    probes = OBS.propose_probes(
        help_text="usage: gron [flags]",
        docs="",
        sample_inputs=[],
        generate=_fake_generate(["gron -u", "gron -v"]),
        n=10,
    )
    assert [p.argv for p in probes] == [["-u"], ["-v"]]


def test_propose_probes_keeps_well_formed_flag_only_lines():
    probes = OBS.propose_probes(
        help_text="usage: tool [flags]",
        docs="",
        sample_inputs=[],
        generate=_fake_generate(["--style rounded", "--number --tsv"]),
        n=10,
    )
    assert [p.argv for p in probes] == [["--style", "rounded"], ["--number", "--tsv"]]


def test_propose_probes_drops_lines_with_no_flag_at_all():
    probes = OBS.propose_probes(
        help_text="usage: tool [flags]",
        docs="",
        sample_inputs=[],
        generate=_fake_generate(["gron somefile.json", "-u"]),
        n=10,
    )
    assert [p.argv for p in probes] == [["-u"]]
