#!/usr/bin/env python3
"""fix_layername.py - fix the LayerName infer_schema error in vLLM 0.26.0 + torch 2.11.0.

Error message:
  ValueError: infer_schema(func): Parameter layer_name has unsupported type
  <class 'vllm.utils.torch_utils.LayerName'>

Root cause:
  vLLM 0.26.0 uses LayerName (a subclass of str) as the parameter type for
  direct_register_custom_op in moe_runner.py. torch 2.11.0's infer_schema
  only does exact type matching and does not recognize str subclasses.

  The previously attempted fix (modifying __signature__) was ineffective because
  infer_schema reads __annotations__ directly, not through inspect.signature().

Fix plan (six-layer guarantee):
  Layer A: Replace the LayerName class definition with LayerName = str (the most fundamental fix)
  Layer B: Regex-scan all vLLM .py files and replace all LayerName type annotations
  Layer E: Fix broken replacements such as strType caused by patch_vllm_source.py
  Layer F: Patch the _resolve_layer_name function (fixes the side effect of Layer A)
  Layer C: Directly patch torch/_library/infer_schema.py to accept str subclasses
  Layer D: Enhance the torch_utils.py preprocessing, also modifying __annotations__

This script does not use a marker file; it forces a check and patch on every run.
Can be run standalone: python scripts/fix_layername.py
"""

import os
import sys
import re
import subprocess
import shutil


# ============================================================
# Utility functions
# ============================================================

def find_vllm_dir():
    """Locate the vLLM installation directory via pip show (without importing vllm)."""
    # Method 1: pip show
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'show', 'vllm'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Location:'):
                    location = line.split(':', 1)[1].strip()
                    candidate = os.path.join(location, 'vllm')
                    if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, '__init__.py')):
                        return candidate
    except Exception:
        pass

    # Method 2: importlib.util.find_spec
    try:
        import importlib.util
        spec = importlib.util.find_spec('vllm')
        if spec and spec.origin:
            return os.path.dirname(spec.origin)
    except Exception:
        pass

    # Method 3: search site-packages
    try:
        import site
        for sp in site.getsitepackages():
            candidate = os.path.join(sp, 'vllm')
            if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, '__init__.py')):
                return candidate
    except Exception:
        pass

    # Method 4: search sys.path
    for p in sys.path:
        if not p:
            continue
        candidate = os.path.join(p, 'vllm')
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, '__init__.py')):
            return candidate

    return None


def find_torch_dir():
    """Locate the torch installation directory."""
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'show', 'torch'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if line.startswith('Location:'):
                    location = line.split(':', 1)[1].strip()
                    candidate = os.path.join(location, 'torch')
                    if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, '__init__.py')):
                        return candidate
    except Exception:
        pass

    try:
        import importlib.util
        spec = importlib.util.find_spec('torch')
        if spec and spec.origin:
            return os.path.dirname(spec.origin)
    except Exception:
        pass

    return None


def clear_pycache(directory):
    """Recursively clear all __pycache__ directories under the given directory."""
    count = 0
    for root, dirs, files in os.walk(directory):
        if '__pycache__' in dirs:
            pycache_dir = os.path.join(root, '__pycache__')
            try:
                shutil.rmtree(pycache_dir)
                count += 1
            except Exception:
                pass
    return count


# ============================================================
# Layer A: Replace the LayerName class definition with LayerName = str
# ============================================================

def patch_layername_class(vllm_dir):
    """Modify torch_utils.py: replace class LayerName(str) with LayerName = str.

    This is the most fundamental fix: if LayerName is just str, then all type
    annotations using LayerName evaluate to str at function-definition time,
    and infer_schema never sees LayerName.

    Previously only the annotation string in moe_runner.py was replaced, but:
    1. The source format may differ (e.g. layer_name : LayerName, quoted annotations, etc.)
    2. Other files may also use LayerName
    3. .pyc cache may cause the old annotation to be used

    Replacing the class definition directly resolves all of these at once.
    """
    tu_path = os.path.join(vllm_dir, 'utils', 'torch_utils.py')

    if not os.path.isfile(tu_path):
        print(f"  [SKIP] torch_utils.py does not exist: {tu_path}")
        return False

    with open(tu_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'LAYERNAME_CLASS_REPLACED' in content:
        print(f"  [OK] LayerName class already replaced with str (skipping)")
        return True

    # Find the class LayerName(str) definition
    # Match multiple formats:
    #   class LayerName(str):
    #   class LayerName(str, ...):
    #   class LayerName(str):
    #       """docstring"""
    #       pass
    lines = content.split('\n')
    new_lines = []
    i = 0
    found = False
    class_indent = 0

    while i < len(lines):
        line = lines[i]

        # Detect the class LayerName(str) definition
        match = re.match(r'^(\s*)class\s+LayerName\s*\(\s*str', line)
        if match and not found:
            indent = len(match.group(1))
            class_indent = indent
            indent_str = ' ' * indent
            # Replace the class definition with LayerName = str
            new_lines.append(f"{indent_str}# LAYERNAME_CLASS_REPLACED: LayerName = str for infer_schema compatibility")
            new_lines.append(f"{indent_str}# (original: class LayerName(str): ...)")
            new_lines.append(f"{indent_str}LayerName = str")
            found = True
            i += 1
            # Skip the class body (lines more deeply indented than the class definition, and blank lines)
            while i < len(lines):
                next_line = lines[i]
                if next_line.strip() == '':
                    # A blank line may be part of the class body, but may also be a separator after the class
                    # Check whether the next line is still inside the class body
                    if i + 1 < len(lines):
                        next_non_empty = lines[i + 1]
                        next_indent = len(re.match(r'^(\s*)', next_non_empty).group(1))
                        if next_indent > class_indent and next_non_empty.strip():
                            i += 1
                            continue
                    break
                next_indent = len(re.match(r'^(\s*)', next_line).group(1))
                if next_indent <= class_indent and next_line.strip():
                    break
                i += 1
            continue

        new_lines.append(line)
        i += 1

    if found:
        content = '\n'.join(new_lines)
        with open(tu_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [OK] torch_utils.py: class LayerName(str) -> LayerName = str")
    else:
        # The class definition format may differ; try a regex replacement
        pattern = r'class\s+LayerName\s*\(\s*str\s*(?:,[^)]*)?\s*\)\s*:'
        if re.search(pattern, content):
            replacement = 'LayerName = str  # LAYERNAME_CLASS_REPLACED'
            content = re.sub(pattern, replacement, content, count=1)
            with open(tu_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  [OK] torch_utils.py: class LayerName(str) -> LayerName = str (regex)")
            found = True
        else:
            print(f"  [INFO] class LayerName(str) definition not found in torch_utils.py")
            # Check whether it is already LayerName = str
            if re.search(r'^LayerName\s*=\s*str', content, re.MULTILINE):
                print(f"  [OK] torch_utils.py already has LayerName = str")
                # Add the marker to prevent duplicate processing
                content = content.replace(
                    'LayerName = str',
                    'LayerName = str  # LAYERNAME_CLASS_REPLACED',
                    1
                )
                with open(tu_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                found = True
            else:
                # Force-add at the end of the file
                if 'LAYERNAME_CLASS_REPLACED' not in content:
                    content += '\n# LAYERNAME_CLASS_REPLACED: fallback override\nLayerName = str\n'
                    with open(tu_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"  [OK] torch_utils.py: appended LayerName = str at the end (fallback)")
                    found = True

    # Verification
    with open(tu_path, 'r', encoding='utf-8') as f:
        verify = f.read()
    if 'LAYERNAME_CLASS_REPLACED' in verify:
        print(f"  [OK] verification passed: torch_utils.py contains LayerName = str")
        return True
    else:
        print(f"  [FAIL] torch_utils.py verification failed!")
        return False


# ============================================================
# Layer B: Regex-scan all vLLM .py files and replace LayerName annotations
# ============================================================

def patch_all_layername_annotations(vllm_dir):
    """Scan all vLLM .py files and replace all LayerName type annotations.

    Use a regex to match all possible LayerName annotation formats:
    - layer_name: LayerName
    - layer_name : LayerName
    - layer_name: LayerName = None
    - Optional[LayerName]
    - Union[LayerName, ...]

    All replacements use \\b (word boundary) to ensure only the complete LayerName
    word is matched, so that longer identifiers like LayerNameType are not mis-matched.
    """
    count = 0
    patched_files = []

    for root, dirs, files in os.walk(vllm_dir):
        # skip __pycache__
        dirs[:] = [d for d in dirs if d != '__pycache__']

        for fname in files:
            if not fname.endswith('.py'):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue

            original = content

            # safe replacement: use \b to ensure only the complete LayerName word is matched
            # layer_name: LayerName -> layer_name: str
            content = re.sub(
                r'(\w+\s*:\s*)LayerName\b',
                r'\1str',
                content
            )
            # Optional[LayerName] -> Optional[str]
            content = re.sub(r'Optional\[LayerName\]', 'Optional[str]', content)
            # Union[LayerName, ...] -> Union[str, ...]
            content = re.sub(r'Union\[LayerName\b', 'Union[str', content)
            # list[LayerName] -> list[str]
            content = re.sub(r'(list|List|Sequence|Tuple)\[LayerName\b', r'\1[str', content)

            if content != original:
                try:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    rel_path = os.path.relpath(fpath, vllm_dir)
                    patched_files.append(rel_path)
                    count += 1
                except Exception:
                    pass

    if count > 0:
        print(f"  [OK] patched {count} files:")
        for fp in patched_files[:10]:
            print(f"    - {fp}")
        if len(patched_files) > 10:
            print(f"    ... and {len(patched_files) - 10} more")
    else:
        print(f"  [OK] all files need no patching (no LayerName annotations found)")

    return True


# ============================================================
# Layer E: fix broken replacements such as strType
# ============================================================

def patch_broken_strtype(vllm_dir):
    """Fix the strType errors caused by patch_vllm_source.py.

    patch_vllm_source.py's Patch 5 uses pure string replacement:
      content.replace("layer_name: LayerName", "layer_name: str")
    This mistakenly matches "layer_name: LayerNameType", replacing it with "layer_name: strType".

    This function scans all vLLM .py files and restores strType to str.
    It also checks for other possibly broken replacements (like str followed by an identifier starting with an uppercase letter).
    """
    count = 0
    patched_files = []

    # broken patterns that need fixing
    # strType -> str (LayerNameType partially replaced)
    # str_ -> str (other possible partial replacements)
    broken_patterns = [
        # strType: partial replacement from LayerNameType
        (r'\bstrType\b', 'str'),
        # strOp: partial replacement from LayerNameOp
        (r'\bstrOp\b', 'str'),
        # strAlias: partial replacement from LayerNameAlias
        (r'\bstrAlias\b', 'str'),
    ]

    for root, dirs, files in os.walk(vllm_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']

        for fname in files:
            if not fname.endswith('.py'):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue

            original = content
            changes = []

            for pattern, replacement in broken_patterns:
                new_content = re.sub(pattern, replacement, content)
                if new_content != content:
                    changes.append(f'{pattern} -> {replacement}')
                    content = new_content

            # generic check: layer_name: str followed by an uppercase letter (possibly a partial-replacement residue)
            # e.g. layer_name: strType -> layer_name: str
            # but do not match valid str type annotations like layer_name: str = ""
            # only match str followed immediately by an uppercase letter that is not = or , or ) or space
            generic_pattern = r'(layer_name\s*:\s*)str([A-Z]\w*)'
            match = re.search(generic_pattern, content)
            if match:
                content = re.sub(generic_pattern, r'\1str', content)
                changes.append(f'layer_name: str{match.group(2)} -> str')

            if content != original:
                try:
                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    rel_path = os.path.relpath(fpath, vllm_dir)
                    patched_files.append(rel_path)
                    count += 1
                except Exception:
                    pass

    if count > 0:
        print(f"  [OK] fixed strType and other errors in {count} files:")
        for fp in patched_files[:10]:
            print(f"    - {fp}")
        if len(patched_files) > 10:
            print(f"    ... and {len(patched_files) - 10} more")
    else:
        print(f"  [OK] no strType or other errors found")

    return True


# ============================================================
# Layer F: patch the _resolve_layer_name function
# ============================================================

def patch_resolve_layer_name(vllm_dir):
    """Modify torch_utils.py: patch the _resolve_layer_name function.

    Layer A replaces class LayerName(str) with LayerName = str, causing:
    - isinstance(layer_name, LayerName) returns True for any string
    - code tries to access layer_name.value, but str has no .value attribute

    Original code:
      return layer_name.value if isinstance(layer_name, LayerName) else layer_name

    Patched code:
      return getattr(layer_name, 'value', layer_name)

    This way:
    - if layer_name has a .value attribute -> return .value (compatible with original behavior)
    - if layer_name is a plain str -> return layer_name itself
    """
    tu_path = os.path.join(vllm_dir, 'utils', 'torch_utils.py')

    if not os.path.isfile(tu_path):
        print(f"  [SKIP] torch_utils.py does not exist: {tu_path}")
        return False

    with open(tu_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'RESOLVE_LAYERNAME_FIX' in content:
        print(f"  [OK] _resolve_layer_name already patched (skipping)")
        return True

    # find the original code pattern
    # original: return layer_name.value if isinstance(layer_name, LayerName) else layer_name
    original_pattern = r'(return\s+layer_name\.value\s+if\s+isinstance\s*\(\s*layer_name\s*,\s*LayerName\s*\)\s+else\s+layer_name)'

    match = re.search(original_pattern, content)
    if match:
        original_code = match.group(1)
        # replace with the safe version using getattr
        patched_code = 'return getattr(layer_name, "value", layer_name)  # RESOLVE_LAYERNAME_FIX'
        content = content.replace(original_code, patched_code, 1)

        with open(tu_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"  [OK] _resolve_layer_name patched: .value -> getattr(.value, default)")
    else:
        # the code format may differ; try a looser match
        loose_pattern = r'(layer_name\.value\s+if\s+isinstance\s*\(\s*layer_name\s*,\s*LayerName\s*\))'
        loose_match = re.search(loose_pattern, content)
        if loose_match:
            original = loose_match.group(1)
            patched = 'getattr(layer_name, "value", layer_name)  # RESOLVE_LAYERNAME_FIX'
            content = content.replace(original, patched, 1)
            with open(tu_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  [OK] _resolve_layer_name patched (loose match)")
        else:
            # search for lines containing .value and LayerName
            print(f"  [INFO] searching for lines containing 'layer_name.value'...")
            for i, line in enumerate(content.split('\n'), 1):
                if 'layer_name.value' in line or ('.value' in line and 'LayerName' in line):
                    print(f"    line {i}: {line.strip()}")
            print(f"  [WARN] original _resolve_layer_name code pattern not found")
            # even if not found, try to search for any .value reference
            # may already be modified by another patch
            return True  # non-fatal, continue execution

    # verification
    with open(tu_path, 'r', encoding='utf-8') as f:
        verify = f.read()
    if 'RESOLVE_LAYERNAME_FIX' in verify:
        print(f"  [OK] verification passed: _resolve_layer_name contains the getattr fix")
        return True
    else:
        print(f"  [WARN] _resolve_layer_name verification: fix marker not found")
        return True  # non-fatal


# ============================================================
# Layer C: directly patch torch/_library/infer_schema.py
# ============================================================

def patch_infer_schema(torch_dir):
    """Directly modify torch/_library/infer_schema.py: accept str subclasses.

    This is the most thorough fix: modify the torch source itself, adding
    preprocessing code at the start of the infer_schema function that replaces
    str subclasses in the function __annotations__ with str.

    Modifying __signature__ previously had no effect, because infer_schema may
    read __annotations__ directly rather than obtaining annotations via inspect.signature().

    This patch inserts code at the start of the infer_schema function to directly modify func.__annotations__.
    """
    is_path = os.path.join(torch_dir, '_library', 'infer_schema.py')

    if not os.path.isfile(is_path):
        print(f"  [SKIP] infer_schema.py does not exist: {is_path}")
        # try other paths
        alt_paths = [
            os.path.join(torch_dir, '_library', 'infer_schema.py'),
            os.path.join(os.path.dirname(torch_dir), 'torch', '_library', 'infer_schema.py'),
        ]
        for alt in alt_paths:
            if os.path.isfile(alt):
                is_path = alt
                break
        else:
            print(f"  [WARN] unable to locate infer_schema.py")
            return False

    with open(is_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'INFER_SCHEMA_STR_SUBCLASS_FIX' in content:
        print(f"  [OK] infer_schema.py already patched (skipping)")
        return True

    # find the infer_schema function definition and capture the first parameter name
    # typical signature: def infer_schema(prototype_function, mutates_args=()):
    # or: def infer_schema(func, mutates_args=()):
    func_pattern = r'def\s+infer_schema\s*\(\s*(\w+)\s*(?:,[^)]*)?\)\s*(?:->\s*\S+\s*)?:'
    match = re.search(func_pattern, content)

    if not match:
        # try a looser match
        func_pattern = r'(def\s+infer_schema\s*\([^)]*\)\s*(?:->\s*\S+\s*)?:)'
        match = re.search(func_pattern, content)
        if match:
            # extract the parameter name from the match
            param_match = re.search(r'\(\s*(\w+)', match.group(1))
            param_name = param_match.group(1) if param_match else 'prototype_function'
        else:
            print(f"  [WARN] infer_schema function definition not found")
            for i, line in enumerate(content.split('\n'), 1):
                if 'def infer_schema' in line:
                    print(f"    line {i}: {line.strip()}")
            return False
    else:
        param_name = match.group(1)

    print(f"  [INFO] first parameter name of infer_schema: {param_name}")

    # build the fix code, using the captured parameter name
    fix_code = f'''
    # INFER_SCHEMA_STR_SUBCLASS_FIX: replace str subclass annotations with str
    # vLLM 0.26.0 uses LayerName(str) as the type annotation, and infer_schema does not recognize str subclasses.
    # This patch modifies func.__annotations__ at the start of infer_schema, replacing str subclasses with str.
    try:
        _anns = getattr({param_name}, '__annotations__', None)
        if _anns:
            _new_anns = {{}}
            _changed = False
            for _k, _v in _anns.items():
                if isinstance(_v, type) and issubclass(_v, str) and _v is not str:
                    _new_anns[_k] = str
                    _changed = True
                else:
                    _new_anns[_k] = _v
            if _changed:
                {param_name}.__annotations__ = _new_anns
    except Exception:
        pass
'''

    # find the end of the function definition and insert the fix code
    func_def_pattern = r'(def\s+infer_schema\s*\([^)]*\)\s*(?:->\s*\S+\s*)?:)'
    func_match = re.search(func_def_pattern, content)
    if not func_match:
        print(f"  [WARN] unable to locate the end of the infer_schema function definition")
        return False

    insert_pos = func_match.end()
    new_content = content[:insert_pos] + fix_code + content[insert_pos:]

    with open(is_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"  [OK] infer_schema.py patched: str subclass preprocessing added at the start of the function")

    # verification
    with open(is_path, 'r', encoding='utf-8') as f:
        verify = f.read()
    if 'INFER_SCHEMA_STR_SUBCLASS_FIX' in verify:
        print(f"  [OK] verification passed: infer_schema.py contains str subclass preprocessing")
        return True
    else:
        print(f"  [FAIL] infer_schema.py verification failed!")
        return False


# ============================================================
# Layer D: enhance torch_utils.py preprocessing (modify __annotations__)
# ============================================================

def patch_torch_utils_enhanced(vllm_dir):
    """Modify torch_utils.py: add enhanced preprocessing to direct_register_custom_op.

    The previous preprocessing only modified __signature__, but infer_schema may read
    __annotations__ directly. This patch modifies both __signature__ and __annotations__.
    """
    tu_path = os.path.join(vllm_dir, 'utils', 'torch_utils.py')

    if not os.path.isfile(tu_path):
        print(f"  [SKIP] torch_utils.py does not exist: {tu_path}")
        return False

    with open(tu_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # if the enhanced marker already exists, skip
    if 'LAYERNAME_ANNS_FIX' in content:
        print(f"  [OK] torch_utils.py already has enhanced preprocessing (skipping)")
        return True

    # find the infer_schema call
    # the old patch may have added LAYERNAME_STR_SUBCLASS_FIX, which needs to be replaced with the enhanced version
    target = 'schema_str = infer_schema(op_func, mutates_args=mutates_args)'

    # first check whether the old patch exists
    old_fix_pattern = r'# LAYERNAME_STR_SUBCLASS_FIX.*?schema_str = infer_schema\(op_func, mutates_args=mutates_args\)'
    old_fix_match = re.search(old_fix_pattern, content, re.DOTALL)

    if old_fix_match:
        # replace the old patch with the enhanced version
        old_fix = old_fix_match.group(0)

        new_fix = '''# LAYERNAME_ANNS_FIX: modify both __signature__ and __annotations__
    try:
        import inspect as _inspect
        _sig = _inspect.signature(op_func)
        _params = dict(_sig.parameters)
        _changed = False
        for _pname, _param in _params.items():
            _ann = _param.annotation
            if isinstance(_ann, type) and issubclass(_ann, str) and _ann is not str:
                _params[_pname] = _param.replace(annotation=str)
                _changed = True
        if _changed:
            op_func.__signature__ = _sig.replace(parameters=list(_params.values()))
            # key: also modify __annotations__, because infer_schema may read it directly
            _anns = dict(getattr(op_func, '__annotations__', {}))
            for _pname, _param in _params.items():
                if _pname in _anns:
                    _anns[_pname] = _param.annotation
            try:
                op_func.__annotations__ = _anns
            except (AttributeError, TypeError):
                pass
    except Exception:
        pass
    schema_str = infer_schema(op_func, mutates_args=mutates_args)'''

        content = content.replace(old_fix, new_fix, 1)
    elif target in content:
        # no old patch, insert the new patch directly
        new_fix = '''# LAYERNAME_ANNS_FIX: modify both __signature__ and __annotations__
    try:
        import inspect as _inspect
        _sig = _inspect.signature(op_func)
        _params = dict(_sig.parameters)
        _changed = False
        for _pname, _param in _params.items():
            _ann = _param.annotation
            if isinstance(_ann, type) and issubclass(_ann, str) and _ann is not str:
                _params[_pname] = _param.replace(annotation=str)
                _changed = True
        if _changed:
            op_func.__signature__ = _sig.replace(parameters=list(_params.values()))
            # key: also modify __annotations__, because infer_schema may read it directly
            _anns = dict(getattr(op_func, '__annotations__', {}))
            for _pname, _param in _params.items():
                if _pname in _anns:
                    _anns[_pname] = _param.annotation
            try:
                op_func.__annotations__ = _anns
            except (AttributeError, TypeError):
                pass
    except Exception:
        pass
    ''' + target

        content = content.replace(target, new_fix, 1)
    else:
        # try a loose match
        match = re.search(r'(schema_str\s*=\s*infer_schema\s*\(\s*op_func\s*,\s*mutates_args\s*=\s*mutates_args\s*\))', content)
        if match:
            target = match.group(1)
            new_fix = '''# LAYERNAME_ANNS_FIX: modify both __signature__ and __annotations__
    try:
        import inspect as _inspect
        _sig = _inspect.signature(op_func)
        _params = dict(_sig.parameters)
        _changed = False
        for _pname, _param in _params.items():
            _ann = _param.annotation
            if isinstance(_ann, type) and issubclass(_ann, str) and _ann is not str:
                _params[_pname] = _param.replace(annotation=str)
                _changed = True
        if _changed:
            op_func.__signature__ = _sig.replace(parameters=list(_params.values()))
            _anns = dict(getattr(op_func, '__annotations__', {}))
            for _pname, _param in _params.items():
                if _pname in _anns:
                    _anns[_pname] = _param.annotation
            try:
                op_func.__annotations__ = _anns
            except (AttributeError, TypeError):
                pass
    except Exception:
        pass
    ''' + target

            content = content.replace(target, new_fix, 1)
        else:
            print(f"  [WARN] infer_schema call not found in torch_utils.py")
            print(f"  [INFO] searching for lines containing 'infer_schema'...")
            for i, line in enumerate(content.split('\n'), 1):
                if 'infer_schema' in line:
                    print(f"    line {i}: {line.strip()}")
            # even if the call site is not found, Layer A (LayerName = str) already solves the root problem
            print(f"  [INFO] Layer A (LayerName = str) already solves the root problem; this layer is an enhanced guarantee")
            return True

    with open(tu_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(f"  [OK] torch_utils.py: enhanced preprocessing (modifies both __signature__ + __annotations__)")

    # verification
    with open(tu_path, 'r', encoding='utf-8') as f:
        verify = f.read()
    if 'LAYERNAME_ANNS_FIX' in verify:
        print(f"  [OK] verification passed: torch_utils.py contains enhanced preprocessing")
        return True
    else:
        print(f"  [WARN] torch_utils.py verification: enhanced marker not found (may be covered by Layer A)")
        return True  # Layer A already solves the root problem


# ============================================================
# verification function
# ============================================================

def verify_patches(vllm_dir, torch_dir):
    """Verify that all patches were applied correctly."""
    print("\n--- Verifying patches ---")
    all_ok = True

    # verify Layer A: LayerName = str
    tu_path = os.path.join(vllm_dir, 'utils', 'torch_utils.py')
    if os.path.isfile(tu_path):
        with open(tu_path, 'r', encoding='utf-8') as f:
            content = f.read()
        if 'LAYERNAME_CLASS_REPLACED' in content or 'LayerName = str' in content:
            print(f"  [OK] Layer A: torch_utils.py LayerName = str")
        else:
            print(f"  [FAIL] Layer A: LayerName = str not found in torch_utils.py")
            all_ok = False

        # check whether a class LayerName(str) definition still exists
        if re.search(r'^\s*class\s+LayerName\s*\(\s*str', content, re.MULTILINE):
            print(f"  [FAIL] Layer A: torch_utils.py still has a class LayerName(str) definition!")
            all_ok = False

        # verify Layer F: _resolve_layer_name patched
        if 'RESOLVE_LAYERNAME_FIX' in content:
            print(f"  [OK] Layer F: _resolve_layer_name patched (getattr)")
        else:
            # check whether the layer_name.value if isinstance pattern still exists
            if re.search(r'layer_name\.value\s+if\s+isinstance\s*\(\s*layer_name\s*,\s*LayerName', content):
                print(f"  [FAIL] Layer F: _resolve_layer_name not patched (still has .value if isinstance pattern)")
                all_ok = False
            else:
                print(f"  [OK] Layer F: _resolve_layer_name has no dangerous pattern")
    else:
        print(f"  [SKIP] Layer A: torch_utils.py does not exist")
        all_ok = False

    # verify Layer C: infer_schema.py patch
    if torch_dir:
        is_path = os.path.join(torch_dir, '_library', 'infer_schema.py')
        if os.path.isfile(is_path):
            with open(is_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if 'INFER_SCHEMA_STR_SUBCLASS_FIX' in content:
                print(f"  [OK] Layer C: infer_schema.py str subclass preprocessing")
            else:
                print(f"  [FAIL] Layer C: str subclass preprocessing not found in infer_schema.py")
                all_ok = False
        else:
            print(f"  [SKIP] Layer C: infer_schema.py does not exist")
    else:
        print(f"  [SKIP] Layer C: torch directory not found")

    return all_ok


# ============================================================
# main function
# ============================================================

def main():
    print("=" * 60)
    print("fix_layername.py — fix the LayerName infer_schema error (six-layer fix)")
    print("=" * 60)

    # 1. find the vLLM directory
    vllm_dir = find_vllm_dir()
    if not vllm_dir:
        print("\n[ERROR] unable to find the vLLM installation directory")
        print("please confirm vLLM is installed: pip show vllm")
        sys.exit(1)

    print(f"\nvLLM directory: {vllm_dir}")

    # 2. find the torch directory
    torch_dir = find_torch_dir()
    if torch_dir:
        print(f"torch directory: {torch_dir}")
    else:
        print(f"torch directory: not found (Layer C will be skipped)")

    # 3. Layer A: replace the LayerName class definition (the most fundamental fix)
    print("\n--- Layer A: replace the LayerName class definition with LayerName = str ---")
    ok_a = patch_layername_class(vllm_dir)

    # 4. Layer B: regex-scan all vLLM .py files
    print("\n--- Layer B: regex-scan all vLLM .py files ---")
    ok_b = patch_all_layername_annotations(vllm_dir)

    # 4.5. Layer E: fix broken replacements such as strType
    print("\n--- Layer E: fix broken replacements such as strType ---")
    ok_e = patch_broken_strtype(vllm_dir)

    # 4.6. Layer F: patch the _resolve_layer_name function
    # After Layer A replaces class LayerName(str) with LayerName = str,
    # isinstance(layer_name, LayerName) returns True for all strings,
    # causing layer_name.value access to fail. Layer F fixes this side effect.
    print("\n--- Layer F: patch the _resolve_layer_name function ---")
    ok_f = patch_resolve_layer_name(vllm_dir)

    # 5. Layer C: directly patch torch/_library/infer_schema.py
    print("\n--- Layer C: directly patch torch infer_schema.py ---")
    if torch_dir:
        ok_c = patch_infer_schema(torch_dir)
    else:
        print(f"  [SKIP] torch directory not found, skipping Layer C")
        ok_c = False

    # 6. Layer D: enhance torch_utils.py preprocessing
    print("\n--- Layer D: enhance torch_utils.py preprocessing ---")
    ok_d = patch_torch_utils_enhanced(vllm_dir)

    # 7. clear __pycache__ (vLLM + torch)
    print("\n--- Clearing __pycache__ ---")
    count1 = clear_pycache(vllm_dir)
    print(f"  [OK] cleared {count1} vLLM __pycache__ directories")
    if torch_dir:
        # only clear the pycache of the _library directory
        lib_dir = os.path.join(torch_dir, '_library')
        if os.path.isdir(lib_dir):
            count2 = clear_pycache(lib_dir)
            print(f"  [OK] cleared {count2} torch/_library __pycache__ directories")

    # 8. verify
    all_ok = verify_patches(vllm_dir, torch_dir)

    # 9. summary
    print("\n" + "=" * 60)
    if all_ok:
        print("[DONE] all six-layer fixes succeeded")
        print("  Layer A: LayerName class -> str alias (root fix)")
        print("  Layer B: regex-scan all .py files")
        print("  Layer E: fix broken replacements such as strType")
        print("  Layer F: patch the _resolve_layer_name function (fixes the Layer A side effect)")
        print("  Layer C: torch infer_schema.py direct patch")
        print("  Layer D: torch_utils.py enhanced preprocessing")
        print("\nnow you can start vLLM: bash scripts/start_vllm.sh")
    elif ok_a:
        print("[PARTIAL] Layer A succeeded (root fix is effective)")
        print("  Layer A is the most critical fix; the other layers are enhanced guarantees")
        print("\nnow you can start vLLM: bash scripts/start_vllm.sh")
    else:
        print("[FAILED] Layer A failed, please check manually")
        print("  manual fix: edit vllm/utils/torch_utils.py")
        print("  replace class LayerName(str): with LayerName = str")
        sys.exit(1)


if __name__ == '__main__':
    main()
