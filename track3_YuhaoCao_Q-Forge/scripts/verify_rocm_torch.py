#!/usr/bin/env python3
"""Exercise the PyTorch operations QVGM relies on using a ROCm GPU."""

from pathlib import Path
import tempfile

from packaging.version import Version
import torch
import torch.nn.functional as F


def main() -> None:
    assert torch.cuda.is_available(), "ROCm GPU is unavailable to PyTorch"
    assert Version(torch.__version__.split("+")[0]) >= Version("2.8.0")
    assert torch.version.hip is not None, "This is not a ROCm PyTorch build"
    assert torch.version.cuda is None, "A CUDA build was installed by mistake"

    # PyTorch intentionally keeps the torch.cuda API and the "cuda" device
    # spelling on ROCm. HIP kernels are used underneath this compatibility API.
    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    architecture = getattr(properties, "gcnArchName", "unknown")

    for dtype in (torch.float32, torch.float16, torch.bfloat16):
        a = torch.randn(256, 256, device=device, dtype=dtype)
        b = torch.randn(256, 256, device=device, dtype=dtype)
        assert torch.isfinite(a @ b).all()

    q = torch.randn(2, 4, 32, 64, device=device, requires_grad=True)
    k = torch.randn_like(q, requires_grad=True)
    v = torch.randn_like(q, requires_grad=True)
    F.scaled_dot_product_attention(q, k, v).square().mean().backward()
    assert q.grad is not None and torch.isfinite(q.grad).all()

    model = torch.nn.Linear(64, 32, device=device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    optimizer.zero_grad(set_to_none=True)
    with torch.autocast("cuda", dtype=torch.bfloat16):
        loss = model(torch.randn(16, 64, device=device)).square().mean()
    loss.backward()
    optimizer.step()

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "checkpoint.pt"
        torch.save(model.state_dict(), path)
        restored = torch.nn.Linear(64, 32, device=device)
        restored.load_state_dict(torch.load(path, weights_only=True))

    torch.cuda.synchronize()
    print(f"PASS torch={torch.__version__} hip={torch.version.hip}")
    print(
        f"GPU={torch.cuda.get_device_name(device)} "
        f"architecture={architecture} vram={properties.total_memory / 2**30:.1f}GiB"
    )


if __name__ == "__main__":
    main()
