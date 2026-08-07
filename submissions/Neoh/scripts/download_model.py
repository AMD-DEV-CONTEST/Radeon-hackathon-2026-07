"""下载 Qwen2.5 模型（safetensors 格式，vLLM 使用）。默认 14B，可用 --model 切换 7B。

支持多源下载：
1. ModelScope（国内最快，推荐）
2. HuggingFace + hf-mirror
3. HuggingFace 官方

下载的是完整 safetensors 权重（14B FP16 约 28GB，7B 约 15GB），vLLM 直接加载。
"""

import argparse
import logging
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# 模型仓库配置
MODEL_SOURCES = {
    "qwen2.5-7b": {
        "modelscope": "Qwen/Qwen2.5-7B-Instruct",
        "huggingface": "Qwen/Qwen2.5-7B-Instruct",
        "local_dir": "Qwen2.5-7B-Instruct",
    },
    "qwen2.5-14b": {
        "modelscope": "Qwen/Qwen2.5-14B-Instruct",
        "huggingface": "Qwen/Qwen2.5-14B-Instruct",
        "local_dir": "Qwen2.5-14B-Instruct",
    },
}


def download_via_modelscope(model_id: str, save_dir: str) -> str:
    """通过 ModelScope 下载（国内推荐）。"""
    try:
        from modelscope import snapshot_download
        logger.info(f"Downloading from ModelScope: {model_id}")
        path = snapshot_download(
            model_id=model_id,
            local_dir=save_dir,
        )
        logger.info(f"ModelScope download complete: {path}")
        return path
    except ImportError:
        logger.warning("modelscope not installed, trying: pip install modelscope")
        raise
    except Exception as e:
        logger.error(f"ModelScope download failed: {e}")
        raise


def download_via_huggingface(model_id: str, save_dir: str, mirror: str = None) -> str:
    """通过 HuggingFace 下载（支持镜像）。"""
    try:
        from huggingface_hub import snapshot_download
        endpoint = mirror
        logger.info(f"Downloading from HuggingFace: {model_id} (mirror: {mirror or 'default'})")
        path = snapshot_download(
            repo_id=model_id,
            local_dir=save_dir,
            endpoint=endpoint,
        )
        logger.info(f"HuggingFace download complete: {path}")
        return path
    except ImportError:
        logger.warning("huggingface_hub not installed, trying: pip install huggingface_hub")
        raise
    except Exception as e:
        logger.error(f"HuggingFace download failed: {e}")
        raise


def download_model(model_name: str, models_dir: str = "./models") -> str:
    """下载模型，按优先级尝试多个源。

    Args:
        model_name: 模型名称，如 "qwen2.5-7b"
        models_dir: 模型保存根目录

    Returns:
        模型本地路径
    """
    if model_name not in MODEL_SOURCES:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(MODEL_SOURCES.keys())}")

    sources = MODEL_SOURCES[model_name]
    save_dir = os.path.join(models_dir, sources["local_dir"])

    # 已存在则跳过
    if os.path.exists(save_dir) and os.path.exists(os.path.join(save_dir, "config.json")):
        logger.info(f"Model already exists at {save_dir}, skipping download")
        return save_dir

    os.makedirs(models_dir, exist_ok=True)

    # 按优先级尝试：ModelScope → hf-mirror → HF 官方
    errors = []

    logger.info("Attempt 1: ModelScope (recommended for China)")
    try:
        return download_via_modelscope(sources["modelscope"], save_dir)
    except Exception as e:
        errors.append(f"ModelScope: {e}")

    logger.info("Attempt 2: HuggingFace mirror (hf-mirror.com)")
    try:
        return download_via_huggingface(sources["huggingface"], save_dir, mirror="https://hf-mirror.com")
    except Exception as e:
        errors.append(f"HF mirror: {e}")

    logger.info("Attempt 3: HuggingFace official")
    try:
        return download_via_huggingface(sources["huggingface"], save_dir, mirror=None)
    except Exception as e:
        errors.append(f"HF official: {e}")

    # 全部失败
    raise RuntimeError(
        f"All download sources failed for {model_name}:\n" +
        "\n".join(f"  - {err}" for err in errors) +
        f"\n\nPlease download manually from:\n"
        f"  ModelScope: https://www.modelscope.cn/models/{sources['modelscope']}\n"
        f"  HuggingFace: https://huggingface.co/{sources['huggingface']}\n"
        f"And extract to: {save_dir}"
    )


def main():
    parser = argparse.ArgumentParser(description="下载 Qwen2.5 模型（safetensors 格式）")
    parser.add_argument(
        "--model",
        type=str,
        default="qwen2.5-14b",
        choices=["qwen2.5-7b", "qwen2.5-14b"],
        help="模型名称"
    )
    parser.add_argument(
        "--models-dir",
        type=str,
        default="./models",
        help="模型保存目录"
    )
    args = parser.parse_args()

    try:
        model_path = download_model(args.model, args.models_dir)
        logger.info(f"✅ 模型下载成功: {model_path}")

        # 统计大小
        total_size = 0
        for dirpath, _, filenames in os.walk(model_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total_size += os.path.getsize(fp)
        logger.info(f"模型总大小: {total_size / (1024**3):.2f} GB")
    except Exception as e:
        logger.error(f"模型下载失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
