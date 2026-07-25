# -*- coding: utf-8 -*-
"""Train DeviationNet: runway deviation regression on AMD ROCm.

Dataset layout: <data>/frames/<sortie>/NNNNNN.jpg + <data>/labels.csv
Targets: cross_track_m (right positive), heading_err_deg (nose right positive)

Usage:
    python train_deviation.py --data /mnt/ramdisk/dcs/full --epochs 30 --out runs/full01

Notes for gfx906 (Radeon VII / MI50 class), ROCm 7.2:
    export ROCBLAS_TENSILE_LIBPATH=/opt/rocm/lib/rocblas/library
    export MIOPEN_DEBUG_CONV_WINOGRAD=0 MIOPEN_DEBUG_CONV_DIRECT=0 \
           MIOPEN_DEBUG_CONV_IMPLICIT_GEMM=0 MIOPEN_DEBUG_CONV_FFT=0 \
           MIOPEN_FIND_MODE=FAST
    (forces the GEMM convolution path; MIOpen ships no precompiled kernels
     for gfx906 and its JIT search is pathologically slow on this target)
"""
import argparse
import csv
import os
import random
import time

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

# label normalization: network output * SCALE = physical value
SCALE_CROSS = 10.0   # meters
SCALE_HERR = 5.0     # degrees
CROP_TOP_FRAC = 2.0 / 3.0   # keep top 2/3 of the frame (crop instrument panel)


def load_labels(data_dir, ground_only=True):
    rows = []
    with open(os.path.join(data_dir, "labels.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["live"] != "1":
                continue
            if ground_only and (float(r["agl"]) > 10.0 or float(r["ias"]) < 2.0):
                continue
            rows.append((r["frame"], float(r["cross_track_m"]),
                         float(r["heading_err_deg"])))
    return rows


def split_by_sortie(rows, val_frac=0.15, seed=7):
    """Hold out whole sorties, never single frames: frames within one sortie
    are heavily correlated, a frame-level split would leak."""
    sorties = sorted({r[0].split("/")[0] for r in rows})
    rng = random.Random(seed)
    rng.shuffle(sorties)
    n_val = max(1, int(len(sorties) * val_frac))
    val_set = set(sorties[:n_val])
    tr = [r for r in rows if r[0].split("/")[0] not in val_set]
    va = [r for r in rows if r[0].split("/")[0] in val_set]
    return tr, va, sorted(val_set)


class FrameDataset(Dataset):
    def __init__(self, data_dir, rows, train):
        self.dir = data_dir
        self.rows = rows
        self.train = train

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        import cv2
        rel, cross, herr = self.rows[i]
        img = cv2.imread(os.path.join(self.dir, "frames", rel))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h = img.shape[0]
        img = img[: int(h * CROP_TOP_FRAC)]

        if self.train:
            if random.random() < 0.5:            # horizontal flip: negate labels
                img = img[:, ::-1]
                cross, herr = -cross, -herr
            # brightness/contrast jitter (different time-of-day lighting)
            a = 1.0 + random.uniform(-0.15, 0.15)
            b = random.uniform(-20, 20)
            img = np.clip(img.astype(np.float32) * a + b, 0, 255)

        x = torch.from_numpy(np.ascontiguousarray(img)).float()
        x = x.permute(2, 0, 1) / 255.0 - 0.5
        y = torch.tensor([cross / SCALE_CROSS, herr / SCALE_HERR],
                         dtype=torch.float32)
        # large deviations are rare but matter most for recovery behavior
        w = torch.tensor(1.0 + abs(cross) / 3.0, dtype=torch.float32)
        return x, y, w


def conv_block(cin, cout, stride):
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, stride, 1, bias=False),
        nn.BatchNorm2d(cout), nn.ReLU(inplace=True))


class DeviationNet(nn.Module):
    """0.48M-parameter CNN, input 3x180x480, output 2 regression values."""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            conv_block(3, 24, 2),     # 90x240
            conv_block(24, 48, 2),    # 45x120
            conv_block(48, 96, 2),    # 23x60
            conv_block(96, 128, 2),   # 12x30
            conv_block(128, 192, 2),  # 6x15
            nn.AdaptiveAvgPool2d((1, 4)),   # keep 4 horizontal cells of spatial info
            nn.Flatten(),
            nn.Linear(192 * 4, 128), nn.ReLU(inplace=True),
            nn.Dropout(0.1),
            nn.Linear(128, 2))

    def forward(self, x):
        return self.net(x)


def evaluate(model, loader, dev):
    model.eval()
    se_c, se_h, ae_c, ae_h, n = 0.0, 0.0, 0.0, 0.0, 0
    with torch.no_grad():
        for x, y, _ in loader:
            x, y = x.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
            p = model(x)
            dc = (p[:, 0] - y[:, 0]) * SCALE_CROSS
            dh = (p[:, 1] - y[:, 1]) * SCALE_HERR
            se_c += (dc ** 2).sum().item(); ae_c += dc.abs().sum().item()
            se_h += (dh ** 2).sum().item(); ae_h += dh.abs().sum().item()
            n += x.size(0)
    return (ae_c / n, (se_c / n) ** 0.5, ae_h / n, (se_h / n) ** 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="runs/run01")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--all-frames", action="store_true",
                    help="include airborne frames (default: ground roll only)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device: {dev} "
          f"({torch.cuda.get_device_name(0) if dev == 'cuda' else 'cpu'})")

    rows = load_labels(args.data, ground_only=not args.all_frames)
    tr_rows, va_rows, val_sorties = split_by_sortie(rows)
    print(f"train {len(tr_rows)} | val {len(va_rows)} "
          f"(val sorties: {len(val_sorties)})")

    tr_ds = FrameDataset(args.data, tr_rows, train=True)
    va_ds = FrameDataset(args.data, va_rows, train=False)
    tr_ld = DataLoader(tr_ds, batch_size=args.batch, shuffle=True,
                       num_workers=args.workers, pin_memory=True,
                       drop_last=True, persistent_workers=args.workers > 0)
    va_ld = DataLoader(va_ds, batch_size=args.batch, shuffle=False,
                       num_workers=max(2, args.workers // 2), pin_memory=True,
                       persistent_workers=args.workers > 0)

    model = DeviationNet().to(dev)
    n_par = sum(p.numel() for p in model.parameters())
    print(f"params: {n_par/1e6:.2f}M")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
    crit = nn.SmoothL1Loss(reduction="none", beta=0.2)

    best = 1e9
    log = open(os.path.join(args.out, "train_log.csv"), "w", newline="")
    lw = csv.writer(log)
    lw.writerow(["epoch", "loss", "val_mae_cross_m", "val_rmse_cross_m",
                 "val_mae_herr_deg", "val_rmse_herr_deg", "sec"])

    for ep in range(1, args.epochs + 1):
        model.train()
        t0, tot, nb = time.time(), 0.0, 0
        for x, y, w in tr_ld:
            x = x.to(dev, non_blocking=True)
            y = y.to(dev, non_blocking=True)
            w = w.to(dev, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            p = model(x)
            loss = (crit(p, y).mean(dim=1) * w).mean()
            loss.backward()
            opt.step()
            tot += loss.item(); nb += 1
        sched.step()
        mae_c, rmse_c, mae_h, rmse_h = evaluate(model, va_ld, dev)
        dt = time.time() - t0
        print(f"ep{ep:3d} loss {tot/nb:.4f} | val cross MAE {mae_c:.2f}m "
              f"RMSE {rmse_c:.2f}m | herr MAE {mae_h:.2f}deg "
              f"RMSE {rmse_h:.2f}deg | {dt:.0f}s")
        lw.writerow([ep, f"{tot/nb:.4f}", f"{mae_c:.3f}", f"{rmse_c:.3f}",
                     f"{mae_h:.3f}", f"{rmse_h:.3f}", f"{dt:.0f}"])
        log.flush()
        score = mae_c + mae_h
        if score < best:
            best = score
            torch.save({"model": model.state_dict(),
                        "scale_cross": SCALE_CROSS, "scale_herr": SCALE_HERR,
                        "crop_top_frac": CROP_TOP_FRAC},
                       os.path.join(args.out, "best.pt"))

    # export ONNX from the best checkpoint
    ck = torch.load(os.path.join(args.out, "best.pt"), map_location=dev)
    model.load_state_dict(ck["model"])
    model.eval()
    dummy = torch.randn(1, 3, 180, 480, device=dev)
    torch.onnx.export(model, dummy, os.path.join(args.out, "deviation.onnx"),
                      input_names=["frame"], output_names=["dev"],
                      dynamic_axes={"frame": {0: "n"}, "dev": {0: "n"}})
    print(f"best score {best:.2f} -> {args.out}/best.pt + deviation.onnx")


if __name__ == "__main__":
    main()
