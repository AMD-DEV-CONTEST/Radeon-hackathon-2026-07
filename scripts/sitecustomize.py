# sitecustomize.py — Auto-imported by Python at startup (when dir is on PYTHONPATH)
#
# Python automatically imports this file at startup (when its directory is in PYTHONPATH),
# including the vLLM API Server process and the EngineCore subprocess.
#
# Patch list:
#   1. infer_schema: accept str subclasses (like vLLM's LayerName) as str type
#      — fixes the LayerName infer_schema error in vLLM 0.26.0 + torch 2.11.0
#      — modifies both __signature__ and __annotations__ (critical fix)
#   2. get_memory_info: compatibility layer for torch < 2.10
#
# Removed old patch files:
#   - vllm_rocm_ops.py (Python _C operator fallback — prebuilt wheel native compilation, not needed)
#   - vllm_rocm_patch.py (get_memory_info monkey-patch — replaced by patch_vllm_source.py)

import os
import sys

# ============================================================
# Patch 1: infer_schema — accept str subclasses (like LayerName) as str
# ============================================================
# vLLM 0.26.0 uses LayerName (a subclass of str) as the parameter type for
# direct_register_custom_op in moe_runner.py. torch 2.11.0's infer_schema
# only does exact type matching and does not recognize str subclasses, causing:
#   ValueError: Parameter layer_name has unsupported type LayerName
#
# The previous patch only modified func.__signature__, but infer_schema may
# read func.__annotations__ directly, so the modification was ineffective.
#
# This patch wraps infer_schema and modifies both before calling:
#   1. func.__signature__ (the signature obtained via inspect.signature)
#   2. func.__annotations__ (directly modifying the annotation dict)
#
# Because sitecustomize.py runs at Python startup (before vLLM is imported),
# by the time vLLM executes `from torch._library.infer_schema import infer_schema`,
# it already obtains the patched version.
#
# This patch applies to all Python processes, including vLLM's EngineCore subprocess.

try:
    import torch._library.infer_schema as _is_mod
    import inspect
    import typing

    if not getattr(_is_mod, '_str_subclass_patched', False):
        _original_infer_schema = _is_mod.infer_schema

    def _fix_annotation(ann):
        """Replace str subclasses in the type annotation with str."""
        # Direct type: a subclass of str (like LayerName)
        if isinstance(ann, type) and issubclass(ann, str) and ann is not str:
            return str
        # Handle typing constructs: Optional[X], Union[X, ...], etc.
        origin = getattr(ann, '__origin__', None)
        args = getattr(ann, '__args__', None)
        if origin is not None and args:
            new_args = tuple(_fix_annotation(a) for a in args)
            if new_args != args:
                try:
                    return origin[new_args]
                except Exception:
                    if origin is typing.Union:
                        return typing.Union[new_args]
        return ann

    def _patched_infer_schema(func, mutates_args=None):
        """Wrap infer_schema, replacing str subclass parameter annotations with str.

        Also modifies __signature__ and __annotations__, ensuring that no matter
        how infer_schema reads the annotations internally, it sees the corrected type.
        """
        try:
            # Method 1: modify __annotations__ (directly modify the annotation dict)
            anns = getattr(func, '__annotations__', None)
            if anns:
                new_anns = {}
                changed = False
                for name, ann in anns.items():
                    new_ann = _fix_annotation(ann)
                    if new_ann is not ann:
                        new_anns[name] = new_ann
                        changed = True
                    else:
                        new_anns[name] = ann
                if changed:
                    try:
                        func.__annotations__ = new_anns
                    except (AttributeError, TypeError):
                        pass

            # Method 2: modify __signature__ (via inspect.signature)
            sig = inspect.signature(func)
            params = dict(sig.parameters)
            changed = False
            for name, param in params.items():
                ann = param.annotation
                if ann is inspect.Parameter.empty:
                    continue
                new_ann = _fix_annotation(ann)
                if new_ann is not ann:
                    params[name] = param.replace(annotation=new_ann)
                    changed = True
            if changed:
                func.__signature__ = sig.replace(parameters=list(params.values()))
        except Exception:
            pass  # fall back to the original infer_schema on patch failure (the original error is raised)
        return _original_infer_schema(func, mutates_args=mutates_args)

    _is_mod.infer_schema = _patched_infer_schema
    _is_mod._str_subclass_patched = True

except Exception:
    pass  # torch not installed or infer_schema module missing, silently skip


# ============================================================
# Patch 2: get_memory_info — compatibility layer for torch < 2.10
# ============================================================
try:
    import torch
    if not hasattr(torch.accelerator, "get_memory_info"):
        def _get_memory_info(device=None):
            if device is None:
                device = torch.cuda.current_device()
            free, total = torch.cuda.mem_get_info(device)
            return free, total
        torch.accelerator.get_memory_info = _get_memory_info
except Exception:
    pass  # torch not installed or non-GPU environment, silently skip
