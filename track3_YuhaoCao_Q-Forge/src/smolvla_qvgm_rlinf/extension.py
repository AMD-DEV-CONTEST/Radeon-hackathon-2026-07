"""Distributed RLinf extension entry point.

Set ``RLINF_EXT_MODULE=smolvla_qvgm_rlinf.extension`` so every Ray worker
registers the same external model builder.
"""

from .registration import register_smolvla


def register() -> None:
    register_smolvla()
