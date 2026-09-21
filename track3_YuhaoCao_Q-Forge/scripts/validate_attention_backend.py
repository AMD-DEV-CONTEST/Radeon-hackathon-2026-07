"""Validate the active FlashAttention backend on ROCm.

Run once with the installed CK wheel and once with the Triton source tree on
PYTHONPATH.  The script checks dense output parity, finite forward/backward
values, and the packed varlen forward/backward path.
"""

import argparse
import json
import os

import torch
import torch.nn.functional as F


def backend_info():
    import flash_attn
    from flash_attn import flash_attn_interface as interface

    triton = bool(getattr(interface, "USE_TRITON_ROCM", False))
    return {
        "backend": "triton" if triton else "ck",
        "version": flash_attn.__version__,
        "module": interface.flash_attn_gpu.__name__,
        "path": flash_attn.__file__,
    }


def finite(*tensors):
    return all(torch.isfinite(t).all().item() for t in tensors)


def dense_check(dtype, causal):
    from flash_attn import flash_attn_func

    torch.manual_seed(7)
    q, k, v = [
        torch.randn(2, 256, 8, 64, device="cuda", dtype=dtype, requires_grad=True)
        for _ in range(3)
    ]
    out = flash_attn_func(q, k, v, causal=causal)
    ref = F.scaled_dot_product_attention(
        q.transpose(1, 2), k.transpose(1, 2), v.transpose(1, 2), is_causal=causal
    ).transpose(1, 2)
    max_err = (out.float() - ref.float()).abs().max().item()
    out.float().square().mean().backward()
    ok = finite(out, q.grad, k.grad, v.grad)
    return {"max_abs_error": max_err, "finite_output_and_grads": ok}


def varlen_check(dtype):
    from flash_attn import flash_attn_varlen_func

    torch.manual_seed(11)
    lengths = [73, 128, 191]
    total, heads, dim = sum(lengths), 8, 64
    q, k, v = [
        torch.randn(total, heads, dim, device="cuda", dtype=dtype, requires_grad=True)
        for _ in range(3)
    ]
    cu = torch.tensor([0, *torch.tensor(lengths).cumsum(0).tolist()], device="cuda", dtype=torch.int32)
    out = flash_attn_varlen_func(q, k, v, cu, cu, max(lengths), max(lengths), causal=True)
    refs = []
    for start, end in zip(cu[:-1].cpu().tolist(), cu[1:].cpu().tolist()):
        refs.append(
            F.scaled_dot_product_attention(
                q[start:end].transpose(0, 1).unsqueeze(0),
                k[start:end].transpose(0, 1).unsqueeze(0),
                v[start:end].transpose(0, 1).unsqueeze(0),
                is_causal=True,
            ).squeeze(0).transpose(0, 1)
        )
    ref = torch.cat(refs)
    max_err = (out.float() - ref.float()).abs().max().item()
    out.float().square().mean().backward()
    ok = finite(out, q.grad, k.grad, v.grad)
    return {"max_abs_error": max_err, "finite_output_and_grads": ok, "lengths": lengths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    result = {
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "gfx": torch.cuda.get_device_properties(0).gcnArchName,
        "triton_env": os.environ.get("FLASH_ATTENTION_TRITON_AMD_ENABLE"),
        **backend_info(),
        "dense": {},
        "varlen": {},
    }
    for dtype, name in ((torch.float16, "fp16"), (torch.bfloat16, "bf16")):
        for causal in (False, True):
            result["dense"][f"{name}_causal_{int(causal)}"] = dense_check(dtype, causal)
        result["varlen"][name] = varlen_check(dtype)
    torch.cuda.synchronize()
    assert all(x["finite_output_and_grads"] for x in result["dense"].values())
    assert all(x["finite_output_and_grads"] for x in result["varlen"].values())
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w") as handle:
            handle.write(text + "\n")


if __name__ == "__main__":
    main()
