"""
Lightweight vision-based terrain classifier + AMD ROCm benchmark.

Purpose in this project:
  The gait controller currently gets terrain difficulty as a ground-truth
  flag. In a real deployment, a robot would need to PERCEIVE terrain type
  from an onboard camera and adapt its gait/PD gains accordingly. This
  module is a small CNN that classifies a depth/RGB patch into a terrain
  class (e.g. pavement / gravel / grass / slippery), and is meant to run
  on-device on the AMD Radeon GPU via ROCm for real-time inference.

  This script also benchmarks CPU vs GPU (ROCm) inference latency, which
  is the evidence we submit for the "AMD Radeon GPU / ROCm adoption"
  judging criterion.

Run on a ROCm machine:
    pip install torch --index-url https://download.pytorch.org/whl/rocm6.1
    python terrain_classifier.py --benchmark

If no GPU is available, the script gracefully benchmarks CPU only.
"""

import argparse
import time

import torch
import torch.nn as nn


class TinyTerrainCNN(nn.Module):
    """Small CNN: classifies a 64x64 RGB image patch into terrain classes.
    Deliberately tiny so it can run at high frequency (>100Hz target) on
    an onboard GPU for real-time gait adaptation.
    """

    CLASSES = ["pavement", "gravel", "grass", "slippery"]

    def __init__(self, num_classes: int = 4):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.head = nn.Linear(64, num_classes)

    def forward(self, x):
        x = self.features(x)
        x = x.flatten(1)
        return self.head(x)


def get_device():
    if torch.cuda.is_available():
        # On ROCm builds of PyTorch, AMD GPUs are exposed through the same
        # torch.cuda API namespace.
        name = torch.cuda.get_device_name(0)
        return torch.device("cuda"), name
    return torch.device("cpu"), "CPU"


def benchmark(device, n_iters=200, batch_size=8):
    model = TinyTerrainCNN().to(device).eval()
    x = torch.randn(batch_size, 3, 64, 64, device=device)

    # Warmup
    with torch.no_grad():
        for _ in range(10):
            model(x)
    if device.type == "cuda":
        torch.cuda.synchronize()

    start = time.time()
    with torch.no_grad():
        for _ in range(n_iters):
            model(x)
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.time() - start

    per_batch_ms = (elapsed / n_iters) * 1000
    throughput = (n_iters * batch_size) / elapsed
    return {
        "device": str(device),
        "iters": n_iters,
        "batch_size": batch_size,
        "ms_per_batch": round(per_batch_ms, 3),
        "images_per_sec": round(throughput, 1),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--iters", type=int, default=200)
    args = parser.parse_args()

    device, name = get_device()
    print(f"Detected device: {name} ({device})")

    if args.benchmark:
        results = [benchmark(device, n_iters=args.iters)]
        if device.type == "cuda":
            cpu_result = benchmark(torch.device("cpu"), n_iters=args.iters)
            results.append(cpu_result)
        for r in results:
            print(r)
        speedup = None
        if len(results) == 2:
            speedup = round(results[1]["ms_per_batch"] / results[0]["ms_per_batch"], 2)
            print(f"\nGPU speedup over CPU: {speedup}x")


if __name__ == "__main__":
    main()
