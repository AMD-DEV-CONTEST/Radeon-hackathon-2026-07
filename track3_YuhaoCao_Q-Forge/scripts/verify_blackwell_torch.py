#!/usr/bin/env python3
from pathlib import Path
import tempfile

from packaging.version import Version
import torch
import torch.nn.functional as F


def main() -> None:
    assert torch.cuda.is_available(), "CUDA is unavailable"
    assert Version(torch.__version__.split("+")[0]) >= Version("2.8.0")
    assert torch.version.cuda is not None
    assert Version(torch.version.cuda) >= Version("12.8")

    device = torch.device("cuda:0")
    name = torch.cuda.get_device_name(device)
    capability = torch.cuda.get_device_capability(device)
    assert capability >= (10, 0), capability

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
    print(f"PASS torch={torch.__version__} cuda={torch.version.cuda}")
    print(f"GPU={name} capability={capability}")


if __name__ == "__main__":
    main()
