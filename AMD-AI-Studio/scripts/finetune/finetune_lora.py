#!/usr/bin/env python3
"""
AMD AI Studio — 模型微调训练脚本
支持 SDXL LoRA / DreamBooth / 全参微调
"""

import os
import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Optional, List

import torch
from accelerate import Accelerator
from accelerate.utils import set_seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("finetune")

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from modules.rocm_utils import is_rocm_available, get_optimal_device


# ============================================================
# 参数解析
# ============================================================
def parse_args():
    parser = argparse.ArgumentParser(description="AMD AI Studio — 模型微调")

    # 训练模式
    parser.add_argument(
        "--method",
        type=str,
        default="lora",
        choices=["lora", "dreambooth", "full"],
        help="微调方法 (lora / dreambooth / full)",
    )
    parser.add_argument(
        "--base_model",
        type=str,
        default="stabilityai/stable-diffusion-xl-base-1.0",
        help="基础模型 ID 或本地路径",
    )

    # 数据集
    parser.add_argument("--dataset_dir", type=str, required=True, help="数据集目录")
    parser.add_argument("--caption_col", type=str, default="text", help="数据集中的文本列名")
    parser.add_argument("--image_col", type=str, default="image", help="数据集中的图像列名")
    parser.add_argument("--resolution", type=int, default=1024, help="训练分辨率 (默认 1024)")
    parser.add_argument(
        "--center_crop", action="store_true", default=True, help="启用中心裁剪"
    )
    parser.add_argument(
        "--random_flip", action="store_true", default=False, help="启用随机翻转"
    )

    # LoRA 参数
    parser.add_argument("--lora_rank", type=int, default=64, help="LoRA rank (默认 64)")
    parser.add_argument("--lora_alpha", type=int, default=128, help="LoRA alpha (默认 128)")
    parser.add_argument(
        "--lora_target_modules",
        type=str,
        nargs="+",
        default=["to_q", "to_k", "to_v", "to_out.0", "ff.net.0.proj", "ff.net.2"],
        help="LoRA 目标模块",
    )

    # 训练参数
    parser.add_argument("--learning_rate", type=float, default=1e-4, help="学习率")
    parser.add_argument("--train_batch_size", type=int, default=1, help="训练批次大小")
    parser.add_argument("--max_train_steps", type=int, default=1000, help="最大训练步数")
    parser.add_argument("--num_epochs", type=int, default=1, help="训练轮数")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=4, help="梯度累积步数")
    parser.add_argument("--lr_scheduler", type=str, default="constant", help="学习率调度器")
    parser.add_argument("--lr_warmup_steps", type=int, default=100, help="学习率预热步数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--mixed_precision", type=str, default="fp16", help="混合精度 (fp16/bf16/no)")

    # 输出
    parser.add_argument("--output_dir", type=str, default="outputs/finetune", help="输出目录")
    parser.add_argument("--save_steps", type=int, default=200, help="保存间隔步数")
    parser.add_argument("--save_total_limit", type=int, default=3, help="最大保存数")

    # 验证
    parser.add_argument("--validation_prompt", type=str, default="", help="验证提示词")
    parser.add_argument("--validation_steps", type=int, default=200, help="验证间隔步数")

    return parser.parse_args()


# ============================================================
# 数据集准备
# ============================================================
def prepare_dataset(args):
    """加载并准备训练数据集"""
    from datasets import load_dataset

    dataset_dir = Path(args.dataset_dir)
    if not dataset_dir.exists():
        raise FileNotFoundError(f"数据集目录不存在: {dataset_dir}")

    # 检测数据集格式
    if (dataset_dir / "metadata.jsonl").exists():
        # 经典格式: metadata.jsonl + images/
        dataset = load_dataset("json", data_files=str(dataset_dir / "metadata.jsonl"), split="train")
    elif (dataset_dir / "metadata.csv").exists():
        dataset = load_dataset("csv", data_files=str(dataset_dir / "metadata.csv"), split="train")
    elif list(dataset_dir.glob("*.json")) or list(dataset_dir.glob("*.jsonl")):
        # 自动检测
        json_files = list(dataset_dir.glob("*.json")) + list(dataset_dir.glob("*.jsonl"))
        dataset = load_dataset("json", data_files=[str(f) for f in json_files], split="train")
    else:
        # 尝试直接加载目录（每张图一个文件）
        image_files = list(dataset_dir.glob("*.[pj][pn]g")) + list(dataset_dir.glob("*.webp"))
        if image_files:
            logger.info(f"发现 {len(image_files)} 张图片，将使用文件名作为提示词")
            from datasets import Dataset
            data = {
                "image": [str(f) for f in image_files],
                "text": [f.stem.replace("_", " ").replace("-", " ") for f in image_files],
            }
            dataset = Dataset.from_dict(data)
        else:
            raise ValueError(f"无法识别的数据集格式: {dataset_dir}")

    logger.info(f"数据集大小: {len(dataset)} 条")
    logger.info(f"数据集列: {dataset.column_names}")
    return dataset


def preprocess_dataset(dataset, args):
    """预处理数据集（图像缩放、编码等）"""
    from torchvision import transforms
    from torchvision.transforms import functional as F

    def preprocess_fn(examples):
        images = []
        captions = []

        for i in range(len(examples["image"])):
            # 加载图像
            image = examples["image"][i]
            if isinstance(image, str):
                from PIL import Image
                image = Image.open(image).convert("RGB")

            # 缩放
            image = image.resize(
                (args.resolution, args.resolution),
                transforms.InterpolationMode.BILINEAR,
            )

            # 中心裁剪
            if args.center_crop:
                w, h = image.size
                min_side = min(w, h)
                image = transforms.CenterCrop(min_side)(image)
                image = image.resize((args.resolution, args.resolution))

            # 随机翻转
            if args.random_flip and torch.rand(1) > 0.5:
                image = F.hflip(image)

            # 转 tensor
            image = transforms.ToTensor()(image)
            image = transforms.Normalize([0.5], [0.5])(image)

            images.append(image)
            captions.append(examples[args.caption_col][i])

        return {"pixel_values": images, "caption": captions}

    dataset = dataset.map(preprocess_fn, batched=True, remove_columns=dataset.column_names)
    return dataset


# ============================================================
# 模型加载
# ============================================================
def load_base_model(args):
    """加载基础模型"""
    from diffusers import (
        StableDiffusionXLPipeline,
        AutoencoderKL,
        DDPMScheduler,
    )
    from transformers import CLIPTokenizer, CLIPTextModel, CLIPTextModelWithProjection

    device = get_optimal_device()
    torch_dtype = torch.float16 if args.mixed_precision == "fp16" else torch.float32

    logger.info(f"加载基础模型: {args.base_model}")
    logger.info(f"设备: {device}, 精度: {torch_dtype}")

    # 加载 VAE
    vae = AutoencoderKL.from_pretrained(
        "madebyollin/sdxl-vae-fp16-fix",
        torch_dtype=torch_dtype,
    )

    # 加载 UNet
    from diffusers import UNet2DConditionModel
    unet = UNet2DConditionModel.from_pretrained(
        args.base_model,
        subfolder="unet",
        torch_dtype=torch_dtype,
    )

    # 加载文本编码器
    tokenizer_1 = CLIPTokenizer.from_pretrained(args.base_model, subfolder="tokenizer")
    tokenizer_2 = CLIPTokenizer.from_pretrained(args.base_model, subfolder="tokenizer_2")
    text_encoder_1 = CLIPTextModel.from_pretrained(args.base_model, subfolder="text_encoder")
    text_encoder_2 = CLIPTextModelWithProjection.from_pretrained(
        args.base_model, subfolder="text_encoder_2"
    )

    # 噪声调度器
    noise_scheduler = DDPMScheduler.from_pretrained(
        args.base_model, subfolder="scheduler"
    )

    return {
        "unet": unet,
        "vae": vae,
        "tokenizer_1": tokenizer_1,
        "tokenizer_2": tokenizer_2,
        "text_encoder_1": text_encoder_1,
        "text_encoder_2": text_encoder_2,
        "noise_scheduler": noise_scheduler,
    }


# ============================================================
# LoRA 注入
# ============================================================
def add_lora_to_unet(unet, args):
    """向 UNet 注入 LoRA"""
    from diffusers.utils import USE_PEFT_BACKEND
    from peft import LoraConfig, get_peft_model

    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        target_modules=args.lora_target_modules,
        lora_dropout=0.1,
        bias="none",
        task_type="UNET_2D_CONDITION",
    )

    unet = get_peft_model(unet, lora_config)
    logger.info(f"LoRA 已注入 UNet (rank={args.lora_rank}, alpha={args.lora_alpha})")
    logger.info(f"可训练参数: {unet.num_parameters(only_trainable=True):,}")
    return unet


# ============================================================
# 训练主循环
# ============================================================
def train_lora(args):
    """执行 LoRA 微调"""
    from PIL import Image
    from diffusers import StableDiffusionXLPipeline
    from diffusers.optimization import get_scheduler
    from torch.utils.data import DataLoader
    from tqdm import tqdm

    # 初始化加速器
    accelerator = Accelerator(
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        mixed_precision=args.mixed_precision,
    )
    set_seed(args.seed)

    # 准备数据集
    dataset = prepare_dataset(args)
    dataset = preprocess_dataset(dataset, args)
    train_dataloader = DataLoader(
        dataset, batch_size=args.train_batch_size, shuffle=True
    )

    # 加载模型
    models = load_base_model(args)

    # 冻结 VAE 和文本编码器（LoRA 只训练 UNet）
    models["vae"].requires_grad_(False)
    models["text_encoder_1"].requires_grad_(False)
    models["text_encoder_2"].requires_grad_(False)

    # 注入 LoRA
    unet = add_lora_to_unet(models["unet"], args)

    # 优化器
    optimizer = torch.optim.AdamW(
        unet.parameters(),
        lr=args.learning_rate,
        betas=(0.9, 0.999),
    )

    # 学习率调度器
    lr_scheduler = get_scheduler(
        args.lr_scheduler,
        optimizer=optimizer,
        num_warmup_steps=args.lr_warmup_steps * accelerator.num_processes,
        num_training_steps=args.max_train_steps * accelerator.num_processes,
    )

    # 准备加速
    unet, optimizer, train_dataloader, lr_scheduler = accelerator.prepare(
        unet, optimizer, train_dataloader, lr_scheduler
    )

    # 移动 VAE/文本编码器到设备
    vae = models["vae"].to(accelerator.device)
    text_encoder_1 = models["text_encoder_1"].to(accelerator.device)
    text_encoder_2 = models["text_encoder_2"].to(accelerator.device)
    noise_scheduler = models["noise_scheduler"]

    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 训练
    logger.info("=" * 50)
    logger.info("开始训练...")
    logger.info(f"  方法: LoRA (rank={args.lora_rank})")
    logger.info(f"  数据集: {args.dataset_dir} ({len(dataset)} 条)")
    logger.info(f"  步数: {args.max_train_steps}")
    logger.info(f"  批次: {args.train_batch_size} × {args.gradient_accumulation_steps} (累积)")
    logger.info(f"  学习率: {args.learning_rate}")
    logger.info(f"  精度: {args.mixed_precision}")
    logger.info(f"  设备: {accelerator.device}")
    logger.info("=" * 50)

    global_step = 0
    progress_bar = tqdm(total=args.max_train_steps, desc="训练进度")
    train_loss = 0.0

    for epoch in range(args.num_epochs):
        unet.train()
        for batch in train_dataloader:
            with accelerator.accumulate(unet):
                # 编码图像到 latent
                latents = vae.encode(batch["pixel_values"].to(dtype=vae.dtype)).latent_dist.sample()
                latents = latents * vae.config.scaling_factor

                # 添加噪声
                noise = torch.randn_like(latents)
                timesteps = torch.randint(
                    0, noise_scheduler.config.num_train_timesteps,
                    (latents.shape[0],), device=latents.device,
                ).long()
                noisy_latents = noise_scheduler.add_noise(latents, noise, timesteps)

                # 编码文本
                prompt_ids = tokenize_prompt(
                    batch["caption"], models["tokenizer_1"], models["tokenizer_2"],
                    accelerator.device,
                )

                # 预测噪声
                noise_pred = unet(
                    noisy_latents, timesteps, prompt_ids
                ).sample

                # 损失
                loss = torch.nn.functional.mse_loss(noise_pred.float(), noise.float())
                accelerator.backward(loss)

                if accelerator.sync_gradients:
                    accelerator.clip_grad_norm_(unet.parameters(), max_norm=1.0)

                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad()

            # 日志
            if accelerator.sync_gradients:
                global_step += 1
                train_loss += loss.detach().float()
                progress_bar.update(1)
                progress_bar.set_postfix(loss=loss.detach().float().item())

                # 保存 checkpoint
                if global_step % args.save_steps == 0:
                    save_lora_weights(unet, output_dir, global_step, accelerator)
                    logger.info(f"Checkpoint 保存: step_{global_step}")

                # 验证
                if args.validation_prompt and global_step % args.validation_steps == 0:
                    validate(unet, args.validation_prompt, output_dir, global_step, accelerator)

                if global_step >= args.max_train_steps:
                    break

    progress_bar.close()

    # 保存最终模型
    save_lora_weights(unet, output_dir, "final", accelerator)
    logger.info(f"训练完成！模型已保存: {output_dir}")

    return str(output_dir)


# ============================================================
# 辅助函数
# ============================================================
def tokenize_prompt(captions, tokenizer_1, tokenizer_2, device):
    """对提示词进行编码（SDXL 双编码器）"""
    # 编码器 1
    tokens_1 = tokenizer_1(
        captions, padding="max_length", max_length=77, truncation=True, return_tensors="pt"
    ).to(device)

    # 编码器 2
    tokens_2 = tokenizer_2(
        captions, padding="max_length", max_length=77, truncation=True, return_tensors="pt"
    ).to(device)

    return {
        "encoder_hidden_states_1": tokens_1.input_ids,
        "encoder_hidden_states_2": tokens_2.input_ids,
    }


def save_lora_weights(unet, output_dir, step, accelerator):
    """保存 LoRA 权重"""
    save_path = Path(output_dir) / f"step_{step}"
    accelerator.unwrap_model(unet).save_pretrained(str(save_path))
    logger.info(f"LoRA 权重已保存: {save_path}")


def validate(unet, prompt, output_dir, step, accelerator):
    """生成验证图像"""
    from diffusers import StableDiffusionXLPipeline
    import torch

    # 创建推理 pipeline
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        unet=accelerator.unwrap_model(unet),
        torch_dtype=torch.float16,
    ).to(accelerator.device)

    with torch.no_grad():
        image = pipe(
            prompt=prompt,
            num_inference_steps=30,
            guidance_scale=7.5,
        ).images[0]

    save_path = Path(output_dir) / f"val_step_{step}.png"
    image.save(save_path)
    logger.info(f"验证图像已保存: {save_path}")


# ============================================================
# 推理（加载训练好的 LoRA）
# ============================================================
def inference_with_lora(
    lora_path: str,
    prompt: str,
    base_model: str = "stabilityai/stable-diffusion-xl-base-1.0",
    output_path: str = "outputs/finetune/inference.png",
    **kwargs,
):
    """使用训练好的 LoRA 权重生成图像"""
    from diffusers import StableDiffusionXLPipeline
    from peft import PeftModel

    logger.info(f"加载 LoRA: {lora_path}")
    logger.info(f"提示词: {prompt}")

    pipe = StableDiffusionXLPipeline.from_pretrained(
        base_model,
        torch_dtype=torch.float16,
    ).to(get_optimal_device())

    pipe.load_lora_weights(lora_path)
    pipe.fuse_lora()

    image = pipe(
        prompt=prompt,
        num_inference_steps=kwargs.get("steps", 30),
        guidance_scale=kwargs.get("guidance", 7.5),
    ).images[0]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    logger.info(f"LoRA 推理完成: {output_path}")
    return output_path


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    args = parse_args()

    if args.method == "lora":
        train_lora(args)
    elif args.method == "dreambooth":
        logger.info("DreamBooth 模式尚未实现")
    elif args.method == "full":
        logger.info("全参微调模式尚未实现")
