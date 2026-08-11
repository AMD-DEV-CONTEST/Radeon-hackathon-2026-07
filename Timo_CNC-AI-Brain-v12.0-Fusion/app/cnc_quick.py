# -*- coding: utf-8 -*-
"""
CNC快速通道 API 增强模块
提供针对CNC高频场景的快速响应通道

新增功能:
1. /api/cnc-quick - 冲突检测+报价一体化快速通道
2. /api/cnc-intent - CNC意图识别（供MTClaw FR调用）
3. CNC关键词预过滤中间件

作者: timo.cao (基于 MTClaw + cnc-ai-brain 融合方案)
版本: v12.0-fusion
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 将 cnc-ai-brain 根目录加入 sys.path（模块级一次性处理，避免每请求重复 insert）
_CNC_BRAIN_ROOT = str(Path(__file__).resolve().parent.parent)
if _CNC_BRAIN_ROOT not in sys.path:
    sys.path.insert(0, _CNC_BRAIN_ROOT)

# 创建路由器
router = APIRouter(prefix="/api", tags=["CNC Quick"])

# CNC关键词库 - 用于快速意图识别
CNC_KEYWORDS = {
    "material": [
        "304", "316", "316L", "6061", "7075", "6063", "5052", "5083",
        "45钢", "Q235", "Q345", "40Cr", "20CrMnTi", "钛合金", "TC4",
        "黄铜", "紫铜", "青铜", "铝", "铝合金", "不锈钢", "合金钢",
        "AL6061", "AL7075", "SUS304", "SUS316", "45#钢"
    ],
    "surface_treatment": [
        "阳极氧化", "镀锌", "电镀", "钝化", "镀镍", "发黑", "喷砂",
        "阳极", "磷化", "氧化", "烤漆", "喷涂", "电泳",
        "anodize", "galvanize", "plating", "passivation"
    ],
    "tolerance": [
        "IT4", "IT5", "IT6", "IT7", "IT8", "IT9", "IT10", "IT11", "IT12",
        "公差", "精度", "精密", "粗糙度", "Ra1.6", "Ra3.2", "Ra0.8"
    ],
    "process": [
        "车削", "铣削", "磨削", "钻孔", "攻牙", "线切割", "电火花",
        "三轴", "五轴", "CNC", "数控", "加工中心", "车床", "铣床",
        "turning", "milling", "grinding", "edm", "wire_cut"
    ],
    "quote": [
        "报价", "价格", "多少钱", "成本", "费用", "询价", "估价",
        "quote", "price", "cost", "estimate", "budget"
    ],
    "conflict": [
        "能不能", "可否", "可行", "可以吗", "能做吗", "能不能做",
        "冲突", "禁忌", "限制", "能否加工", "能不能加工",
        "possible", "feasible", "can you make"
    ]
}

# CNC意图类型
CNC_INTENTS = {
    "conflict_check": "工艺冲突检测",
    "quote": "报价计算",
    "drawing": "3D建模/出图",
    "general": "一般咨询"
}


def detect_cnc_intent(message: str) -> Dict[str, Any]:
    """
    检测CNC相关意图 - 轻量级预过滤

    返回:
        {
            "intent": "conflict_check|quote|drawing|general",
            "confidence": 0.0-1.0,
            "keywords_matched": ["304", "阳极氧化"],
            "suggested_tool": "cnc_conflict_check|cnc_quote_calc|..."
        }
    """
    msg_lower = message.lower()
    matched_categories = {}

    # 关键词匹配（同义子串去重：如 铝/铝合金 同时命中时只保留更具体的，避免重复计分）
    for category, keywords in CNC_KEYWORDS.items():
        matched = [kw for kw in keywords if kw.lower() in msg_lower]
        matched = [
            kw for kw in matched
            if not any(other != kw and kw.lower() in other.lower() for other in matched)
        ]
        if matched:
            matched_categories[category] = matched

    # 意图推理
    intent = "general"
    confidence = 0.0
    suggested_tool = None

    # 冲突检测意图
    conflict_score = len(matched_categories.get("material", [])) + \
                     len(matched_categories.get("surface_treatment", [])) + \
                     len(matched_categories.get("process", []))

    has_conflict_verb = any(kw in msg_lower for kw in CNC_KEYWORDS["conflict"])
    has_quote_verb = any(kw in msg_lower for kw in CNC_KEYWORDS["quote"])

    if has_conflict_verb and conflict_score >= 2:
        intent = "conflict_check"
        confidence = min(0.6 + conflict_score * 0.1, 0.95)
        suggested_tool = "cnc_conflict_check"
    elif has_quote_verb and (conflict_score >= 1 or len(matched_categories) >= 2):
        intent = "quote"
        confidence = min(0.6 + len(matched_categories) * 0.1, 0.95)
        suggested_tool = "cnc_quote_calc"
    elif conflict_score >= 3:
        # 材料+工艺+表面处理都有，大概率是冲突检测或报价
        if has_conflict_verb:
            intent = "conflict_check"
            confidence = 0.85
            suggested_tool = "cnc_conflict_check"
        else:
            intent = "quote"
            confidence = 0.75
            suggested_tool = "cnc_quote_calc"

    # 提取所有匹配的关键词
    all_matched = []
    for keywords in matched_categories.values():
        all_matched.extend(keywords)

    return {
        "intent": intent,
        "confidence": confidence,
        "keywords_matched": all_matched,
        "suggested_tool": suggested_tool,
        "categories": list(matched_categories.keys())
    }


@router.post("/cnc-quick")
async def cnc_quick(request: Request):
    """
    CNC快速通道 - 一体化冲突检测+报价

    输入:
        {
            "message": "304不锈钢做阳极氧化可以吗？",
            "material": "304",  # 可选，从message提取
            "surface_treatment": "阳极氧化",  # 可选
            "quantity": 10,  # 可选
            "dimensions": {"length": 100, "width": 50, "height": 10}  # 可选
        }

    输出:
        {
            "intent": "conflict_check",
            "confidence": 0.85,
            "result": {
                "can_process": true/false,
                "conflicts": [...],
                "suggestions": [...]
            },
            "quote": {...},  # 如果有尺寸信息
            "latency_ms": 123
        }
    """
    start_time = time.time()

    try:
        raw_body = await request.body()
        body = json.loads(raw_body.decode("utf-8", errors="strict"))
    except Exception as e:
        return JSONResponse(
            content={"error": f"Invalid JSON: {str(e)}"},
            status_code=400
        )

    message = body.get("message", "").strip()
    if not message:
        return JSONResponse(
            content={"error": "message is required"},
            status_code=400
        )

    # Step 1: 意图识别
    intent_result = detect_cnc_intent(message)

    # Step 2: 执行对应的CNC工具
    result = {
        "intent": intent_result["intent"],
        "confidence": intent_result["confidence"],
        "message": message,
        "keywords_matched": intent_result["keywords_matched"]
    }

    try:
        if intent_result["intent"] == "conflict_check":
            # 调用冲突检测
            from src.neuro_core.conflict_check import ConflictChecker

            # 从body提取参数
            material = body.get("material") or extract_param_from_message(message, "material")
            surface_treatment = body.get("surface_treatment")
            tolerance = body.get("tolerance")
            process = body.get("process")
            wall_thickness = body.get("wall_thickness")

            if material:
                # 使用本地规则引擎（快速路径）
                checker = ConflictChecker(None)  # None = 不使用AI，只用规则
                # ConflictChecker.check 签名为 check(self, params: dict)
                check_result = checker.check({
                    "material": material,
                    "surface_treatment": surface_treatment,
                    "tolerance": tolerance,
                    "process": process,
                    "wall_thickness": wall_thickness
                })
                result["result"] = check_result
            else:
                result["result"] = {
                    "can_process": False,
                    "conflicts": ["缺少材料参数"],
                    "suggestions": ["请提供材料，如 304/6061/45钢/钛合金"]
                }

        elif intent_result["intent"] == "quote":
            # 调用报价计算
            from src.runtime.quote_adapter import QuoteAdapter

            quote_adapter = QuoteAdapter()
            material = body.get("material") or extract_param_from_message(message, "material")
            quantity = body.get("quantity") or 10
            # dimensions 键名归一：契约使用 length/width/height/thickness/diameter，
            # 报价引擎 quote_adapter.calc_weight_from_dimensions 只认 L/W/H/D/d/t。
            # 同时保留 None 防护（dimensions 缺失或为 None 时回退为空字典）。
            _KEYMAP = {"length": "L", "width": "W", "height": "H", "thickness": "H", "diameter": "D"}
            dimensions = {_KEYMAP.get(k, k): v for k, v in (body.get("dimensions") or {}).items() if v is not None}
            surface_treatment = body.get("surface_treatment")

            if material:
                # QuoteAdapter.quote 签名为 quote(self, params: dict)
                quote_result = quote_adapter.quote({
                    "material": material,
                    "quantity": quantity,
                    "dimensions": dimensions,
                    "surface_treatment": surface_treatment
                })
                result["quote"] = quote_result
            else:
                result["quote"] = {
                    "error": "缺少材料参数",
                    "example": "material='AL6061', dimensions={'length':100,'width':50,'height':10}"
                }

    except Exception as e:
        logger.exception("CNC快速通道执行失败: intent=%s, message=%r", intent_result["intent"], message)
        result["error"] = f"CNC工具执行失败: {str(e)}"
        result["suggestion"] = "请使用 /api/chat 完整路径"

    # 计算延迟
    latency_ms = int((time.time() - start_time) * 1000)
    result["latency_ms"] = latency_ms

    return JSONResponse(content=wrap_shadow(result))


@router.post("/cnc-intent")
async def cnc_intent(request: Request):
    """
    CNC意图识别API - 供MTClaw FR预过滤使用

    输入: {"message": "304不锈钢做阳极氧化可以吗？"}
    输出: {
        "intent": "conflict_check",
        "confidence": 0.85,
        "suggested_tool": "cnc_conflict_check",
        "keywords_matched": ["304", "不锈钢", "阳极氧化"]
    }
    """
    try:
        raw_body = await request.body()
        body = json.loads(raw_body.decode("utf-8", errors="strict"))
    except Exception as e:
        logger.warning("CNC意图识别请求体解析失败: %s", e)
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    message = body.get("message", "").strip()
    if not message:
        return JSONResponse(content={"error": "message is required"}, status_code=400)

    intent_result = detect_cnc_intent(message)
    return JSONResponse(content=intent_result)


def extract_param_from_message(message: str, param_type: str) -> Optional[str]:
    """从用户消息中提取参数（简化版）"""
    if param_type == "material":
        # 按关键词长度降序匹配，优先返回更具体的材料名（如 铝合金 优先于 铝）
        for mat in sorted(CNC_KEYWORDS["material"], key=len, reverse=True):
            if mat.lower() in message.lower():
                return mat
    elif param_type == "surface_treatment":
        for st in CNC_KEYWORDS["surface_treatment"]:
            if st in message:
                return st
    return None


def wrap_shadow(response: dict) -> dict:
    """添加免责声明（兼容cnc-ai-brain的Shadow Mode）"""
    import os
    shadow_mode = os.environ.get("SHADOW_MODE", "1") != "0"
    if shadow_mode:
        response["disclaimer"] = "此结论为AI建议，仅供参考。实际加工前请人工确认。"
        response["shadow_mode"] = True
    return response
