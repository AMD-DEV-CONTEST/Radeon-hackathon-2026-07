#!/usr/bin/env python3
"""
scripts/quantize_gptq.py - quantize Qwen3-8B (FP16) to GPTQ-Int4

Usage:
    python scripts/quantize_gptq.py

Prerequisites:
    1. Qwen3-8B already downloaded to ./models/Qwen3-8B
    2. pip install gptqmodel torch transformers datasets

Notes:
    Qwen3 does not officially release a GPTQ-Int4 pre-quantized version (unlike Qwen2.5),
    so it must be quantized locally. GPTQModel supports ROCm GPU acceleration.

    The quantized model is saved to ./models/Qwen3-8B-GPTQ-Int4,
    and can be loaded directly by vLLM with --quantization gptq.
"""
import os
import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def detect_device():
    """Detect an available quantization device, returning a valid device string for GPTQModel."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        logger.warning("CUDA/HIP unavailable; will use CPU quantization (very slow)")
        return "cpu"
    except ImportError:
        logger.warning("torch not installed; defaulting to CPU")
        return "cpu"


def main():
    parser = argparse.ArgumentParser(description="Qwen3-8B GPTQ-Int4 local quantization")
    parser.add_argument(
        "--source", default="./models/Qwen3-8B",
        help="FP16 source model path (default: ./models/Qwen3-8B)"
    )
    parser.add_argument(
        "--target", default="./models/Qwen3-8B-GPTQ-Int4",
        help="INT4 quantized model output path (default: ./models/Qwen3-8B-GPTQ-Int4)"
    )
    parser.add_argument(
        "--bits", type=int, default=4, choices=[2, 3, 4, 8],
        help="quantization bits (default: 4)"
    )
    parser.add_argument(
        "--group-size", type=int, default=128,
        help="group size (default: 128, 0=no grouping)"
    )
    parser.add_argument(
        "--calib-samples", type=int, default=128,
        help="number of calibration samples (default: 128; more means higher accuracy but slower)"
    )
    parser.add_argument(
        "--device", default=None,
        help="quantization device: cuda/cpu (default: auto-detect)"
    )
    args = parser.parse_args()

    # 1. Check the source model
    if not os.path.isdir(args.source):
        logger.error(f"Source model does not exist: {args.source}")
        logger.error("Please run first: bash scripts/download_models.sh")
        sys.exit(1)

    config_path = os.path.join(args.source, "config.json")
    if not os.path.isfile(config_path):
        logger.error(f"Source model is missing config.json: {config_path}")
        sys.exit(1)

    # 2. Check/install GPTQModel
    try:
        from gptqmodel import GPTQModel
    except ImportError:
        logger.warning("GPTQModel not installed; installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gptqmodel"])
        from gptqmodel import GPTQModel

    # 3. Device detection (GPTQModel does not support "auto"; resolve to cuda/cpu)
    device = args.device if args.device else detect_device()
    logger.info(f"Quantization device: {device}")

    logger.info(f"Source model: {args.source}")
    logger.info(f"Output path: {args.target}")
    logger.info(f"Quantization params: bits={args.bits}, group_size={args.group_size}, calib={args.calib_samples}")

    # 4. Prepare the calibration dataset
    logger.info("Loading calibration dataset (wikitext-2)...")
    tokenizer = None
    calibration = None
    try:
        from transformers import AutoTokenizer
        from datasets import load_dataset

        tokenizer = AutoTokenizer.from_pretrained(args.source, trust_remote_code=True)
        # Use the repo_id format "wikitext/wikitext-2-raw-v1" to avoid URI parsing issues in newer datasets versions
        dataset = load_dataset("wikitext", "wikitext-2-raw-v1", split="train", trust_remote_code=True)
        calibration = []
        for text in dataset["text"]:
            if len(text.strip()) > 50:
                tokens = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
                calibration.append(tokens["input_ids"])
                if len(calibration) >= args.calib_samples:
                    break
        logger.info(f"Calibration samples: {len(calibration)}")
    except Exception as e:
        logger.warning(f"Failed to load wikitext dataset ({e})")
        logger.warning("Using built-in random calibration data (accuracy may drop slightly)")
        # Ensure there is at least a tokenizer
        if tokenizer is None:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(args.source, trust_remote_code=True)
        import torch
        # Generate random token sequences as calibration data
        vocab_size = tokenizer.vocab_size
        calibration = [
            torch.randint(0, vocab_size, (1, 512))
            for _ in range(min(args.calib_samples, 32))
        ]
        logger.info(f"Random calibration samples: {len(calibration)}")

    # 5. Load the FP16 model
    logger.info(f"Loading FP16 model: {args.source}")
    from gptqmodel import GPTQModel, QuantizeConfig

    quantize_config = QuantizeConfig(
        bits=args.bits,
        group_size=args.group_size,
        desc_act=True,           # activation-aware quantization for better accuracy
        sym=True,                # symmetric quantization
    )

    # 6. Run quantization
    logger.info("Starting GPTQ quantization (may take 10-30 minutes)...")
    model = GPTQModel.from_pretrained(
        args.source,
        quantize_config=quantize_config,
        trust_remote_code=False,  # Qwen3 is natively supported by transformers, set to False
        device=device,
    )

    if calibration:
        model.quantize(calibration)
    else:
        model.quantize()  # use built-in calibration

    # 7. Save the quantized model
    logger.info(f"Saving quantized model to: {args.target}")
    os.makedirs(args.target, exist_ok=True)
    model.save_quantized(args.target)

    # Save the tokenizer
    tokenizer.save_pretrained(args.target)

    # 8. Verify
    logger.info("Verifying the quantized model can be loaded...")
    del model
    loaded = GPTQModel.from_quantized(
        args.target,
        device=device,
        trust_remote_code=False,
    )
    logger.info(f"Quantized model loaded successfully: {args.target}")

    # Check the output files
    safetensors = [f for f in os.listdir(args.target) if f.endswith(".safetensors")]
    logger.info(f"Output files: {len(safetensors)} safetensors + config.json + tokenizer")

    # Compute the model size
    total_size = sum(
        os.path.getsize(os.path.join(args.target, f))
        for f in os.listdir(args.target)
    )
    logger.info(f"Quantized model total size: {total_size / (1024**3):.2f} GB")

    print()
    print("=" * 60)
    print("GPTQ-Int4 quantization complete!")
    print(f"  Source model:   {args.source}")
    print(f"  Quantized model: {args.target}")
    print(f"  Bits:     {args.bits}-bit")
    print(f"  Group size:     {args.group_size}")
    print(f"  Size:     {total_size / (1024**3):.2f} GB")
    print()
    print("vLLM load command:")
    print(f"  python -m vllm.entrypoints.openai.api_server \\")
    print(f"      --model {args.target} \\")
    print(f"      --quantization gptq \\")
    print(f"      --dtype bfloat16 \\")
    print(f"      --port 8000")
    print("=" * 60)


if __name__ == "__main__":
    main()
