# radeon-fix report

- Repository: `/root/radeon-fix-demo5/demo_project`
- Issue: pycalc has three bugs: 1) mode breaks ties by returning the first encountered value instead of the smaller value; 2) normalize scales by the maximum instead of the min-max range, crashes when the maximum is 0, and does not handle all-equal inputs; 3) report.summary_text only prints the first five normalized values instead of all of them. Fix all three so every test in tests/ passes.
- Model: `Qwen3-14B-BF16`
- Endpoint: `http://127.0.0.1:8000/v1` (local inference)
- Completed: True
- Patch: non-empty

## Issue

pycalc has three bugs: 1) mode breaks ties by returning the first encountered value instead of the smaller value; 2) normalize scales by the maximum instead of the min-max range, crashes when the maximum is 0, and does not handle all-equal inputs; 3) report.summary_text only prints the first five normalized values instead of all of them. Fix all three so every test in tests/ passes.

## Trajectory summary

- Model turns: 11
- Tool calls: 13
- Edit attempts: 4
- Replace attempts: 3
- Replace successes: 2
- Patch apply results: [False, False, False, True, False, False, True]
- Verifier verdict: accept (mode V1; deterministic syntax/structure gates, does not run tests)
- Total tokens: 32412
- Wall time: 254.3 s
- Context provider: aider-repomap-focused (available: True)
- Context refresh: yes

## Repository context

- Initial Repo Map available: True
- Initial Repo Map chars: 114
- Focused refresh available: True

## AMD GPU inference

- GPU: AMD Radeon
- vLLM: 0.16.1.dev0+g89a77b108.d20260317.rocm721
- VRAM: 51.52
- GPU utilization: 96
- GPU arch: None
- Model: Qwen3-14B-BF16
- KV cache: auto
- TTFT p50: 115.6
- Decode: 12.41

## Final check

- Command: `python -m pytest -q`
- Exit code: 0
- Passed: True

```text
.......                                                                  [100%]
7 passed in 0.01s
```

## Patch

```diff
diff --git a/pycalc/analysis.py b/pycalc/analysis.py
index f3992fb..af05bca 100644
--- a/pycalc/analysis.py
+++ b/pycalc/analysis.py
@@ -9,7 +9,7 @@ def mode(values):
     best = None
     best_count = -1
     for value, count in counts.items():
-        if count > best_count:
+        if count > best_count or (count == best_count and value < best):
             best = value
             best_count = count
     return best
@@ -21,4 +21,6 @@ def normalize(values):
         return []
     low = min(values)
     high = max(values)
-    return [round(value / high, 4) for value in values]
+    if low == high:
+        return [0.0 for _ in values]
+    return [round((value - low) / (high - low), 4) for value in values]
diff --git a/pycalc/report.py b/pycalc/report.py
index 41f5059..9ff2d3b 100644
--- a/pycalc/report.py
+++ b/pycalc/report.py
@@ -13,5 +13,5 @@ def summary_text(values, title="Summary"):
     lines.append(f"- values: {len(values)}")
     lines.append(f"- mode: {mode(values)}")
     normalized = [str(value) for value in normalize(values)]
-    lines.append("- normalized: " + ", ".join(normalized[:5]))
+    lines.append("- normalized: " + ", ".join(normalized))
     return "\n".join(lines)
```

## Apply

The patch was produced in an isolated temporary copy. To apply it to the original repository:

```bash
cd /root/radeon-fix-demo5/demo_project && git apply /root/radeon-fix-demo5/out/patch.diff
```
