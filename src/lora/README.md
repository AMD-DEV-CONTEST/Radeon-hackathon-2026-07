# Style LoRA — `stkstyle` (self-trained on AMD Radeon / ROCm)

This folder contains the **self-trained style LoRA** that locks the project's signature
"candy-neon Q-version" art style across every generation. It is trained **entirely on the
same AMD Radeon GPU (ROCm)** used for inference — no NVIDIA/CUDA, no cloud service.

> **Why it matters for the contest:** it is a second, independent proof that the whole
> pipeline (not just inference) runs on AMD ROCm. Training a diffusion LoRA on Radeon is
> non-trivial; doing it in ~70 min on a single 48 GB card shows the stack is production-real.

---

## 1. What it does

- Adds a small adapter (`stkstyle`) on top of `cagliostrolab/animagine-xl-4.0` (SDXL).
- When enabled in the WebUI (toggle **使用风格 LoRA (stkstyle)**, default weight 0.8),
  every generated sticker shares the same line weight, palette and "chibi" proportions.
- Trigger word: **`stkstyle`** — it is prepended to every training caption, so the model
  learns to associate the word with the target look.

## 2. Training configuration

| Item | Value |
|---|---|
| Base model | `cagliostrolab/animagine-xl-4.0` (SDXL 1.0, OpenRAIL++-M) |
| Platform | **AMD Radeon (Navi 31, gfx1100), ROCm 7.2**, PyTorch `2.11.0+rocm7.2` |
| Method | LoRA on UNet only; Text Encoders **frozen** (preserves prompt understanding) |
| Rank / alpha | `r=32` / `α=16` (attention + MLP targets) |
| Steps / batch | 2000 steps, batch size 2, bf16 |
| Learning rate | `1e-4`, cosine schedule |
| Resolution | 1024×1024 |
| Caption dropout | 0.15 (improves generalization, avoids overfitting the cat-girl) |
| Trainable params | 46,448,640 (1.78% of 2.61 B total) |
| Wall-clock | **4230 s (~70 min)** on a single Radeon |
| Dataset | 33 image–caption pairs (`training_data/images/`) |

The exact recipe lives in `train_stkstyle_lora.py` (PEFT `LoraConfig`, manual
Diffusers SDXL training loop, ROCm-safe bf16 + no GradScaler).

## 3. Dataset

`training_data/images/` holds 33 hand-picked anime character sheets (cat / demon /
angel / wolf / dragon / bunny / fox / lion / pig girls …) plus a `.txt` caption next to
each `.png`. Every caption starts with the trigger word `stkstyle`, e.g.:

```
stkstyle, cat girl, cat ears, pink hair, happy, big smile
```

Mixed characters + expressions were used so the LoRA captures the *style* (line, color,
proportions) rather than a single character identity.

## 4. Output weights

| Path | Format | Use |
|---|---|---|
| `models/stkstyle_lora_diffusers/pytorch_lora_weights.safetensors` | Diffusers | Loaded by the WebUI via `pipe.load_lora_weights(...)` |
| `models/stkstyle_lora/` (PEFT, on training host) | PEFT adapter | Re-training / inspection |

The Diffusers weights (~178 MB) are the ones shipped for inference.

## 5. Reproduce the training

```bash
# on an AMD Radeon with ROCm 7.x + the project venv
cd src/lora
python train_stkstyle_lora.py \
    --base_model cagliostrolab/animagine-xl-4.0 \
    --data_dir   training_data/images \
    --output models/stkstyle_lora \
    --steps 2000 --batch_size 2 --lr 1e-4 \
    --rank 32 --alpha 16 --resolution 1024 --caption_dropout 0.15

# convert PEFT -> Diffusers for the WebUI
python ../../scripts/convert_lora.py
```

> `train.log` in this folder is the real console log of the ROCm training run
> (2000 steps, loss converging ~0.04–0.09, no ROCm hang).

## 6. Use it in the generator

```bash
cd <project-root>
python src/webui/gradio_app.py --port 7860 --demo-dir demo_output
```

or simply toggle **使用风格 LoRA (stkstyle)** inside the WebUI.
