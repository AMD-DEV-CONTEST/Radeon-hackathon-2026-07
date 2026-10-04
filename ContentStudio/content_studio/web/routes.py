"""FastAPI 路由。"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from io import BytesIO
from pathlib import Path

import asyncio
import base64
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

from content_studio.config import get_active_provider, load_config, save_config
from content_studio.core.comfy import ComfyClient
from content_studio.core.generator import Generator, build_material
from content_studio.core.models import LLMClient
from content_studio.core.pipeline import run_pipeline, weave_images
from content_studio.publish.wechat import WeChatPublisher
from content_studio.styles.registry import list_presets, preset_options, resolve_style
from content_studio.web import jobs

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"options": preset_options()})


@router.get("/demo", response_class=HTMLResponse)
def demo(request: Request):
    return templates.TemplateResponse(request, "demo.html", {})


@router.get("/check", response_class=HTMLResponse)
def check_page(request: Request):
    return templates.TemplateResponse(request, "check.html", {})


@router.get("/api/check")
async def api_check():
    """一键体检：检查 LLM / ComfyUI / 公众号 三项连通性。"""
    import httpx
    cfg = load_config()
    results = {}

    # 1) LLM
    try:
        p = get_active_provider(cfg)
        client = LLMClient(p, client=__import__("openai").OpenAI(base_url=p.base_url, api_key=p.api_key or "x", timeout=15))
        ok = bool(p.api_key)
        if ok:
            try:
                # 简单发一条，看能不能回
                resp = client._one_call("你是测试助手", "回复一个字：好")
                text = resp.choices[0].message.content.strip()
                results["llm"] = {"ok": True, "detail": f"{p.name} / {p.model} → {text[:20]}"}
            except Exception as e:
                msg = str(e)[:120]
                if any(k in msg.lower() for k in ["401","authentication","invalid api key","unauthorized"]):
                    results["llm"] = {"ok": False, "detail": "API Key 无效或未填"}
                elif any(k in msg.lower() for k in ["timeout","timed out"]):
                    results["llm"] = {"ok": False, "detail": "请求超时（接口慢或不可达）"}
                elif any(k in msg.lower() for k in ["connect","connection","拒绝"]):
                    results["llm"] = {"ok": False, "detail": "连不上（检查网络/base_url）"}
                else:
                    results["llm"] = {"ok": False, "detail": msg[:80]}
        else:
            results["llm"] = {"ok": False, "detail": f"{p.name} 未填 API Key"}
    except Exception as e:
        results["llm"] = {"ok": False, "detail": str(e)[:80]}

    # 2) ComfyUI
    if not cfg.comfy.enabled:
        results["comfy"] = {"ok": None, "detail": "未启用（选「无」风格时不影响）"}
    else:
        try:
            r = httpx.get(f"{cfg.comfy.base_url.rstrip('/')}/system_stats", timeout=5)
            data = r.json()
            devs = data.get("devices", [])
            if devs:
                d = devs[0]
                vram = round(d.get("vram_total", 0) / 1048576)
                results["comfy"] = {"ok": True, "detail": f"{d.get('name','?')} · {vram}MB VRAM"}
            else:
                results["comfy"] = {"ok": True, "detail": "已连接（未检测到 GPU 设备）"}
        except Exception:
            results["comfy"] = {"ok": False, "detail": f"连不上 {cfg.comfy.base_url}（未启动？）"}

    # 3) 公众号
    if not cfg.wechat.app_id or not cfg.wechat.app_secret:
        results["wechat"] = {"ok": None, "detail": "未配置（不影响预览/导出，只有发草稿箱需要）"}
    else:
        try:
            pub = WeChatPublisher(cfg.wechat.app_id, cfg.wechat.app_secret, http=httpx.Client(timeout=10))
            pub.get_access_token()
            results["wechat"] = {"ok": True, "detail": "Token 获取成功，可发草稿箱"}
        except Exception as e:
            msg = str(e)[:100]
            if "401" in msg or "4013" in msg or "invalid" in msg.lower():
                results["wechat"] = {"ok": False, "detail": "AppID/AppSecret 无效"}
            else:
                results["wechat"] = {"ok": False, "detail": msg[:80]}

    return results


@router.get("/gpu_info")
def gpu_info():
    """查 ComfyUI 的 GPU 信息（证明 AMD GPU 在跑）。"""
    cfg = load_config()
    if not cfg.comfy.enabled:
        return {"connected": False, "devices": []}
    try:
        import httpx
        r = httpx.get(f"{cfg.comfy.base_url.rstrip('/')}/system_stats", timeout=5)
        data = r.json()
        return {
            "connected": True,
            "devices": [
                {"name": d.get("name", "?"),
                 "vram_total_mb": round(d.get("vram_total", 0) / 1048576),
                 "vram_free_mb": round(d.get("vram_free", 0) / 1048576)}
                for d in data.get("devices", [])
            ]
        }
    except Exception:
        return {"connected": False, "devices": []}


@router.get("/styles")
def styles():
    return [{"id": p.id, "name": p.name} for p in list_presets()]


@router.get("/api/config")
def api_config():
    cfg = load_config()
    return {
        "active_provider": cfg.active_provider,
        "providers": [{"name": p.name, "base_url": p.base_url, "api_key": p.api_key, "model": p.model} for p in cfg.providers],
        "comfy_url": cfg.comfy.base_url,
        "app_id": cfg.wechat.app_id,
        "app_secret": cfg.wechat.app_secret,
    }


UPLOAD_DIR = Path(tempfile.gettempdir()) / "content_studio_uploads"


def _save_upload(data: bytes, suffix: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=suffix, dir=str(UPLOAD_DIR))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return name


def _to_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _build_services(cfg):
    generator = Generator(LLMClient(get_active_provider(cfg)))
    comfy = ComfyClient(cfg.comfy.base_url, timeout=cfg.comfy.timeout) if cfg.comfy.enabled else None
    return generator, comfy


def _friendly_error(e: Exception) -> str:
    """把底层异常翻成用户能看懂的提示。"""
    m = str(e)
    low = m.lower()
    if any(k in low for k in ["401", "authentication", "invalid api key", "unauthorized", "未授权"]):
        return "API Key 无效或未填——去「设置」检查当前 provider 的 key"
    if any(k in low for k in ["400", "badrequest", "invalid_request"]):
        return "请求被服务拒绝（多半是模型名或参数不对）——去「设置」核对模型名"
    if any(k in low for k in ["timeout", "timed out", "超时"]):
        return "请求超时（服务慢或图太大），重试或换模型"
    if any(k in low for k in ["connect", "connection", "winerror 10061", "拒绝", "unreachable", "name resolution"]):
        return "连不上服务（检查网络 / base_url / 服务是否启动）"
    if "ascii" in low and "encode" in low:
        return "API Key 含非英文字符——重新复制纯英文 key 再填"
    return m


def _result_dict(res, inputs=None):
    d = {
        "target": res.target,
        "wechat": {
            "title": res.wechat.title, "summary": res.wechat.summary,
            "body_html": res.wechat.body_html, "image_captions": res.wechat.image_captions,
            "images": [_to_jpeg(im) for im in res.wechat.images],
            "cover": _to_jpeg(res.wechat.cover) if res.wechat.cover else None,
        } if res.target == "wechat" else None,
        "xhs": {
            "title": res.xhs.title, "body": res.xhs.body, "hashtags": res.xhs.hashtags,
            "cover_text": res.xhs.cover_text, "images": [_to_jpeg(im) for im in res.xhs.images],
        } if res.target == "xhs" else None,
        "used_comfyui": res.used_comfyui, "warnings": res.warnings, "timings": res.timings,
    }
    if inputs is not None:
        d["inputs"] = inputs
    return d


@router.post("/generate")
async def generate(
    theme: str = Form(...),
    text: str = Form(""),
    styles: list[str] | None = Form(default=None),
    target: str = Form("wechat"),
    template: str = Form(""),
    t2i_count: int = Form(0),
    t2i_prompt: str = Form(""),
    ocr: bool = Form(False),
    images: list[UploadFile] | None = File(default=None),
):
    if not images:
        raise HTTPException(400, "请至少上传一张照片")
    cfg = load_config()
    style_ids = styles or []
    try:
        style_objs = [resolve_style(s) for s in style_ids]
    except ValueError as e:
        raise HTTPException(400, str(e))
    saved: list[str] = []
    ocr_text = ""
    for up in images:
        data = await up.read()
        suffix = Path(up.filename or "img.png").suffix or ".png"
        saved.append(_save_upload(data, suffix))
    if ocr and saved:
        from content_studio.core import ocr as ocr_mod
        ocr_text = ocr_mod.extract_text(saved)
    material = build_material((theme + "\n" + text).strip(), ocr_text=ocr_text, image_count=len(saved))
    _TPL = {
        "review": "[文章类型：产品评测，结构=产品概述→核心亮点→使用体验→总结推荐]",
        "event": "[文章类型：活动宣传，结构=活动亮点→时间地点→参与方式→期待拉满]",
        "tutorial": "[文章类型：教程攻略，结构=前言→分步骤详解(每步配图)→常见问题→总结]",
        "analysis": "[文章类型：行业分析，结构=背景→数据现象→分析解读→趋势预测]",
    }
    if template and template in _TPL:
        material = _TPL[template] + "\n\n" + material

    job = jobs.create_job()

    def worker():
        try:
            generator, comfy = _build_services(cfg)

            def progress(stage, p):
                jobs.update_job(job.id, stage=stage, progress=p)

            res = run_pipeline(material, saved, style_objs, cfg, generator, comfy, target, t2i_count, t2i_prompt, progress)
            jobs.update_job(
                job.id, stage="done", progress=1.0,
                result=_result_dict(res, {
                    "material": material, "image_paths": saved,
                    "styles": [s.id if s else "none" for s in style_objs], "target": target,
                    "t2i_count": t2i_count, "t2i_prompt": t2i_prompt,
                }),
            )
        except Exception as e:
            import traceback
            from pathlib import Path as _P
            try:
                logf = _P.home() / ".content_studio" / "generate_error.log"
                logf.parent.mkdir(parents=True, exist_ok=True)
                logf.write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            jobs.update_job(job.id, stage="error", error=_friendly_error(e))

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job.id}


@router.post("/job/{jid}/regenerate")
def regenerate(jid: str):
    """用同一组输入重新生成一篇（模型有随机性，每次不同）。"""
    j = jobs.get_job(jid)
    if j is None or not j.result or "inputs" not in j.result:
        raise HTTPException(404, "找不到原始输入，无法重新生成")
    inp = j.result["inputs"]
    material = inp["material"]
    image_paths = inp["image_paths"]
    target = inp["target"]
    style_objs = [resolve_style(s) for s in inp["styles"]]

    new_job = jobs.create_job()

    def worker():
        try:
            cfg = load_config()
            generator, comfy = _build_services(cfg)

            def progress(stage, p):
                jobs.update_job(new_job.id, stage=stage, progress=p)

            res = run_pipeline(material, image_paths, style_objs, cfg, generator, comfy, target, inp.get("t2i_count", 0), inp.get("t2i_prompt", ""), progress)
            jobs.update_job(new_job.id, stage="done", progress=1.0, result=_result_dict(res, inp))
        except Exception as e:
            jobs.update_job(new_job.id, stage="error", error=_friendly_error(e))

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": new_job.id}


@router.get("/job/{jid}")
def job_status(jid: str):
    j = jobs.get_job(jid)
    if j is None:
        raise HTTPException(404)
    return {"stage": j.stage, "progress": j.progress, "error": j.error}


@router.get("/job/{jid}/stream")
async def stream_job(jid: str):
    """SSE：实时推送任务进度，直到 done/error。"""
    async def gen():
        while True:
            j = jobs.get_job(jid)
            if j is None:
                yield 'data: {"stage":"error","error":"任务不存在"}\n\n'
                return
            payload = {"stage": j.stage, "progress": j.progress, "error": j.error}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if j.stage in ("done", "error"):
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.delete("/job/{jid}")
def delete_job_route(jid: str):
    if not jobs.delete_job(jid):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/job/{jid}/image/{n}")
def job_image(jid: str, n: int, t: str = "wechat"):
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    block = j.result.get(t) or j.result.get("wechat")
    imgs = (block or {}).get("images") or []
    if n < 0 or n >= len(imgs):
        raise HTTPException(404)
    return Response(content=imgs[n], media_type="image/jpeg")


@router.get("/job/{jid}/preview", response_class=HTMLResponse)
def job_preview(jid: str, request: Request):
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    woven = None
    wc = j.result.get("wechat")
    if wc:
        imgs = wc.get("images") or []
        body_srcs = [f"/job/{jid}/image/{i}?t=wechat" for i in range(len(imgs))]
        woven = weave_images(wc.get("body_html", ""), body_srcs, wc.get("image_captions"))
    return templates.TemplateResponse(request, "preview.html", {"job": j, "jid": jid, "woven_wechat": woven})


@router.get("/job/{jid}/cover")
def job_cover(jid: str):
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    wc = j.result.get("wechat") or {}
    cov = wc.get("cover")
    if not cov:
        raise HTTPException(404)
    return Response(content=cov, media_type="image/jpeg")


@router.get("/job/{jid}/export/html")
def export_html(jid: str):
    """导出文章为独立 HTML 文件（图片内嵌 base64，离线可看）。"""
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    wc = j.result.get("wechat")
    if not wc:
        raise HTTPException(404)
    imgs = wc.get("images") or []
    data_urls = [f"data:image/jpeg;base64,{base64.b64encode(im).decode()}" for im in imgs]
    woven = weave_images(wc.get("body_html", ""), data_urls, wc.get("image_captions"))
    cover_b64 = base64.b64encode(wc["cover"]).decode() if wc.get("cover") else None
    cover_html = f'<img src="data:image/jpeg;base64,{cover_b64}" style="width:100%;border-radius:8px;margin-bottom:12px;">' if cover_b64 else ""
    title = wc.get("title", "文章")
    html = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{max-width:760px;margin:40px auto;padding:0 20px;font-family:system-ui,sans-serif;line-height:1.8;color:#333;}}
img{{max-width:100%;border-radius:8px;}}figcaption{{color:#888;font-size:13px;text-align:center;}}</style></head>
<body>{cover_html}<h1>{title}</h1><p style="color:#666;">摘要：{wc.get("summary","")}</p>{woven}</body></html>"""
    return Response(content=html.encode("utf-8"), media_type="text/html",
                    headers={"Content-Disposition": "attachment; filename=article.html"})


@router.get("/history", response_class=HTMLResponse)
def history(request: Request):
    items = []
    for j in jobs.list_jobs():
        r = j.result or {}
        wc = r.get("wechat") or {}
        xh = r.get("xhs") or {}
        items.append({
            "id": j.id, "created_at": j.created_at, "target": r.get("target", ""),
            "title": wc.get("title") or xh.get("title") or "(无标题)",
            "stage": j.stage,
        })
    return templates.TemplateResponse(request, "history.html", {"items": items})


def _bytes_to_tmp(data: bytes, suffix: str = ".jpg") -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(suffix=suffix, dir=str(UPLOAD_DIR))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return name


@router.post("/job/{jid}/publish")
async def publish(jid: str, request: Request):
    j = jobs.get_job(jid)
    if j is None or not j.result:
        raise HTTPException(404)
    cfg = load_config()
    if not cfg.wechat.app_id or not cfg.wechat.app_secret:
        raise HTTPException(400, "未配置公众号 AppID/AppSecret，请到设置页填写")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    edited = (payload or {}).get("body_html")
    wc = j.result["wechat"]
    imgs = wc["images"]
    pub = WeChatPublisher(cfg.wechat.app_id, cfg.wechat.app_secret)
    thumb_src = wc.get("cover") or (wc["images"][0] if wc.get("images") else b"")
    thumb = pub.upload_cover_material(_bytes_to_tmp(thumb_src)) if thumb_src else ""

    def _upload_ref(m):
        i = int(m.group(1))
        if 0 <= i < len(imgs):
            return pub.upload_body_image(_bytes_to_tmp(imgs[i]))
        return m.group(0)

    body_html = edited if edited is not None else wc.get("body_html", "")
    content = re.sub(r"/job/[^\"'<>=]*?/image/(\d+)(?:\?[^\"'<>=]*)?", _upload_ref, body_html)
    media_id = pub.create_draft({
        "title": wc["title"], "author": "Content Studio", "digest": wc.get("summary", ""),
        "content": content, "thumb_media_id": thumb,
        "need_open_comment": 0, "only_fans_can_comment": 0,
    })
    wc["draft_media_id"] = media_id
    return {"media_id": media_id}


@router.get("/settings", response_class=HTMLResponse)
def settings_form(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(request, "settings.html", {"cfg": cfg})


@router.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    cfg = load_config()
    active = form.get("active_provider") or (cfg.providers[0].name if cfg.providers else "")
    for p in cfg.providers:
        key = (form.get(f"key_{p.name}") or "").strip()
        model = (form.get(f"model_{p.name}") or "").strip()
        base_url = (form.get(f"base_url_{p.name}") or "").strip()
        if key:
            p.api_key = key
        if model:
            p.model = model
        if base_url:
            p.base_url = base_url
    cfg.active_provider = active
    cfg.comfy.base_url = (form.get("comfy_url") or cfg.comfy.base_url).strip()
    cfg.wechat.app_id = (form.get("app_id") or "").strip()
    cfg.wechat.app_secret = (form.get("app_secret") or "").strip()
    save_config(cfg)
    return JSONResponse({"ok": True})
