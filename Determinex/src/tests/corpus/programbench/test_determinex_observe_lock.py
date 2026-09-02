import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))


def test_observe_decodes_binary_process_output_with_replacement():
    import subprocess

    import determinex_observe as observe

    cp = subprocess.CompletedProcess(
        args=["tool"],
        returncode=0,
        stdout=b"ok\x80\n",
        stderr=b"warn\xff\n",
    )

    stdout, stderr = observe._completed_text(cp)

    assert stdout == "ok\ufffd\n"
    assert stderr == "warn\ufffd\n"


def test_reimpl_decodes_binary_process_output_with_replacement():
    import determinex_pb_reimpl as reimpl

    assert reimpl._decode_output(b"help\xff\n") == "help\ufffd\n"
