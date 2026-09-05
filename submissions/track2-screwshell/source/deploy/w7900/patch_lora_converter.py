#!/usr/bin/env python3
"""
Patch llama.cpp's convert_lora_to_gguf.py so it can convert Qwen3.6 hybrid-arch LoRAs.

WHY THIS EXISTS
---------------
Qwen3.6-27B uses merged QKV projections. Upstream `TextModel._reorder_v_heads()`
calls `tensor.reshape(...)` on the V-head slice. For a LoRA the tensor is a
`LoraTorchTensor` (a lazy B@A pair), whose `.reshape()` raises
`NotImplementedError` for that shape change. Result:

    NotImplementedError  (convert_lora_to_gguf.py -> LoraTorchTensor.reshape)

so `btl3` and `rag_n7` cannot be converted to GGUF, and llama.cpp's `--lora`
only accepts GGUF. Only `cybersec` worked, because it ships a prebuilt GGUF on
HuggingFace and never touches the merged-QKV layers.

THE FIX (upstream PR #24627 direction, still unmerged as of 2026-08)
Instead of reshaping the fused tensor, compute the permutation on an index
vector and `index_select()` the A or B factor:
  - reordering along the LAST dim  -> permute columns of A
  - reordering along any other dim -> permute rows of B
This is mathematically identical to reordering the materialised B@A product,
but never materialises it.

USAGE
-----
    python3 patch_lora_converter.py /opt/llama.cpp/convert_lora_to_gguf.py

Idempotent: running it twice is a no-op. Verified against llama.cpp master
272700b3 (2026-08-02) on gfx1100 / W7900; produced working GGUF for both
badtheorylabs/BTL-3 and lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "def _reorder_v_heads(self, tensor, dim, num_k_heads, num_v_per_k, head_dim):"

# Anchor: the next method defined in the dynamically-built LoraModel subclass.
ANCHOR = "            def modify_tensors(self, data_torch: Tensor, name: str, bid: int | None)"

PATCH = '''            def _reorder_v_heads(self, tensor, dim, num_k_heads, num_v_per_k, head_dim):
                # Qwen3.6 merged-QKV LoRA support (upstream PR #24627 direction).
                # LoraTorchTensor cannot .reshape(); permute the A/B factor instead.
                if not isinstance(tensor, LoraTorchTensor):
                    return super()._reorder_v_heads(tensor, dim, num_k_heads, num_v_per_k, head_dim)
                shape = tensor.shape
                if dim < 0:
                    dim += len(shape)
                lora_a, lora_b = tensor.get_lora_A_B()
                if dim == len(shape) - 1:
                    perm = super()._reorder_v_heads(
                        torch.arange(shape[dim], dtype=torch.long).unsqueeze(0),
                        1, num_k_heads, num_v_per_k, head_dim).squeeze(0)
                    lora_a = lora_a.index_select(-1, perm)
                else:
                    perm = super()._reorder_v_heads(
                        torch.arange(shape[dim], dtype=torch.long).unsqueeze(-1),
                        0, num_k_heads, num_v_per_k, head_dim).squeeze(-1)
                    lora_b = lora_b.index_select(dim, perm)
                return LoraTorchTensor(lora_a, lora_b)

'''


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        print("error: expected exactly one argument (path to convert_lora_to_gguf.py)")
        return 2

    target = Path(argv[1])
    if not target.is_file():
        print(f"error: not a file: {target}")
        return 1

    source = target.read_text(encoding="utf-8")

    if MARKER in source:
        print(f"already patched, nothing to do: {target}")
        return 0

    if ANCHOR not in source:
        print(
            "error: anchor not found -- llama.cpp upstream has changed.\n"
            f"       expected a line starting with:\n         {ANCHOR}\n"
            "       Re-derive the patch against the current master before proceeding."
        )
        return 1

    if source.count(ANCHOR) != 1:
        print(f"error: anchor is ambiguous ({source.count(ANCHOR)} matches); refusing to patch.")
        return 1

    backup = target.with_suffix(target.suffix + ".orig")
    if not backup.exists():
        shutil.copy2(target, backup)
        print(f"backup written: {backup}")

    target.write_text(source.replace(ANCHOR, PATCH + ANCHOR, 1), encoding="utf-8")
    print(f"patched: {target}")
    print("now convert with e.g.:")
    print("  python3 convert_lora_to_gguf.py --base <BASE_HF_DIR> --outtype f16 \\")
    print("      --outfile loras/btl3/adapter.gguf <PEFT_LORA_DIR>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
