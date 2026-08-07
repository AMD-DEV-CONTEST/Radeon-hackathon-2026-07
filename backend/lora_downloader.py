"""
NodeFlow — LoRA 批量下载脚本

从 config.LORA_REGISTRY 中读取所有 "已确认可下载" (download_url 非 None) 的 LoRA,
并用 store_service.download_model 逐个下载到本地。

用法:
    python lora_downloader.py                # 下载所有可下载 LoRA (跳过已存在)
    python lora_downloader.py --id sdxl_detail_tweaker
                                           # 只下载指定 LoRA
    python lora_downloader.py --force        # 强制重新下载 (覆盖已存在)
    python lora_downloader.py --list         # 列出所有 LoRA 及其可下载状态

说明:
    * 目标路径来自每个条目的 target_path (/persistent/loras/...)。
    * 已存在且文件大小 > 0 时默认跳过,用 --force 覆盖。
    * Civitai 链接需要 CIVITAI_API_TOKEN 环境变量;HF resolve 链接无需鉴权。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config import LORA_REGISTRY, DOWNLOADABLE_LORA_IDS
from store_service import store_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("lora_downloader")


def _list_loras() -> None:
    """打印所有 LoRA 及其可下载状态。"""
    print(f"{'ID':<28} {'架构':<10} {'类别':<18} {'可下载':<6} 名称")
    print("-" * 100)
    for lora_id, cfg in LORA_REGISTRY.items():
        downloadable = "是" if cfg.get("download_url") else "否"
        print(
            f"{lora_id:<28} {cfg.get('architecture','-'):<10} "
            f"{cfg.get('category','-'):<18} {downloadable:<6} {cfg.get('name','')}"
        )


async def _download_one(lora_id: str, force: bool) -> int:
    """下载单个 LoRA,返回 0=成功/跳过, 1=失败。"""
    cfg = LORA_REGISTRY.get(lora_id)
    if not cfg:
        logger.error("Unknown LoRA id: %s", lora_id)
        return 1

    url = cfg.get("download_url")
    if not url:
        logger.warning("LoRA '%s' has no download_url yet, skipping.", lora_id)
        return 0

    target = cfg.get("target_path")
    if not target:
        logger.error("LoRA '%s' has no target_path, skipping.", lora_id)
        return 1

    target_path = Path(target)
    if target_path.exists() and target_path.stat().st_size > 0 and not force:
        logger.info(
            "Skip '%s' (already exists at %s, %.1f MB). "
            "Use --force to re-download.",
            lora_id,
            target_path,
            target_path.stat().st_size / 1e6,
        )
        return 0

    try:
        result = await store_service.download_model(url=url, target_path=target)
        logger.info(
            "OK  '%s' -> %s (%.2f MB)", lora_id, result["path"], result["size_mb"]
        )
        return 0
    except Exception as exc:  # noqa: BLE001 — 下载脚本逐条兜底
        logger.error("FAIL '%s': %s", lora_id, exc)
        return 1


async def _run(ids: list[str], force: bool) -> int:
    """依次下载指定 ID 列表 (保持顺序,便于观察进度)。"""
    failures = 0
    for lora_id in ids:
        failures += await _download_one(lora_id, force)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="NodeFlow LoRA 批量下载")
    parser.add_argument(
        "--id",
        nargs="+",
        help="指定要下载的 LoRA ID (可多个);缺省下载全部可下载项。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载 (覆盖已存在文件)。",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有 LoRA 及其可下载状态后退出。",
    )
    args = parser.parse_args()

    if args.list:
        _list_loras()
        return 0

    if args.id:
        # 校验 ID 是否存在
        unknown = [i for i in args.id if i not in LORA_REGISTRY]
        if unknown:
            logger.error("Unknown LoRA ID(s): %s", ", ".join(unknown))
            print("可用 ID 见 --list 输出。")
            return 2
        ids = args.id
    else:
        ids = DOWNLOADABLE_LORA_IDS

    if not ids:
        logger.info("No downloadable LoRA entries. Nothing to do.")
        return 0

    logger.info("Will download %d LoRA(s): %s", len(ids), ", ".join(ids))
    failures = asyncio.run(_run(ids, args.force))
    logger.info(
        "Done. %d success, %d failed.",
        len(ids) - failures,
        failures,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())