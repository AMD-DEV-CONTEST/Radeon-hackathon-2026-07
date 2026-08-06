"""Adapter discovery for the MoL inference core (torch-free, unit-testable).

Discovery scans ``lora_dir`` for adapter folders and resolves the path the
engine needs:

* **peft backend**      : register every adapter *folder* under ``lora_dir``
  (peft loads the folder directly).
* **llama.cpp backend** (tight mode): the orchestrator restarts the server with
  ONE ``--lora`` at a time, so it needs the LOCAL ``.gguf`` path per adapter
  *name* to substitute into the launch template. The server's ``/lora-adapters``
  ids are therefore NOT used; we resolve the gguf ourselves and skip non-gguf
  adapters (e.g. peft-format safetensors loras).

Forbidden experts (``hermes_s2`` / ``fable5``, see ``docs/TRUTH.md`` §6) are
always skipped here via an ANCHORED exact match (``router.is_forbidden``), so a
stale on-disk copy can never be loaded even though ``DEFAULT_SKILL_MAP`` also
excludes them. The ban is enforced at the *registration* layer, not just
routing. Disk folders are registered under their logical name
(``router.EXPERT_NAME_ALIASES``), so a renamed expert keeps working without
touching the remote directory.
"""
from __future__ import annotations

import glob
import logging
import os

from screwshell.core.router import is_forbidden, logical_expert_name


def discover_adapters(lora_dir: str, backend: str) -> dict[str, str]:
    """Return ``{adapter_name: path}`` for every loadable adapter under ``lora_dir``.

    Keys are LOGICAL expert names, resolved through ``router.logical_expert_name``
    (the single naming authority -- do not invert the alias map here). Forbidden
    experts are never returned. Non-adapter folders (no ``.gguf`` for the
    llama.cpp backend) are skipped.
    """
    adapters: dict[str, str] = {}
    if not os.path.isdir(lora_dir):
        return adapters
    for name in sorted(os.listdir(lora_dir)):
        if is_forbidden(name):
            logging.info("skipping forbidden expert %s", name)
            continue
        d = os.path.join(lora_dir, name)
        if not os.path.isdir(d):
            continue
        if backend == "llamacpp":
            ggufs = glob.glob(os.path.join(d, "*.gguf"))
            if not ggufs:
                continue
            path = sorted(ggufs)[0]
        else:
            path = d
        adapters[logical_expert_name(name)] = path
    return adapters
