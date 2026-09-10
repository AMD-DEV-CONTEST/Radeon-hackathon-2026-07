from __future__ import annotations

import os
import subprocess
import sys

import pytest

from specstyle.errors import DomainError
from specstyle.workflow import _job_store_codec as codec


def test_codec_import_does_not_load_workflow_state_semantics() -> None:
    program = """
import sys
import specstyle.workflow._job_store_codec
assert "specstyle.workflow.state_machine" not in sys.modules
"""
    environment = {**os.environ, "PYTHONPATH": "src"}
    completed = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr


def test_parse_canonical_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    for data in (b'{"x":1,"x":1}', b'{"x": 1}', b'{"x":NaN}'):
        with pytest.raises(DomainError):
            codec.parse_canonical(data)


def test_canonical_json_uses_sorted_compact_utf8() -> None:
    assert codec.canonical_json({"z": 1, "a": "\u4e2d"}) == (
        b'{"a":"\xe4\xb8\xad","z":1}'
    )
