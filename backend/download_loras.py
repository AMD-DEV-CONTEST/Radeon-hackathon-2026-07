"""
NodeFlow LoRA 批量下载脚本

使用 huggingface_hub 的 hf_hub_download 下载 LoRA 权重文件，
自动处理 HF_ENDPOINT 镜像、HF_TOKEN 鉴权、断点续传。

用法:
    python download_loras.py                  # 下载所有 LoRA
    python download_loras.py --dry-run        # 只打印计划，不下载
    python download_loras.py sdxl_cyberpunk   # 只下载单个 LoRA
"""

import argparse
import logging
import os
import shutil
import sys

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LORA_REGISTRY, DOWNLOADABLE_LORA_IDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_loras")


def download_lora(lora_id: str, lora_cfg: dict, dry_run: bool = False) -> bool:
    """使用 huggingface_hub 下载单个 LoRA 权重文件。"""
    target_path = lora_cfg["target_path"]
    base_hf = lora_cfg.get("base_hf")
    file_name = lora_cfg.get("file_name")
    name = lora_cfg["name"]

    if not base_hf or not file_name:
        logger.warning(f"[{lora_id}] base_hf or file_name is None, skipping")
        return False

    # 创建目标目录
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)

    # 如果文件已存在，跳过
    if os.path.exists(target_path):
        file_size = os.path.getsize(target_path) / (1024 * 1024)
        logger.info(
            f"[{lora_id}] Already exists: {target_path} ({file_size:.1f} MB), skipping"
        )
        return True

    if dry_run:
        logger.info(
            f"[{lora_id}] DRY-RUN: Would download {base_hf}/{file_name} -> {target_path}"
        )
        return True

    # 使用 huggingface_hub 下载
    logger.info(f"[{lora_id}] Downloading {name}...")
    logger.info(f"       Repo: {base_hf}")
    logger.info(f"       File: {file_name}")
    logger.info(f"       -> {target_path}")

    try:
        from huggingface_hub import hf_hub_download

        # hf_hub_download 自动读取 HF_ENDPOINT / HF_TOKEN / HF_HOME 环境变量
        cached_path = hf_hub_download(
            repo_id=base_hf,
            filename=file_name,
        )

        # 复制到目标路径（硬链接优先）
        shutil.copy2(cached_path, target_path)

        file_size_mb = os.path.getsize(target_path) / (1024 * 1024)
        logger.info(
            f"[{lora_id}] Downloaded successfully: {file_size_mb:.1f} MB"
        )
        return True

    except Exception as e:
        logger.error(f"[{lora_id}] Download failed: {e}")
        # 清理不完整的下载文件
        if os.path.exists(target_path):
            os.remove(target_path)
        return False


def main():
    parser = argparse.ArgumentParser(description="NodeFlow LoRA 批量下载")
    parser.add_argument(
        "lora_ids",
        nargs="*",
        help="要下载的 LoRA ID（留空 = 下载全部）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印计划，不实际下载",
    )
    args = parser.parse_args()

    # 确定要下载的 LoRA 列表
    if args.lora_ids:
        download_list = [
            (lid, LORA_REGISTRY[lid])
            for lid in args.lora_ids
            if lid in LORA_REGISTRY
        ]
        missing = [lid for lid in args.lora_ids if lid not in LORA_REGISTRY]
        if missing:
            logger.warning(f"Unknown LoRA IDs: {missing}")
    else:
        download_list = [
            (lid, LORA_REGISTRY[lid])
            for lid in DOWNLOADABLE_LORA_IDS
        ]

    if not download_list:
        logger.info("No LoRA to download.")
        return

    logger.info(f"=== 计划下载 {len(download_list)} 个 LoRA ===")
    for lid, cfg in download_list:
        target = cfg["target_path"]
        exists = os.path.exists(target)
        size = os.path.getsize(target) / (1024 * 1024) if exists else 0
        status = f"({size:.1f} MB)" if exists else "(pending)"
        logger.info(f"  [{lid}] {cfg['name']:30s} {status}")

    if args.dry_run:
        logger.info("Dry-run mode, not downloading.")
        return

    # 开始下载
    success = 0
    failed = 0
    for lora_id, lora_cfg in download_list:
        if download_lora(lora_id, lora_cfg):
            success += 1
        else:
            failed += 1

    logger.info(
        f"=== 下载完成: {success} 成功, {failed} 失败 ==="
    )


if __name__ == "__main__":
    main()