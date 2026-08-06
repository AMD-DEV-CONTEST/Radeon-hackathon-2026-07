"""TunableOps 注入垫片 — AMD vLLM Optimize Skill Phase 4 Step 0c。

通过 PYTHONPATH 注入，在 vLLM EngineCore 子进程启动时自动加载调优结果。
不修改任何系统文件或 pip 包。

启用方式：
    export PYTHONPATH="/persistent/insurance-rag-agent/docs/benchmarks/vllm_tune/pypath:$PYTHONPATH"
    export PYTORCH_TUNABLEOP_ENABLED=1
    export PYTORCH_TUNABLEOP_TUNING=0
    python -m vllm.entrypoints.openai.api_server ...
"""
import os
import sys

def _inject_tunableops():
    """在 torch 导入后注入 TunableOps 调优结果。"""
    try:
        import torch
        csv_path = "/persistent/insurance-rag-agent/docs/benchmarks/vllm_tune/tuned_gemm.csv"
        if os.path.exists(csv_path):
            torch.cuda.tunable.enable(val=True)
            torch.cuda.tunable.tuning_enable(val=False)
            torch.cuda.tunable.read_file(csv_path)
            print(f"tunableops_inject: Loaded {csv_path}", file=sys.stderr)
        else:
            print(f"tunableops_inject: WARNING — {csv_path} not found", file=sys.stderr)
    except ImportError:
        pass
    except Exception as e:
        print(f"tunableops_inject: ERROR — {e}", file=sys.stderr)

# 在 sitecustomize 中延迟执行（等 torch 被导入后）
# 使用 meta_path hook 确保在 torch 首次导入后触发
_original_import = __builtins__.__import__

def _patched_import(name, *args, **kwargs):
    result = _original_import(name, *args, **kwargs)
    if name == "torch" and not getattr(sys, "_tunableops_injected", False):
        sys._tunableops_injected = True
        _inject_tunableops()
    return result

__builtins__.__import__ = _patched_import
