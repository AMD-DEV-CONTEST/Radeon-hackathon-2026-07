# -*- coding: utf-8 -*-
"""
tools/verify_tool.py — 官方发票真伪查验工具（外部辅助工具，非核心推理）

复用现有 app.py 的 verify_invoice 逻辑（多编码解码、verify=False），
将官方返回结构化为 official / field_match，供决策与解释使用。
"""

import json

import requests
import urllib3
from urllib.parse import urlencode
from langchain_core.tools import tool

import tools  # noqa: F401  注入 sys.path
import config as cfg

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _decode_response(raw: bytes):
    """按 config.VERIFY_ENCODINGS 顺序尝试解码并解析 JSON。"""
    for enc in cfg.VERIFY_ENCODINGS:
        try:
            return json.loads(raw.decode(enc))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def verify_invoice_core(fpdm: str, fphm: str, date: str, code: str) -> dict:
    """调用官方查验接口，返回结构化结果（对齐设计文档 5.2）。"""
    params = {"fpdm": fpdm or "", "fphm": fphm or "", "date": date or "",
              "code": code or "", "channel": cfg.VERIFY_CHANNEL}
    url = f"{cfg.VERIFY_URL}?{urlencode(params)}"

    try:
        resp = requests.get(url, timeout=cfg.VERIFY_TIMEOUT, verify=False)
        result = _decode_response(resp.content)
    except Exception as e:
        return {"verified": False, "code": "-1", "message": f"请求异常: {e}",
                "official": {}, "field_match": {}}

    if result is None:
        return {"verified": False, "code": "-1", "message": "无法解码响应",
                "official": {}, "field_match": {}}

    api_code = result.get("code")
    verified = api_code in (0, "0")
    if not verified:
        return {"verified": False, "code": str(api_code),
                "message": result.get("message", "未知错误"),
                "official": {}, "field_match": {}}

    data = result.get("data", {}) or {}
    fphm_api = data.get("fphm_dzfp", "")
    jshj_api = data.get("jshjxx_dzfp", "")
    kprq_api = data.get("kprq_dzfp", "")

    official = {
        "fphm": fphm_api,
        "jshj": jshj_api,
        "kprq": kprq_api,
        "xfmc": data.get("xfmc_dzfp", ""),
        "gfmc": data.get("gfmc_dzfp", ""),
        "je": data.get("je_dzfp", ""),
        "se": data.get("se_dzfp", ""),
    }
    field_match = {
        "fphm": bool(fphm_api) and fphm_api == fphm,
        "jshj": bool(jshj_api) and jshj_api == code,
    }
    return {
        "verified": True,
        "code": "0",
        "message": result.get("message", "获取成功"),
        "official": official,
        "field_match": field_match,
    }


@tool
def invoice_verify_tool(fpdm: str, fphm: str, date: str, code: str) -> dict:
    """调用官方发票查验接口核验发票真伪。入参为 OCR 识别得到的发票代码 fpdm、
    发票号码 fphm、开票日期 date(yyyyMMdd)、价税合计 code。返回 verified 是否查验通过、
    official 官方回填字段、field_match 关键字段是否与识别一致。"""
    return verify_invoice_core(fpdm, fphm, date, code)
