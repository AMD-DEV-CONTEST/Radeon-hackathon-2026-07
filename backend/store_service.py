"""
NodeFlow — 模型商店服务

聚合 HuggingFace Hub 与 Civitai 两个来源,提供:
    * 热门 Checkpoint 模型浏览 (text-to-image / Checkpoint)
    * 热门 LoRA 浏览 (按 baseModel 过滤)
    * 异步下载 (带进度日志 + 大小校验)
    * 本地 JSON 缓存 (API 不可用时降级返回缓存)

设计要点:
    * 全部使用 ``httpx`` 异步客户端,与 FastAPI 事件循环兼容。
    * Civitai 需要 ``Authorization: Bearer {CIVITAI_API_TOKEN}`` 从环境变量读取。
    * 缓存目录默认 ``/persistent/store_cache/`` (持久化卷)。
    * 任何远端异常都被捕获,转而返回缓存数据 + 警告,不抛 500。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger("store_service")

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
CIVITAI_API_TOKEN: str = os.getenv("CIVITAI_API_TOKEN", "")
CIVITAI_BASE: str = "https://civitai.com/api/v1"
HF_BASE: str = "https://huggingface.co/api"

CACHE_DIR: Path = Path("/persistent/store_cache")
CACHE_TTL_SEC: int = 3600  # 缓存有效期 (秒),仅用于 get_cached_trending 的年龄展示

# HTTP 超时 (秒):列表请求快速失败,下载请求单独放宽
LIST_TIMEOUT_SEC: float = 30.0
DOWNLOAD_TIMEOUT_SEC: float = 600.0
DOWNLOAD_CHUNK_BYTES: int = 1024 * 1024  # 1 MiB

# ---------------------------------------------------------------------------
# 许可证 → 商用许可映射
# key 统一小写;value 中 commercial_use:
#   True  = 允许商用
#   False = 禁止商用
#   "conditional" = 有附加条件 (如 OpenRAIL 的使用政策)
#   "unknown"     = 未知 / 需人工确认
# ---------------------------------------------------------------------------
LICENSE_INFO: dict[str, dict[str, Any]] = {
    "mit": {"name": "MIT", "commercial_use": True},
    "apache-2.0": {"name": "Apache 2.0", "commercial_use": True},
    "bsd-3-clause": {"name": "BSD 3-Clause", "commercial_use": True},
    "bsd-2-clause": {"name": "BSD 2-Clause", "commercial_use": True},
    "mpl-2.0": {"name": "MPL 2.0", "commercial_use": True},
    "openrail": {"name": "OpenRAIL", "commercial_use": "conditional"},
    "openrail++": {"name": "OpenRAIL++", "commercial_use": "conditional"},
    "openrail-m": {"name": "OpenRAIL-M", "commercial_use": "conditional"},
    "bigscience-openrail-m": {"name": "BigScience OpenRAIL-M", "commercial_use": "conditional"},
    "creativeml-openrail-m": {"name": "CreativeML OpenRAIL-M", "commercial_use": "conditional"},
    "cc-by-4.0": {"name": "CC BY 4.0", "commercial_use": True},
    "cc-by-3.0": {"name": "CC BY 3.0", "commercial_use": True},
    "cc-by-sa-4.0": {"name": "CC BY-SA 4.0", "commercial_use": True},
    "cc-by-sa-3.0": {"name": "CC BY-SA 3.0", "commercial_use": True},
    "cc-by-nc-4.0": {"name": "CC BY-NC 4.0", "commercial_use": False},
    "cc-by-nc-3.0": {"name": "CC BY-NC 3.0", "commercial_use": False},
    "cc-by-nc-sa-4.0": {"name": "CC BY-NC-SA 4.0", "commercial_use": False},
    "cc0-1.0": {"name": "CC0 1.0", "commercial_use": True},
    "gpl-3.0": {"name": "GPL 3.0", "commercial_use": True},
    "lgpl-3.0": {"name": "LGPL 3.0", "commercial_use": True},
    "other": {"name": "Other", "commercial_use": "unknown"},
    "unknown": {"name": "Unknown", "commercial_use": "unknown"},
}


class StoreService:
    """
    模型商店服务 (单例语义由调用方维持;本身无状态,可重复实例化)。

    所有公开方法均为 ``async``,适合在 FastAPI 路由中直接 ``await``。
    """

    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        """
        Args:
            cache_dir: 本地缓存目录,不存在则自动创建。
        """
        self.cache_dir: Path = Path(cache_dir)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # 缓存目录不可用不应阻断服务,后续读写会各自兜底
            logger.warning("Cannot create cache dir %s: %s", self.cache_dir, exc)

    # ==================================================================
    # 公开 API
    # ==================================================================
    async def get_trending_models(
        self, source: str = "hf", limit: int = 20
    ) -> dict[str, Any]:
        """
        获取热门 Checkpoint 模型列表。

        Args:
            source: ``"hf"`` (HuggingFace) 或 ``"civitai"``。
            limit: 返回条数上限。

        Returns:
            dict::
                {
                  "status": "ok" | "degraded" | "error",
                  "source": str,
                  "count": int,
                  "models": list[dict],
                  "cached": bool,        # degraded 时为 True
                  "warning": str | None  # degraded / error 时的说明
                }
        """
        limit = max(1, min(int(limit), 100))
        cache_key = f"trending_models_{source}"

        try:
            if source == "hf":
                models = await self._fetch_hf_models(limit)
            elif source == "civitai":
                models = await self._fetch_civitai_models(
                    types="Checkpoint", limit=limit
                )
            else:
                return {
                    "status": "error",
                    "source": source,
                    "count": 0,
                    "models": [],
                    "cached": False,
                    "warning": f"Unknown source: {source!r} (use 'hf' or 'civitai')",
                }

            self._write_cache(cache_key, models)
            return {
                "status": "ok",
                "source": source,
                "count": len(models),
                "models": models,
                "cached": False,
                "warning": None,
            }
        except Exception as exc:  # noqa: BLE001 — 顶层兜底,降级到缓存
            logger.warning("get_trending_models(%s) failed: %s", source, exc)
            cached = self._read_cache(cache_key)
            return {
                "status": "degraded" if cached else "error",
                "source": source,
                "count": len(cached),
                "models": cached,
                "cached": bool(cached),
                "warning": f"Remote API unavailable, returning cached data. ({exc})",
            }

    async def get_trending_loras(
        self,
        source: str = "civitai",
        base_model: str = "SDXL 1.0",
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        获取热门 LoRA 列表。

        Args:
            source: 目前仅支持 ``"civitai"``。
            base_model: 基础模型过滤 (如 ``"SDXL 1.0"`` / ``"SD 1.5"``)。
            limit: 返回条数上限。

        Returns:
            同 :meth:`get_trending_models` 结构,字段名为 ``loras``。
        """
        limit = max(1, min(int(limit), 100))
        cache_key = f"trending_loras_{source}_{base_model.replace(' ', '_')}"

        try:
            if source != "civitai":
                return {
                    "status": "error",
                    "source": source,
                    "count": 0,
                    "loras": [],
                    "cached": False,
                    "warning": f"LoRA source not supported: {source!r} (only 'civitai')",
                }

            loras = await self._fetch_civitai_models(
                types="LORA", limit=limit, base_model=base_model
            )
            self._write_cache(cache_key, loras)
            return {
                "status": "ok",
                "source": source,
                "base_model": base_model,
                "count": len(loras),
                "loras": loras,
                "cached": False,
                "warning": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_trending_loras(%s) failed: %s", source, exc)
            cached = self._read_cache(cache_key)
            return {
                "status": "degraded" if cached else "error",
                "source": source,
                "base_model": base_model,
                "count": len(cached),
                "loras": cached,
                "cached": bool(cached),
                "warning": f"Remote API unavailable, returning cached data. ({exc})",
            }

    async def download_model(self, url: str, target_path: str) -> dict[str, Any]:
        """
        异步下载模型 / LoRA 文件到本地,带进度日志与大小校验。

        Civitai 下载链接会自动附加 API Token 鉴权。

        Args:
            url: 文件直链 (HF resolve URL 或 Civitai downloadUrl)。
            target_path: 本地保存路径 (父目录会自动创建)。

        Returns:
            dict::
                {
                  "status": "ok",
                  "path": str,
                  "size_bytes": int,
                  "size_mb": float,
                  "url": str
                }

        Raises:
            httpx.HTTPStatusError: 远端返回非 2xx。
            IOError: 下载完成后大小与 Content-Length 不一致。
        """
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        headers: dict[str, str] = {}
        if "civitai.com" in url and CIVITAI_API_TOKEN:
            headers["Authorization"] = f"Bearer {CIVITAI_API_TOKEN}"

        logger.info("Downloading %s -> %s", url, target)
        downloaded = 0
        total = 0
        last_log_pct = -10  # 每 10% 打印一次

        timeout = httpx.Timeout(DOWNLOAD_TIMEOUT_SEC, connect=LIST_TIMEOUT_SEC)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", "0") or 0)

                with open(target, "wb") as fh:
                    async for chunk in resp.aiter_bytes(
                        chunk_size=DOWNLOAD_CHUNK_BYTES
                    ):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int(downloaded * 100 / total)
                            if pct >= last_log_pct + 10:
                                last_log_pct = pct - (pct % 10)
                                logger.info(
                                    "Downloaded %s/%s bytes (%d%%)",
                                    downloaded,
                                    total,
                                    pct,
                                )
                        else:
                            # 未知总大小时每 50 MiB 打印一次
                            if downloaded % (50 * DOWNLOAD_CHUNK_BYTES) == 0:
                                logger.info(
                                    "Downloaded %s bytes (total unknown)", downloaded
                                )

        actual_size = target.stat().st_size
        if total and actual_size != total:
            # 大小不一致视为损坏,清理并报错
            try:
                target.unlink()
            except OSError:
                pass
            raise IOError(
                f"Download size mismatch: expected {total} bytes, got {actual_size} bytes"
            )

        logger.info(
            "Download complete: %s (%.2f MB)", target, actual_size / 1e6
        )
        return {
            "status": "ok",
            "path": str(target),
            "size_bytes": actual_size,
            "size_mb": round(actual_size / 1e6, 2),
            "url": url,
        }

    async def get_cached_trending(self) -> dict[str, Any]:
        """
        读取本地缓存的概览 (不发起网络请求)。

        Returns:
            dict::{cache_key: {"timestamp": float, "age_sec": float, "count": int}}
            若无缓存则返回空 dict。
        """
        result: dict[str, Any] = {}
        if not self.cache_dir.exists():
            return result

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Skip unreadable cache %s: %s", cache_file, exc)
                continue

            ts = float(payload.get("timestamp", 0.0) or 0.0)
            data = payload.get("data", [])
            result[cache_file.stem] = {
                "timestamp": ts,
                "age_sec": round(time.time() - ts, 1) if ts else None,
                "count": len(data) if isinstance(data, list) else 0,
                "expired": (time.time() - ts) > CACHE_TTL_SEC if ts else True,
            }
        return result

    # ==================================================================
    # 内部:远端抓取
    # ==================================================================
    async def _fetch_hf_models(self, limit: int) -> list[dict[str, Any]]:
        """
        从 HuggingFace 抓取热门 text-to-image 模型。

        GET {HF_BASE}/models?sort=trendingScore&direction=-1
            &filter=text-to-image&limit={limit}
        """
        params = {
            "sort": "trendingScore",
            "direction": -1,
            "filter": "text-to-image",
            "limit": limit,
        }
        async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SEC) as client:
            resp = await client.get(f"{HF_BASE}/models", params=params)
            resp.raise_for_status()
            items = resp.json()

        if not isinstance(items, list):
            return []

        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            tags = item.get("tags", []) or []
            license_str = self._parse_license(tags)
            model_id = item.get("id", "")
            results.append(
                {
                    "id": model_id,
                    "source": "hf",
                    "downloads": item.get("downloads", 0),
                    "likes": item.get("likes", 0),
                    "trendingScore": item.get("trendingScore", 0.0),
                    "license": license_str,
                    "license_name": LICENSE_INFO.get(license_str, {}).get(
                        "name", license_str
                    ),
                    "commercial_use": self._get_commercial_use(license_str),
                    "download_url": f"https://huggingface.co/{model_id}",
                    "tags": tags,
                }
            )
        return results

    async def _fetch_civitai_models(
        self,
        types: str,
        limit: int,
        base_model: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        从 Civitai 抓取模型 / LoRA。

        GET {CIVITAI_BASE}/models?types={types}
            [&baseModels={base_model}]&sort=Highest Rated&limit={limit}

        Args:
            types: ``"Checkpoint"`` 或 ``"LORA"``。
            limit: 条数。
            base_model: 可选基础模型过滤。
        """
        params: dict[str, Any] = {
            "types": types,
            "sort": "Highest Rated",
            "limit": limit,
        }
        if base_model:
            params["baseModels"] = base_model

        headers: dict[str, str] = {}
        if CIVITAI_API_TOKEN:
            headers["Authorization"] = f"Bearer {CIVITAI_API_TOKEN}"
        else:
            logger.warning(
                "CIVITAI_API_TOKEN not set — Civitai may rate-limit or reject requests."
            )

        async with httpx.AsyncClient(timeout=LIST_TIMEOUT_SEC) as client:
            resp = await client.get(
                f"{CIVITAI_BASE}/models", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", []) if isinstance(data, dict) else []
        results: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            versions = item.get("modelVersions", []) or []
            version = versions[0] if versions else {}
            license_str = (item.get("license") or "unknown").lower()

            entry: dict[str, Any] = {
                "id": item.get("id"),
                "source": "civitai",
                "name": item.get("name", ""),
                "type": item.get("type", types),
                "downloadUrl": version.get("downloadUrl", ""),
                "nsfw": bool(item.get("nsfw", False)),
                "license": license_str,
                "license_name": LICENSE_INFO.get(license_str, {}).get(
                    "name", license_str
                ),
                "commercial_use": self._get_commercial_use(license_str),
                "baseModel": version.get("baseModel", ""),
                "stats": item.get("stats", {}),
            }
            results.append(entry)
        return results

    # ==================================================================
    # 内部:许可证解析 + 缓存读写
    # ==================================================================
    def _parse_license(self, tags: Any) -> str:
        """
        从 HuggingFace tags 中解析 license。

        HF tags 形如 ``["license:mit", "license:apache-2.0", ...]``。

        Args:
            tags: tag 列表。

        Returns:
            归一化小写的 license 标识;未找到返回 ``"unknown"``。
        """
        if not tags:
            return "unknown"
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("license:"):
                return tag.split(":", 1)[1].strip().lower()
        return "unknown"

    def _get_commercial_use(self, license_str: Optional[str]) -> Any:
        """
        根据 license 字符串查询是否可商用。

        支持精确匹配与包含式回退 (如 ``"cc-by-nc-sa-4.0"`` 命中 ``cc-by-nc-sa-4.0``)。

        Returns:
            ``True`` / ``False`` / ``"conditional"`` / ``"unknown"``。
        """
        key = (license_str or "unknown").strip().lower()
        if not key:
            return "unknown"

        if key in LICENSE_INFO:
            return LICENSE_INFO[key]["commercial_use"]

        # 包含式回退
        for known, info in LICENSE_INFO.items():
            if known in key or key in known:
                return info["commercial_use"]
        return "unknown"

    def _cache_path(self, key: str) -> Path:
        """根据 cache key 得到缓存文件路径。"""
        return self.cache_dir / f"{key}.json"

    def _write_cache(self, key: str, data: Any) -> None:
        """写入缓存 (失败仅记录日志,不抛异常)。"""
        try:
            payload = {"timestamp": time.time(), "data": data}
            self._cache_path(key).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("Failed to write cache %s: %s", key, exc)

    def _read_cache(self, key: str) -> list[dict[str, Any]]:
        """读取缓存数据部分 (失败返回空列表)。"""
        try:
            payload = json.loads(self._cache_path(key).read_text(encoding="utf-8"))
            data = payload.get("data", [])
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []


# 模块级单例,供 main.py 直接 import 使用
store_service: StoreService = StoreService()
