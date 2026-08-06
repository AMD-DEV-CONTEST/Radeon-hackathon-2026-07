# vllm_rocm_patch.py — Monkey-patch for vLLM 0.26.0 + torch 2.9.1 (ROCm 6.3)
#
# Problem:
#   vLLM 0.26.0 calls torch.accelerator.get_memory_info(device) in
#   vllm/utils/mem_utils.py to snapshot GPU memory. This API was added
#   in PyTorch 2.10+. ROCm 6.3 only provides torch 2.9.1, which lacks it.
#
# Solution:
#   Patch torch.accelerator.get_memory_info to delegate to
#   torch.cuda.mem_get_info(device), which exists in torch 2.9.1
#   and returns (free_bytes, total_bytes) — same signature.
#
# Usage:
#   Set PYTHONPATH to include this file's directory, or import it
#   before vLLM. start_vllm.sh handles this automatically.

import torch

if not hasattr(torch.accelerator, "get_memory_info"):
    def _get_memory_info(device=None):
        """Compatibility shim: torch.accelerator.get_memory_info for torch < 2.10.

        Delegates to torch.cuda.mem_get_info which exists in torch 2.9.1
        and returns (free_memory, total_memory) in bytes.
        """
        if device is None:
            device = torch.cuda.current_device()
        free, total = torch.cuda.mem_get_info(device)
        return free, total

    torch.accelerator.get_memory_info = _get_memory_info
