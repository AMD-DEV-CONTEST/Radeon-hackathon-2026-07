"""
NodeFlow — 自动补丁脚本: 让 LoRA 在所有模式可用

在实例上运行:
    source /persistent/venv/bin/activate
    cd /workspace/nodeflow/backend
    python patch_lora.py

然后重启后端即可。
"""

import re
from pathlib import Path

FILE = Path(__file__).resolve().parent / "main.py"
BACKUP = FILE.with_suffix(".py.bak")

# 读取原始内容
content = FILE.read_text("utf-8")

# 如果已经打过补丁,跳过
if "_apply_temporary_loras" in content:
    print("[SKIP] 补丁已应用,跳过。")
    exit(0)

# 备份原始文件
BACKUP.write_text(content, "utf-8")
print(f"[BACKUP] 已备份原始文件 -> {BACKUP}")

# ======================================================================
# Patch 1: 在 engine = FluxEngine() 后插入辅助函数
# ======================================================================
content = content.replace(
    "# 全局引擎实例 (单例门面,内部委托给 ModelManager)\nengine = FluxEngine()",
    "# 全局引擎实例 (单例门面,内部委托给 ModelManager)\nengine = FluxEngine()\n\n\n"
    "# ---------------------------------------------------------------------------\n"
    "# LoRA 临时加载/卸载辅助函数 (免模式限制)\n"
    "# ---------------------------------------------------------------------------\n\n\n"
    "def _apply_temporary_loras(\n"
    "    lora_paths: list[str],\n"
    "    weights: Optional[list[float]] = None,\n"
    ") -> list[str]:\n"
    '    """\n'
    "    在生成前加载临时 LoRA,返回 lora_id 列表。\n"
    "    生成结束后应调用 _cleanup_temporary_loras() 清理。\n"
    "    \"\"\"\n"
    "    loaded: list[str] = []\n"
    "    for i, path in enumerate(lora_paths):\n"
    "        w = weights[i] if weights and i < len(weights) else 0.8\n"
    "        try:\n"
    "            lid = engine.load_lora(path=path, weight=w)\n"
    "            loaded.append(lid)\n"
    '            logger.info("Temporary LoRA loaded: %s (weight=%.2f)", lid, w)\n'
    "        except Exception as e:\n"
    '            logger.warning("Failed to load temporary LoRA %s: %s", path, e)\n'
    "    return loaded\n\n\n"
    "def _cleanup_temporary_loras(lora_ids: list[str]) -> None:\n"
    '    """生成后清理临时 LoRA。"""\n'
    "    for lid in lora_ids:\n"
    "        try:\n"
    "            engine.unload_lora(lid)\n"
    '            logger.info("Temporary LoRA unloaded: %s", lid)\n'
    "        except Exception as e:\n"
    '            logger.warning("Failed to unload temporary LoRA %s: %s", lid, e)\n',
)

# ======================================================================
# Patch 2: TextToImageRequest 加 lora_weights 字段
# ======================================================================
content = content.replace(
    '    loras: Optional[list[str]] = Field(\n        default=None, description="LoRA 标识列表 (Expert 可选)"\n    )',
    '    loras: Optional[list[str]] = Field(\n        default=None, description="LoRA 文件路径列表 (所有模式均可用)"\n    )\n'
    '    lora_weights: Optional[list[float]] = Field(\n'
    '        default=None, description="LoRA 权重列表 (仅 Expert 模式生效;Fast 模式使用默认权重)"\n'
    "    )",
)

# ======================================================================
# Patch 3: generate_from_text — 移出 LoRA, 加临时加载
# ======================================================================

# 3a: 从 expert 块移除 loras
content = content.replace(
    "        if req.negative_prompt:\n            params[\"negative_prompt\"] = req.negative_prompt\n        if req.loras:\n            params[\"loras\"] = req.loras",
    "        if req.negative_prompt:\n            params[\"negative_prompt\"] = req.negative_prompt",
)

# 3b: fast 块 ignored 里 loras -> lora_weights
content = content.replace(
    "        if req.negative_prompt:\n            ignored.append(\"negative_prompt\")\n        if req.loras:\n            ignored.append(\"loras\")",
    "        if req.negative_prompt:\n            ignored.append(\"negative_prompt\")\n        if req.lora_weights:\n            ignored.append(\"lora_weights\")",
)

# 3c: 在 warnings.append 之后、logger.info 之前插入 LoRA 临时加载
content = content.replace(
    '            warnings.append(\n                f"Expert parameters ({", ".join(ignored)}) are ignored in fast mode"\n            )\n\n    logger.info(\n        "text2img:',
    '            warnings.append(\n                f"Expert parameters ({", ".join(ignored)}) are ignored in fast mode"\n            )\n\n    # LoRA 全局可用 (不限模式);权重仅在 expert 模式自定义\n'
    "    temp_loras: list[str] = []\n"
    "    if req.loras:\n"
    "        lora_weights = req.lora_weights if req.mode == \"expert\" else None\n"
    "        temp_loras = _apply_temporary_loras(req.loras, lora_weights)\n\n"
    "    logger.info(\n        \"text2img:",
)

# 3d: 在 except ValueError 和 except Exception 中加 cleanup
content = content.replace(
    "    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc))\n    except Exception as exc:  # noqa: BLE001\n        logger.error(\"text2img failed: %s\", exc, exc_info=True)\n        raise HTTPException(status_code=500, detail=f\"Generation failed: {exc}\")\n    elapsed = time.time() - start_ts",
    "    except ValueError as exc:\n        _cleanup_temporary_loras(temp_loras)\n        raise HTTPException(status_code=400, detail=str(exc))\n"
    "    except Exception as exc:  # noqa: BLE001\n        logger.error(\"text2img failed: %s\", exc, exc_info=True)\n"
    "        _cleanup_temporary_loras(temp_loras)\n"
    '        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")\n'
    "    # 生成成功后清理临时 LoRA\n"
    "    _cleanup_temporary_loras(temp_loras)\n"
    "    elapsed = time.time() - start_ts",
)

# ======================================================================
# Patch 4: generate_from_image — 同样改造
# ======================================================================

# 4a: 加 lora_weights Form 参数
content = content.replace(
    "    loras: Optional[list[str]] = Form(None),\n) -> JSONResponse:\n",
    "    loras: Optional[list[str]] = Form(None),\n    lora_weights: Optional[str] = Form(None),\n) -> JSONResponse:\n",
)

# 4b: 更新 docstring
content = content.replace(
    "    快速版 (fast): 少步模型,忽略 expert 字段。\n    专家版 (expert): 可自定义步数/引导/种子/负向提示/LoRA。\n    \"\"\"",
    "    快速版 (fast): 少步模型,忽略 expert 字段。\n    专家版 (expert): 可自定义步数/引导/种子/负向提示/LoRA。\n    LoRA 在所有模式均可用,权重仅在 expert 模式自定义。\n    \"\"\"",
)

# 4c: 从 expert 块移除 loras
content = content.replace(
    "        if negative_prompt:\n            params[\"negative_prompt\"] = negative_prompt\n        if loras:\n            params[\"loras\"] = loras\n    else:\n        ignored:",
    "        if negative_prompt:\n            params[\"negative_prompt\"] = negative_prompt\n    else:\n        ignored:",
)

# 4d: fast 块 ignored 里 loras -> lora_weights
content = content.replace(
    "        if negative_prompt:\n            ignored.append(\"negative_prompt\")\n        if loras:\n            ignored.append(\"loras\")\n        if ignored:\n            warnings.append(\n                f\"Expert parameters ({', '.join(ignored)}) are ignored in fast mode\"\n            )\n\n    logger.info(\n        \"img2img:",
    "        if negative_prompt:\n            ignored.append(\"negative_prompt\")\n        if lora_weights:\n            ignored.append(\"lora_weights\")\n"
    "        if ignored:\n            warnings.append(\n                f\"Expert parameters ({', '.join(ignored)}) are ignored in fast mode\"\n"
    "            )\n\n"
    "    # 6) LoRA 全局可用 (不限模式)\n"
    "    temp_loras: list[str] = []\n"
    "    if loras:\n"
    "        parsed_weights: Optional[list[float]] = None\n"
    '        if mode == "expert" and lora_weights:\n'
    "            try:\n"
    '                parsed_weights = [float(w.strip()) for w in lora_weights.split(",")]\n'
    "            except (ValueError, TypeError):\n"
    '                warnings.append("lora_weights 解析失败,使用默认权重 0.8")\n'
    "        temp_loras = _apply_temporary_loras(loras, parsed_weights)\n\n"
    "    logger.info(\n        \"img2img:",
)

# 4e: img2img try/except 加 cleanup
content = content.replace(
    "    except ValueError as exc:\n        raise HTTPException(status_code=400, detail=str(exc))\n    except Exception as exc:  # noqa: BLE001\n        logger.error(\"img2img failed: %s\", exc, exc_info=True)\n        raise HTTPException(status_code=500, detail=f\"Generation failed: {exc}\")\n    elapsed = time.time() - start_ts",
    "    except ValueError as exc:\n        _cleanup_temporary_loras(temp_loras)\n        raise HTTPException(status_code=400, detail=str(exc))\n"
    "    except Exception as exc:  # noqa: BLE001\n        logger.error(\"img2img failed: %s\", exc, exc_info=True)\n"
    "        _cleanup_temporary_loras(temp_loras)\n"
    '        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")\n'
    "    # 生成成功后清理临时 LoRA\n"
    "    _cleanup_temporary_loras(temp_loras)\n"
    "    elapsed = time.time() - start_ts",
)

# ======================================================================
# 写入
# ======================================================================
FILE.write_text(content, "utf-8")
print(f"[DONE] 补丁应用完成,已更新 -> {FILE}")
print("请重启后端生效: kill <PID> && uvicorn main:app --host 0.0.0.0 --port 8000")