#!/usr/bin/env python3
"""Patch vLLM source files for ROCm + torch 2.9.1 compatibility.

Fixes two issues when vLLM is installed from PyPI (CUDA wheel) on ROCm:

1. torch.accelerator.get_memory_info() missing (torch 2.10+ API, ROCm has 2.9.1)
   - Patched in: vllm/utils/mem_utils.py and other files calling get_memory_info
   - Fix: delegate to torch.cuda.mem_get_info()

2. torch.ops._C.get_cuda_view_from_cpu_tensor() missing (vllm._C not compiled for ROCm)
   - Patched in: vllm/utils/torch_utils.py and other files calling get_cuda_view_from_cpu_tensor
   - Fix: try C++ operator, fallback to cpu_tensor.to('cuda')

CRITICAL: This script must NOT use `import vllm` to find the vLLM directory,
because a previous broken patch may have made vLLM un-importable. Instead,
it searches sys.path / site-packages directly.

This script can also REPAIR files broken by previous runs of older versions.

Usage:
  python scripts/patch_vllm_source.py
"""

import os
import sys
import glob

# ============================================================
# Patch 1: get_memory_info shim (torch 2.9.1 < 2.10)
# ============================================================

MEM_MARKER = "# ROCm compat: get_memory_info shim (auto-patched)"

MEM_SHIM_CODE = f'''{MEM_MARKER}
# vLLM 0.26.0 uses torch.accelerator.get_memory_info() (added in torch 2.10+).
# ROCm 6.3 only provides torch 2.9.1, so we add a compatibility shim that
# delegates to torch.cuda.mem_get_info(), which exists in 2.9.1 and returns
# (free_bytes, total_bytes) with the same semantics.
try:
    torch.accelerator.get_memory_info
except AttributeError:
    def _rocm_get_memory_info(device=None):
        if device is None:
            device = torch.cuda.current_device()
        free, total = torch.cuda.mem_get_info(device)
        return free, total
    torch.accelerator.get_memory_info = _rocm_get_memory_info'''

# ============================================================
# Patch 2: get_cuda_view_from_cpu_tensor fallback (vllm._C not compiled)
# ============================================================

UVA_MARKER = "# ROCm compat: UVA fallback (auto-patched)"
UVA_FUNC_MARKER = "# ROCm compat: UVA monkey-patch (auto-patched)"


def find_vllm_dir():
    """Find the vLLM installation directory WITHOUT importing vllm.

    Searches sys.path and common venv locations for the vllm package.
    This is critical because a previous broken patch may have made
    `import vllm` fail with IndentationError.
    """
    # Method 1: search sys.path
    for path_entry in sys.path:
        if not path_entry or not os.path.isdir(path_entry):
            continue
        candidate = os.path.join(path_entry, "vllm")
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "__init__.py")):
            return candidate

    # Method 2: search site-packages patterns
    for pattern in [
        "*/site-packages/vllm",
        "*/lib/python*/site-packages/vllm",
        "*/lib/python*/dist-packages/vllm",
    ]:
        matches = glob.glob(os.path.join(sys.prefix, pattern))
        if not matches:
            # Also search from sys.executable
            matches = glob.glob(os.path.join(os.path.dirname(os.path.dirname(sys.executable)), pattern))
            matches += glob.glob(os.path.join(os.path.dirname(sys.executable), "..", "lib", "python*", "site-packages", "vllm"))
        for m in matches:
            m = os.path.abspath(m)
            if os.path.isdir(m) and os.path.isfile(os.path.join(m, "__init__.py")):
                return m

    # Method 3: use pip show
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", "vllm"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Location:'):
                    loc = line.split(':', 1)[1].strip()
                    candidate = os.path.join(loc, "vllm")
                    if os.path.isdir(candidate):
                        return candidate
    except Exception:
        pass

    print("ERROR: vLLM directory not found.")
    print("Searched sys.path and site-packages patterns.")
    print(f"sys.path: {sys.path}")
    sys.exit(1)


def _get_indent(line):
    """Get the leading whitespace of a line."""
    return line[:len(line) - len(line.lstrip())]


def _find_torch_import_line(lines):
    """Find insertion point: after the last torch import."""
    insert_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('import torch') or stripped.startswith('from torch'):
            insert_idx = i + 1
    return insert_idx


def _find_first_code_line(lines):
    """Find first non-comment, non-docstring line."""
    in_docstring = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if in_docstring:
                in_docstring = False
                continue
            if stripped.count('"""') == 2 or stripped.count("'''") == 2:
                continue
            in_docstring = True
            continue
        if in_docstring:
            continue
        if stripped and not stripped.startswith('#'):
            return i
    return 0


def _repair_broken_uva_patch(lines):
    """Repair files broken by previous UVA patch versions.

    Old versions used regex replacement that didn't preserve indentation,
    leaving lines like:
        elif ...:
        # ROCm compat: UVA fallback (auto-patched)
        try:

    This function detects and removes the broken patch so it can be reapplied.
    """
    repaired = False
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect broken UVA patch: marker comment followed by try: without proper indentation
        # The old regex replaced "return torch.ops._C.get_cuda_view_from_cpu_tensor(arg)"
        # with a multi-line block that lost the original indentation.
        if UVA_MARKER in line and i + 1 < len(lines):
            # Check if the next line has wrong indentation (try: at wrong level)
            # The broken patch looks like:
            #   # ROCm compat: UVA fallback (auto-patched)
            #       try:
            #           return torch.ops._C.get_cuda_view_from_cpu_tensor(arg)
            #       except (AttributeError, RuntimeError):
            #           # vllm._C not compiled for ROCm; use copy-based fallback
            #           return arg.to(torch.accelerator.current_accelerator())
            #
            # We need to detect this block and remove it, then re-add the original
            # "return torch.ops._C.get_cuda_view_from_cpu_tensor(arg)" line.

            # Check if this is a broken inline patch (not the monkey-patch style)
            # Look ahead for the pattern: marker -> try: -> return ... get_cuda_view -> except -> return ... to(
            block_lines = [line]
            j = i + 1
            while j < len(lines) and j < i + 10:
                block_lines.append(lines[j])
                j += 1

            block_text = '\n'.join(block_lines)

            if 'try:' in block_text and 'get_cuda_view_from_cpu_tensor' in block_text and 'except' in block_text:
                # This is the broken inline patch - extract the arg name
                # and restore the original return statement
                # Find the return line to get indentation and arg
                return_line = None
                for bl in block_lines:
                    if 'get_cuda_view_from_cpu_tensor' in bl and 'return' in bl:
                        return_line = bl
                        break

                if return_line:
                    indent = _get_indent(return_line)
                    # Extract arg from: return torch.ops._C.get_cuda_view_from_cpu_tensor(arg)
                    import re as _re
                    m = _re.search(r'get_cuda_view_from_cpu_tensor\(([^)]+)\)', return_line)
                    if m:
                        arg = m.group(1).strip()
                        # Skip the entire broken block
                        # Count how many lines to skip (look for the fallback
                        # return line containing 'current_accelerator')
                        skip_count = 0
                        for k, bl in enumerate(block_lines):
                            skip_count = k + 1
                            if 'current_accelerator' in bl:
                                break

                        # Restore original line
                        new_lines.append(f"{indent}return torch.ops._C.get_cuda_view_from_cpu_tensor({arg})")
                        i += skip_count
                        repaired = True
                        continue

        new_lines.append(line)
        i += 1

    return new_lines, repaired


def _repair_broken_methodtype_patch(lines):
    """Repair files containing the buggy types.MethodType(..., None) line.

    Old patch versions inserted:
        import types
        _fake_op = types.MethodType(lambda self, arg: ..., None)

    types.MethodType requires a non-None instance in Python 3, causing:
        TypeError: instance must not be None

    This function removes the 'import types' and '_fake_op = ...' lines.
    The _fake_op variable was never used — the actual assignment
    (torch.ops._C.get_cuda_view_from_cpu_tensor = ...) still works.

    Returns (new_lines, was_repaired).
    """
    repaired = False
    new_lines = []
    for line in lines:
        stripped = line.strip()

        # Remove the buggy _fake_op line
        if '_fake_op = types.MethodType(' in stripped:
            repaired = True
            continue

        # Remove the orphaned 'import types' if it was only for _fake_op
        # Only remove if it's a standalone import (not 'import types' inside a try block
        # that might be used elsewhere). Check: it must be at the same indent level
        # as the monkey-patch block and not inside other code.
        if stripped == 'import types':
            # Check if 'types' is used elsewhere in the file (besides the _fake_op line we just removed)
            uses_types = False
            for other_line in lines:
                if other_line is line:
                    continue
                other_stripped = other_line.strip()
                if '_fake_op = types.MethodType(' in other_stripped:
                    continue  # This line will also be removed
                if 'types.' in other_stripped or 'import types' in other_stripped:
                    uses_types = True
                    break
            if not uses_types:
                repaired = True
                continue

        new_lines.append(line)

    return new_lines, repaired


def patch_memory_info(fpath):
    """Add get_memory_info compatibility shim to a file.

    Returns True if patched, False if already patched.
    """
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    if MEM_MARKER in content:
        return False  # Already patched

    if 'get_memory_info' not in content:
        return False  # Not relevant

    lines = content.split('\n')
    insert_idx = _find_torch_import_line(lines)
    if insert_idx is None:
        insert_idx = _find_first_code_line(lines)

    # Use the same indentation as the import line
    indent = _get_indent(lines[insert_idx]) if insert_idx < len(lines) else ""

    shim_lines = MEM_SHIM_CODE.strip('\n').split('\n')
    for j, shim_line in enumerate(shim_lines):
        lines.insert(insert_idx + j, shim_line)

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return True


def patch_uva_functions(fpath):
    """Wrap get_cuda_view_from_cpu_tensor calls with try/except fallback.

    Uses line-by-line processing to preserve indentation.
    Also repairs files broken by previous regex-based patches.

    Returns True if patched/repaired, False if nothing to do.
    """
    with open(fpath, 'r', encoding='utf-8') as f:
        lines = f.read().split('\n')

    # Step 1: Repair any broken previous patches
    lines, was_repaired = _repair_broken_uva_patch(lines)

    # Step 1.5: Repair broken MethodType patch (types.MethodType(..., None) causes TypeError)
    lines, mt_repaired = _repair_broken_methodtype_patch(lines)
    if mt_repaired:
        was_repaired = True

    content = '\n'.join(lines)

    # Step 2: Check if already has a valid patch
    has_valid_patch = False
    for line in lines:
        if UVA_MARKER in line:
            # Check if it's a valid (non-broken) patch
            has_valid_patch = True
            break

    # Also check for monkey-patch style marker
    if UVA_FUNC_MARKER in content:
        has_valid_patch = True

    if has_valid_patch and not was_repaired:
        return False  # Already properly patched

    # Step 3: Apply patch using monkey-patch approach (safer than inline replacement)
    # Instead of modifying each call site, we add a module-level monkey-patch
    # that makes torch.ops._C.get_cuda_view_from_cpu_tensor available.
    # This is much safer because it doesn't touch the call sites at all.

    if 'get_cuda_view_from_cpu_tensor' not in content:
        return False

    # Find insertion point
    insert_idx = _find_torch_import_line(lines)
    if insert_idx is None:
        insert_idx = _find_first_code_line(lines)

    # Add monkey-patch at module level
    monkey_patch = f'''{UVA_FUNC_MARKER}
# vllm._C is not compiled when vLLM is installed from PyPI CUDA wheel on ROCm.
# This monkey-patch adds the missing C++ operator as a pure-Python fallback.
# It runs at import time in ALL processes (main + spawned children).
try:
    torch.ops._C.get_cuda_view_from_cpu_tensor
except (AttributeError, RuntimeError):
    def _rocm_get_cuda_view_from_cpu_tensor(cpu_tensor):
        """Fallback for torch.ops._C.get_cuda_view_from_cpu_tensor on ROCm.

        Original C++ op creates a GPU view of a CPU tensor (zero-copy UVA).
        ROCm fallback: copy tensor to GPU (functionally equivalent, slightly slower).
        """
        return cpu_tensor.to(torch.accelerator.current_accelerator(), non_blocking=True)

    # Register the fallback operator (direct assignment, no MethodType)
    try:
        torch.ops._C.get_cuda_view_from_cpu_tensor = _rocm_get_cuda_view_from_cpu_tensor
    except (AttributeError, TypeError, RuntimeError):
        # torch.ops._C may be read-only; call-site try/except handles it
        pass'''

    mp_lines = monkey_patch.strip('\n').split('\n')
    for j, mp_line in enumerate(mp_lines):
        lines.insert(insert_idx + j, mp_line)

    # Step 4: Also wrap call sites with try/except as belt-and-suspenders
    # Do this AFTER the monkey-patch, line by line, preserving indentation
    new_lines = []
    for line in lines:
        stripped = line.strip()

        # Match: return torch.ops._C.get_cuda_view_from_cpu_tensor(arg)
        if 'get_cuda_view_from_cpu_tensor' in stripped and stripped.startswith('return') and UVA_MARKER not in line:
            indent = _get_indent(line)
            # Extract argument
            import re
            m = re.search(r'get_cuda_view_from_cpu_tensor\(([^)]+)\)', stripped)
            if m:
                arg = m.group(1).strip()
                # Replace with try/except preserving indentation
                new_lines.append(f"{indent}{UVA_MARKER}")
                new_lines.append(f"{indent}try:")
                new_lines.append(f"{indent}    return torch.ops._C.get_cuda_view_from_cpu_tensor({arg})")
                new_lines.append(f"{indent}except (AttributeError, RuntimeError):")
                new_lines.append(f"{indent}    # vllm._C not compiled for ROCm; copy-based fallback")
                new_lines.append(f"{indent}    return {arg}.to(torch.accelerator.current_accelerator(), non_blocking=True)")
                continue

        new_lines.append(line)

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))

    return True


# ============================================================
# Patch 3: Direct source patch for torch.ops._C references (vllm._C missing)
# ============================================================
# Strategy: Replace `self.op = torch.ops._C.<name>` with safe getattr,
# and patch `forward` methods to fall back to `forward_native` when op is None.
# This is a direct line-by-line source modification, not an append-at-end approach.

OP_PATCH_MARKER = "# ROCm compat: ops getattr fallback (auto-patched)"


def _patch_activation_init_lines(lines):
    """Replace `self.op = torch.ops._C.<name>` with safe getattr.

    Before:  self.op = torch.ops._C.silu_and_mul
    After:   self.op = getattr(torch.ops._C, 'silu_and_mul', None)  # ROCm compat
    """
    import re
    patched = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # Match: self.op = torch.ops._C.<name>
        m = re.match(r'^(\s*self\.op\s*=\s*)torch\.ops\._C\.(\w+)\s*$', line)
        if m and OP_PATCH_MARKER not in line:
            indent_op = m.group(1)
            op_name = m.group(2)
            new_lines.append(f"{indent_op}getattr(torch.ops._C, '{op_name}', None)  {OP_PATCH_MARKER}")
            patched = True
        else:
            new_lines.append(line)
    return new_lines, patched


def _patch_forward_to_native(lines):
    """Add `if self.op is None: return self.forward_native(...)` to forward methods.

    Finds `def forward(self, ...)` in classes that also have `self.op`,
    and inserts a None-check at the start of the method body.
    """
    import re
    patched = False
    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Match: def forward(self, x, out=None):  (or similar signatures)
        m = re.match(r'^(\s*)def forward\(self,\s*(.+)\):\s*$', line)
        if m and OP_PATCH_MARKER not in line:
            indent = m.group(1)
            args = m.group(2)
            # Check if the class uses self.op (look ahead a few lines)
            uses_self_op = False
            for j in range(i, min(i + 20, len(lines))):
                if 'self.op' in lines[j] and 'self.op is None' not in lines[j]:
                    uses_self_op = True
                    break
                if lines[j].strip() and not lines[j].startswith(indent + ' ') and 'def ' not in lines[j]:
                    break

            if uses_self_op:
                # Check if forward_native exists in the file
                has_native = any('def forward_native' in l for l in lines)
                if has_native:
                    # Insert the None-check before the first line of the method body
                    new_lines.append(line)
                    # Build the forward_native call based on args
                    # args could be "x, out=None" or "x" or "x, out"
                    arg_names = re.findall(r'(\w+)', args)
                    # Remove 'None' and default values
                    call_args = []
                    for a in arg_names:
                        if a not in ('None', 'self'):
                            call_args.append(a)
                    call_str = ', '.join(call_args)
                    new_lines.append(f"{indent}    if self.op is None:  {OP_PATCH_MARKER}")
                    new_lines.append(f"{indent}        return self.forward_native({call_str})")
                    patched = True
                    i += 1
                    continue

        new_lines.append(line)
        i += 1
    return new_lines, patched


def _remove_old_activation_patch(content):
    """Remove old broken activation patches (appended at end of file)."""
    old_markers = [
        "# ROCm compat: activation forward_native fallback (auto-patched)",
    ]
    cleaned = content
    removed = False
    for marker in old_markers:
        if marker in cleaned:
            # Remove everything from the marker to the end of file
            idx = cleaned.find(marker)
            if idx > 0:
                # Find the start of the block (including preceding newlines)
                start = idx
                while start > 0 and cleaned[start - 1] == '\n':
                    start -= 1
                cleaned = cleaned[:start] + '\n'
                removed = True
    return cleaned, removed


def patch_activation_layers(vllm_dir):
    """Directly patch vLLM source files that reference torch.ops._C operators.

    Replaces unsafe `torch.ops._C.X` attribute access with `getattr(torch.ops._C, 'X', None)`,
    and adds forward_native fallback in forward methods.
    """
    patched = 0
    repaired = 0

    # Target files that reference torch.ops._C operators
    target_files = [
        os.path.join(vllm_dir, "model_executor", "layers", "activation.py"),
        os.path.join(vllm_dir, "model_executor", "layers", "layernorm.py"),
        os.path.join(vllm_dir, "model_executor", "layers", "rotary_embedding.py"),
    ]

    # Also search for any other files that reference torch.ops._C
    for root, dirs, filenames in os.walk(vllm_dir):
        if '__pycache__' in root:
            continue
        for fname in filenames:
            if fname.endswith('.py'):
                fpath = os.path.join(root, fname)
                if fpath not in target_files:
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            content = f.read()
                        if 'torch.ops._C.' in content and 'self.op' in content:
                            target_files.append(fpath)
                    except (UnicodeDecodeError, PermissionError):
                        continue

    for fpath in target_files:
        if not os.path.isfile(fpath):
            continue

        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
        except (UnicodeDecodeError, PermissionError):
            continue

        # Step 1: Remove old broken patches
        content, was_repaired = _remove_old_activation_patch(content)

        # Step 2: Skip if already has the new patch marker AND no old markers
        has_new_marker = OP_PATCH_MARKER in content
        has_old_marker = "# ROCm compat: activation forward_native fallback" in content

        if has_new_marker and not was_repaired and not has_old_marker:
            continue

        # Step 3: Check if file actually needs patching
        if 'torch.ops._C.' not in content and 'self.op' not in content:
            continue

        lines = content.split('\n')

        # Step 4: Patch self.op = torch.ops._C.X lines
        lines, init_patched = _patch_activation_init_lines(lines)

        # Step 5: Patch forward methods to fall back to forward_native
        lines, fwd_patched = _patch_forward_to_native(lines)

        if init_patched or fwd_patched or was_repaired:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            rel = os.path.relpath(fpath, vllm_dir)
            if was_repaired and not init_patched and not fwd_patched:
                print(f"  [REPAIR] {rel} (removed old broken patch)")
                repaired += 1
            else:
                tags = []
                if init_patched:
                    tags.append("init")
                if fwd_patched:
                    tags.append("forward")
                if was_repaired:
                    tags.append("repair")
                print(f"  [OK] {rel} ({'+'.join(tags)})")
                patched += 1

    return patched, repaired


# ============================================================
# Patch 4: Disable vllm_c kernel backend when _C ops are missing
# ============================================================

VLLMC_MARKER = "# ROCm compat: _C ops availability check (auto-patched)"


def patch_vllm_c_kernel(vllm_dir):
    """Patch vllm/kernels/vllm_c.py to disable vllm_c backend when _C ops missing.

    vLLM 0.26.0 uses a new IR op dispatch system. The vllm_c backend in
    vllm/kernels/vllm_c.py calls torch.ops._C.rms_norm(output, x, weight, epsilon)
    directly. On ROCm without compiled vllm._C, this raises AttributeError.

    The dispatch system's dispatch() method only checks `supported` and
    `supports_args` — it does NOT catch runtime AttributeError. So the
    error propagates up and crashes vLLM.

    Fix: Add _C_OPS_AVAILABLE check and set GPGPU_DEVICE=False when _C is
    missing. This makes vllm_c unsupported, causing dispatch to use `native`.
    """
    vllm_c_path = os.path.join(vllm_dir, "kernels", "vllm_c.py")
    if not os.path.isfile(vllm_c_path):
        return False

    try:
        with open(vllm_c_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (UnicodeDecodeError, PermissionError):
        return False

    if VLLMC_MARKER in content:
        return False  # Already patched

    check_code = f'''{VLLMC_MARKER}
# On ROCm without compiled vllm._C, torch.ops._C.* operators don't exist.
# Setting GPGPU_DEVICE=False disables the vllm_c backend, causing the
# IR op dispatch to fall back to the `native` (pure PyTorch) implementation.
_C_OPS_AVAILABLE = True
try:
    torch.ops._C.rms_norm
except (AttributeError, RuntimeError):
    _C_OPS_AVAILABLE = False
'''

    # Try known patterns for the GPGPU_DEVICE line
    patterns = [
        "GPGPU_DEVICE = CUDA_ALIKE or current_platform.is_xpu()",
        "GPGPU_DEVICE = (CUDA_ALIKE or current_platform.is_xpu())",
    ]

    patched = False
    for old_line in patterns:
        if old_line in content:
            new_line = check_code + "GPGPU_DEVICE = (CUDA_ALIKE or current_platform.is_xpu()) and _C_OPS_AVAILABLE"
            content = content.replace(old_line, new_line)
            patched = True
            break

    if not patched:
        # Try regex to find any GPGPU_DEVICE assignment
        import re
        m = re.search(r'^(GPGPU_DEVICE\s*=\s*.+)$', content, re.MULTILINE)
        if m:
            old_line = m.group(1)
            rhs = old_line.split('=', 1)[1].strip()
            new_line = check_code + f"GPGPU_DEVICE = ({rhs}) and _C_OPS_AVAILABLE"
            content = content.replace(old_line, new_line)
            patched = True

    if patched:
        with open(vllm_c_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] kernels/vllm_c.py (disabled vllm_c when _C ops missing)")
    else:
        print(f"  [WARN] kernels/vllm_c.py: GPGPU_DEVICE line not found")

    return patched


def _patch_layername_in_file(fpath):
    """Replace LayerName type annotations with str in a single file.

    Returns True if patched, False if already patched or no match.
    """
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check if already patched
    if "LAYERNAME_SCHEMA_PATCH" in content:
        return False

    # Check if file uses LayerName type annotations
    # Use regex check to avoid wrongly matching longer identifiers like LayerNameType
    import re as _re
    has_layername = bool(_re.search(r'\bLayerName\b', content))
    if not has_layername:
        return False

    patched = False

    # Pattern 1: layer_name: LayerName (in function signatures)
    # Use regex replacement; \b ensures only the full LayerName word is matched,
    # not LayerNameType
    new_content = _re.sub(r'(layer_name\s*:\s*)LayerName\b', r'\1str', content)
    if new_content != content:
        content = new_content
        patched = True

    # Pattern 2: Optional[LayerName] if used anywhere
    if "Optional[LayerName]" in content:
        content = content.replace("Optional[LayerName]", "Optional[str]")
        patched = True

    if patched:
        # Add marker comment at the top to detect previous patches
        marker = "# LAYERNAME_SCHEMA_PATCH: LayerName -> str for infer_schema compat\n"
        lines = content.split('\n')
        if lines:
            lines.insert(0, marker)
            content = '\n'.join(lines)

        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)

    return patched


def patch_layername_schema(vllm_dir):
    """Patch 5: Fix LayerName infer_schema error.

    vLLM 0.26.0 uses a custom `LayerName` type (str subclass) as a parameter
    in custom op registration (direct_register_custom_op). torch 2.11.0's
    infer_schema doesn't recognize it, causing:

      ValueError: infer_schema(func): Parameter layer_name has unsupported type
      <class 'vllm.utils.torch_utils.LayerName'>

    This error occurs at module-level import time (e.g. moe_runner.py line 195),
    affecting ALL models because the import chain triggers fused_moe -> moe_runner.

    Fix: Replace `layer_name: LayerName` with `layer_name: str` in ALL vLLM
    source files. LayerName is a str subclass, so this is type-safe.

    Scans all .py files in vLLM directory, not just moe_runner.py, to handle
    any other files that might use LayerName annotations.
    """
    total_patched = 0

    # Primary target: moe_runner.py (known to trigger the error)
    moe_runner_path = os.path.join(
        vllm_dir, "model_executor", "layers", "fused_moe", "runner", "moe_runner.py"
    )
    if os.path.isfile(moe_runner_path):
        if _patch_layername_in_file(moe_runner_path):
            print(f"  [OK] fused_moe/runner/moe_runner.py (LayerName -> str)")
            total_patched += 1
        else:
            # Check if already patched
            with open(moe_runner_path, 'r', encoding='utf-8') as f:
                if "LAYERNAME_SCHEMA_PATCH" in f.read():
                    print(f"  [SKIP] moe_runner.py already patched")
                else:
                    print(f"  [WARN] No LayerName annotations found in moe_runner.py")
    else:
        print(f"  [SKIP] moe_runner.py not found")

    # Comprehensive scan: check ALL .py files for LayerName annotations
    # This catches any other files that might use LayerName in op registration
    for root, dirs, filenames in os.walk(vllm_dir):
        if '__pycache__' in root:
            continue
        for fname in filenames:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            # Skip moe_runner.py (already handled above)
            if os.path.abspath(fpath) == os.path.abspath(moe_runner_path):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
                if "layer_name: LayerName" in content or "Optional[LayerName]" in content:
                    if "LAYERNAME_SCHEMA_PATCH" not in content:
                        if _patch_layername_in_file(fpath):
                            rel = os.path.relpath(fpath, vllm_dir)
                            print(f"  [OK] {rel} (LayerName -> str)")
                            total_patched += 1
            except (UnicodeDecodeError, PermissionError):
                continue

    return total_patched


def patch_all():
    """Find and patch all vLLM files that need compatibility shims."""
    vllm_dir = find_vllm_dir()
    print(f"vLLM directory: {vllm_dir}")

    # Collect all .py files
    all_py_files = []
    for root, dirs, filenames in os.walk(vllm_dir):
        if '__pycache__' in root:
            continue
        for fname in filenames:
            if fname.endswith('.py'):
                all_py_files.append(os.path.join(root, fname))

    # ============================================================
    # Patch 1: get_memory_info
    # ============================================================
    print("\n=== Patch 1: get_memory_info (torch 2.9.1 < 2.10) ===")
    mem_patched = 0
    for fpath in all_py_files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            if 'get_memory_info' in content and MEM_MARKER not in content:
                if patch_memory_info(fpath):
                    print(f"  [OK] {os.path.relpath(fpath, vllm_dir)}")
                    mem_patched += 1
        except (UnicodeDecodeError, PermissionError):
            continue
    if mem_patched == 0:
        print("  (already patched or no files need it)")
    else:
        print(f"  Patched {mem_patched} file(s).")

    # ============================================================
    # Patch 2: get_cuda_view_from_cpu_tensor (vllm._C not compiled)
    # ============================================================
    print("\n=== Patch 2: get_cuda_view_from_cpu_tensor (vllm._C missing) ===")
    uva_patched = 0
    uva_repaired = 0
    for fpath in all_py_files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read()
            # Check if file needs patching or repair
            needs_patch = 'get_cuda_view_from_cpu_tensor' in content and UVA_FUNC_MARKER not in content
            # Check for broken patches (marker present but syntax might be broken)
            needs_repair = UVA_MARKER in content and UVA_FUNC_MARKER not in content
            # Check for broken MethodType patch (UVA_FUNC_MARKER present but has types.MethodType(..., None))
            needs_mt_repair = '_fake_op = types.MethodType(' in content

            if needs_patch or needs_repair or needs_mt_repair:
                result = patch_uva_functions(fpath)
                if result:
                    rel = os.path.relpath(fpath, vllm_dir)
                    if needs_mt_repair:
                        print(f"  [REPAIR-MethodType] {rel}")
                        uva_repaired += 1
                    elif needs_repair and not needs_patch:
                        print(f"  [REPAIR] {rel}")
                        uva_repaired += 1
                    else:
                        print(f"  [OK] {rel}")
                        uva_patched += 1
        except (UnicodeDecodeError, PermissionError):
            continue
    if uva_patched == 0 and uva_repaired == 0:
        print("  (already patched or no files need it)")
    else:
        if uva_patched:
            print(f"  Patched {uva_patched} file(s).")
        if uva_repaired:
            print(f"  Repaired {uva_repaired} file(s).")

    # ============================================================
    # Patch 3: Direct source patch for torch.ops._C references
    # ============================================================
    print("\n=== Patch 3: Direct source patch for torch.ops._C references ===")
    act_patched, act_repaired = patch_activation_layers(vllm_dir)
    if act_patched == 0 and act_repaired == 0:
        print("  (already patched or no files need it)")
    else:
        if act_patched:
            print(f"  Patched {act_patched} file(s).")
        if act_repaired:
            print(f"  Repaired {act_repaired} file(s) (removed old broken patches).")

    # ============================================================
    # Patch 4: Disable vllm_c kernel backend (CRITICAL for rms_norm)
    # ============================================================
    print("\n=== Patch 4: Disable vllm_c kernel backend (rms_norm fix) ===")
    vllm_c_patched = patch_vllm_c_kernel(vllm_dir)
    if not vllm_c_patched:
        print("  (already patched or file not found)")

    # ============================================================
    # Patch 5: Fix LayerName infer_schema error (vLLM 0.26.0 + torch 2.11.0)
    # ============================================================
    print("\n=== Patch 5: Fix LayerName infer_schema error (LayerName -> str) ===")
    moe_patched = patch_layername_schema(vllm_dir)
    if not moe_patched:
        print("  (already patched or no LayerName annotations found)")

    # ============================================================
    # Summary
    # ============================================================
    total = mem_patched + uva_patched + uva_repaired + act_patched + act_repaired
    if vllm_c_patched:
        total += 1
    total += moe_patched
    print(f"\n{'=' * 60}")
    print(f"Done. Total files processed: {total}")
    print(f"  - get_memory_info: {mem_patched} file(s)")
    print(f"  - get_cuda_view_from_cpu_tensor: {uva_patched} patched, {uva_repaired} repaired")
    print(f"  - torch.ops._C source patch: {act_patched} patched, {act_repaired} repaired")
    print(f"  - vllm_c kernel backend: {'patched' if vllm_c_patched else 'skipped'}")
    print(f"  - LayerName infer_schema: {moe_patched} file(s) patched")
    print(f"\nNote: Re-run this script after reinstalling/upgrading vLLM.")
    print(f"Note: vLLM 0.26.0+rocm723 prebuilt wheel natively compiles vllm._C, no _C operator patch needed.")
    print(f"Note: Patch 4 disables vllm_c backend as fallback if registration fails.")
    return total


if __name__ == '__main__':
    patch_all()
