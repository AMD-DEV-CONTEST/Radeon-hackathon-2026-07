"""
Union·由你 — CNC AI 工艺大脑 v12.0.0-fusion
全自动自适配 · 一句话画STEP+3D预览+上传报价+输出打包
作者: timo.cao | 邮箱: miscdd@163.com | 生成: 大帅教练系统
"""
import sys, json, os, io
import asyncio
from pathlib import Path
from datetime import datetime

# Windows GBK 编码兼容 — 强制 stdout/stderr 使用 UTF-8
if sys.platform == "win32":
    for _stream_name in ("stdout", "stderr"):
        _stream = getattr(sys, _stream_name)
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 版本号(统一定义，禁止硬编码) ──
VERSION = "12.0.0-fusion"
VERSION_CODENAME = "工业融合"

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from src.core.environment_detector import EnvironmentDetector
from src.core.model_auto_loader import ModelAutoLoader
from src.core.model_registry import ModelRegistry
from src.core.skill_auto_loader import SkillAutoLoader
from src.ai_engine.ollama_engine import OllamaEngine
from src.ai_engine.engine import AIEngine, EngineError
from src.neuro_core.serial_expert import SerialExpertOrchestrator
from src.neuro_core.schema_validator import SchemaValidator
from src.neuro_core.conflict_check import ConflictChecker
from src.safety.audit_logger import AuditLogger
from src.runtime.event_bus import EventBus
from src.runtime.progress_reporter import ProgressReporter
from src.runtime.quote_adapter import QuoteAdapter
from src.runtime.skill_caller import SkillCaller
from src.runtime.history_lookup import HistoryLookup
from src.runtime.step_generator_dual import generate_part, get_engine_status
from src.runtime.step_generator import get_weight, DENSITY
from src.runtime.step_parser import extract_bbox_from_step, estimate_volume_from_bbox, get_material_density
from src.runtime.export_bundler import create_bundle
from src.data.rag_engine import search, index_document, auto_index_all, get_stats, browse_registry, register_item
from src.neuro_core.reasoning_chain import get_chain, get_recent_chains, ReasoningChain, register_chain, StepType
from app.cnc_quick import router as cnc_quick_router  # v12.0-fusion: CNC快速通道

# ── Shadow Mode ──
# Shadow mode (可通过环境变量 SHADOW_MODE=0 关闭)
SHADOW_MODE = os.environ.get("SHADOW_MODE", "1") != "0"

async def run_blocking(func, *args, **kwargs):
    """统一 helper: 将同步阻塞调用(urllib LLM 请求等)放入线程池执行，
    避免在 async 处理函数中阻塞 FastAPI 事件循环。"""
    return await asyncio.to_thread(func, *args, **kwargs)

def wrap_shadow(response: dict) -> dict:
    if SHADOW_MODE:
        response["disclaimer"] = "此结论为AI建议，仅供参考。实际加工前请人工确认。"
        response["shadow_mode"] = True
    return response

# ── 全局启动 ──
detector = EnvironmentDetector(PROJECT_ROOT)
env = detector.detect()

# 模型健康检查函数
def _test_model_health(model_cfg):
    """测试模型是否可用，返回(True, response)或(False, error)。"""
    import urllib.request
    source = model_cfg.get("source", "")
    name = model_cfg.get("name", "?")
    
    if source in ("cloud", "local"):
        api_url = model_cfg.get("api_url", "")
        api_key = model_cfg.get("api_key", "")
        model_id = model_cfg.get("model_id", name)
        try:
            body = json.dumps({"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}).encode()
            req = urllib.request.Request(
                api_url.rstrip("/") + "/chat/completions",
                data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, content[:50]
        except Exception as e:
            return False, str(e)
    elif source == "ollama":
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            if name in models:
                return True, "ollama available"
            return False, f"model {name} not in ollama"
        except Exception as e:
            return False, str(e)
    return False, "unknown source"

# 模型注册表 — 自动检测Ollama + 云端配置
model_registry = ModelRegistry(PROJECT_ROOT / "config" / "models.json")
all_models = model_registry.get_all_ranked()

# 按质量排序后，选择第一个可用的模型
best_config = None
ai = None
_ai_available = False

# 降级链优先（尊重配置preference），其余模型作为补充候选
_fallback_chain_startup = model_registry.select_with_fallback()
_chain_names = {m["name"] for m in _fallback_chain_startup}
_candidates = _fallback_chain_startup + [m for m in all_models if m["name"] not in _chain_names]

print(f"[MODEL] Found {len(all_models)} models, testing availability...")
for model_cfg in _candidates:
    name = model_cfg.get("name", "?")
    source = model_cfg.get("source", "?")
    score = model_cfg.get("quality_score", 0)
    ok, msg = _test_model_health(model_cfg)
    print(f"[MODEL] Testing {name} ({source}, score={score}): {'✅' if ok else '❌'} {msg[:60]}")
    if ok and not best_config:
        best_config = model_cfg
        print(f"[MODEL] Selected: {name} ({source})")

# 根据模型来源选择引擎
if best_config:
    source = best_config.get("source", "")
    if source in ("cloud", "local"):
        ai = AIEngine(best_config)
    else:
        model_name = best_config.get("name", "qwen2.5:1.5b")
        ai = OllamaEngine(model_name)
    _ai_available = True
    print(f"[MODEL] AI engine ready: {best_config['name']}")
else:
    print("[MODEL] No AI model available, using rule engine only")

# ── 降级机制: 云端失败自动fallback到本地 ──
_fallback_chain = model_registry.select_with_fallback()
print(f"[FALLBACK] Chain: {[m['name'] for m in _fallback_chain]}")
_LAST_CHAT_META = {"model": None, "source": None, "fallback_index": -1}  # fallback_chat最近一次成功模型(XAI追溯用)

def fallback_chat(prompt, system_prompt="", temperature=0.3, max_tokens=2048):
    """带降级的chat调用: 云端失败→自动切本地。"""
    global ai, best_config, _fallback_chain
    last_err = None
    for _idx, model_cfg in enumerate(_fallback_chain):
        name = model_cfg.get("name", "?")
        source = model_cfg.get("source", "?")
        try:
            if source in ("cloud", "local"):
                from src.ai_engine.openai_engine import OpenAIEngine
                engine = OpenAIEngine(
                    api_key=model_cfg.get("api_key", "none"),
                    api_url=model_cfg["api_url"],
                    model=model_cfg.get("model_id", name),
                )
            else:
                engine = OllamaEngine(name)
            result = engine.chat(prompt, system_prompt, temperature, max_tokens)
            # 检查是否返回了错误JSON
            if result and '"error"' in result and '"status":' in result:
                import json as _j
                try:
                    err = _j.loads(result)
                    if err.get("status") in ("ollama_call_failed", "cloud_call_failed"):
                        last_err = result
                        print(f"[FALLBACK] {name} failed, trying next...")
                        continue
                except Exception:
                    pass
            # 成功 → 更新全局ai为当前引擎(下次直接用)
            if ai is not engine:
                ai = engine
                best_config = model_cfg
                print(f"[FALLBACK] Switched to {name} ({source})")
            # 清理多模态模型泄漏的特殊token（如 <|tts_eos|>）
            if isinstance(result, str):
                import re as _re
                result = _re.sub(r"<\|[^|]*\|>", "", result).strip()
            _LAST_CHAT_META = {"model": name, "source": source, "fallback_index": _idx}
            return result
        except Exception as e:
            last_err = str(e)
            print(f"[FALLBACK] {name} exception: {e}")
            continue
    # 全部模型失败: 抛出带上下文的异常，由调用方返回结构化错误(错误文本不混入用户回复)
    raise EngineError(f"all models failed, last_error: {last_err}")

def fallback_chat_json(prompt, system_prompt="", temperature=0.3, max_tokens=2048):
    """带降级的chat_json调用。全部模型失败时抛出 EngineError。"""
    raw = fallback_chat(prompt, system_prompt, temperature, max_tokens)
    import json as _j
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return _j.loads(raw[start:end+1])
        except Exception:
            pass
    return {"_raw": raw, "_error": "json_parse_failed"}

# ── AI引擎包装器：所有模块统一使用fallback机制 ──
class AIFallbackWrapper:
    """包装器，让所有模块统一使用 fallback_chat，自动降级。
    全部模型失败时静默降级(返回空文本/错误标记)，保证专家编排等内部模块不崩溃，
    且错误文本不会泄漏到用户可见回复。直接面向用户的路由应自行捕获 EngineError。"""
    def chat(self, prompt, system_prompt="", temperature=0.3, max_tokens=2048):
        try:
            return fallback_chat(prompt, system_prompt, temperature, max_tokens)
        except EngineError as e:
            print(f"[AI-WRAPPER] engine failed: {e}")
            return ""
    def chat_json(self, prompt, system_prompt="", temperature=0.3, max_tokens=2048):
        try:
            return fallback_chat_json(prompt, system_prompt, temperature, max_tokens)
        except EngineError as e:
            print(f"[AI-WRAPPER] engine failed: {e}")
            return {"_error": "engine_failed"}

ai_wrapper = AIFallbackWrapper()

# ── 一句话画图: LLM结构化参数提取 (JSON结构收集 → LLM推理 → OCC直接驱动) ──
PART_SPEC_TYPES = ["flange", "sleeve", "shaft", "plate", "box", "bracket", "step_block"]

PART_SPEC_SYSTEM = """你是CNC零件参数提取器。从用户的一句话中提取零件参数，只输出JSON，禁止输出任何解释、思考过程或markdown标记。

JSON格式(未提及的参数一律填null):
{"part_type": "flange|sleeve|shaft|plate|box|bracket|step_block|null",
 "params": {"od": 外径mm, "id": 内径mm, "thickness": 厚度mm, "length": 长度mm,
            "w": 宽mm, "h": 高mm, "t": 板厚mm, "d": 直径或深度mm,
            "bolt_holes": 螺栓孔个数, "bolt_d": 螺栓孔径mm, "bolt_pcd": 孔分布圆直径mm},
 "material": "材料牌号如6061/7075/45钢/Q235/304/黄铜/ABS, 未提及填null",
 "quantity": 件数整数, 未提及填null,
 "surface_treatment": "表面处理如阳极氧化/镀镍/发黑/喷砂, 未提及填null"}

映射规则: 法兰/检查盖→flange; 法兰盖/闷盖/圆盘(无内孔)→flange且id=0; 轴套/衬套→sleeve; 轴/齿轮轴→shaft;
平板/板/垫板→plate; 箱体/方块/壳体→box; 支架→bracket; 台阶块→step_block。
"直径120"对法兰/轴套类→od=120; "内径50"→id=50; M10孔→bolt_d=10; "4个孔"→bolt_holes=4。
尺寸只填数字(单位mm)。不是画零件的请求→part_type填null。只输出JSON。"""

_SPEC_PARAM_KEYS = ("od", "id", "thickness", "length", "w", "h", "t", "d",
                    "bolt_holes", "bolt_d", "bolt_pcd", "step_w", "step_d", "h1", "h2")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def validate_part_spec(spec):
    """校验+清洗LLM提取的零件规格，不合法返回None。"""
    if not isinstance(spec, dict):
        return None
    pt = spec.get("part_type")
    if pt not in PART_SPEC_TYPES:
        return None
    clean = {}
    raw = spec.get("params") or {}
    for k in _SPEC_PARAM_KEYS:
        v = raw.get(k)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if k == "bolt_holes":
            clean[k] = int(_clamp(v, 0, 64))
        elif k == "id":
            v = _clamp(v, 0, 5000)  # id=0 合法 — 无内孔(法兰盖/闷盖)
            clean[k] = int(v) if v == int(v) else v
        else:
            v = _clamp(v, 0.1, 5000)
            clean[k] = int(v) if v == int(v) else v
    # 参数别名归一: 法兰/轴套类的"直径d"→od (LLM常把直径放d)
    if pt in ("flange", "sleeve") and "d" in clean and "od" not in clean:
        clean["od"] = clean.pop("d")
    elif pt == "shaft" and "od" in clean and "d" not in clean:
        clean["d"] = clean.pop("od")
    if clean.get("bolt_holes"):
        clean.setdefault("bolt_d", 8)
        if "bolt_pcd" not in clean and clean.get("od"):
            clean["bolt_pcd"] = round(clean["od"] * 0.75)
    material = spec.get("material") or None
    if material:
        material = str(material).strip()[:20] or None
    quantity = spec.get("quantity")
    try:
        quantity = int(_clamp(float(quantity), 1, 100000)) if quantity else None
    except (TypeError, ValueError):
        quantity = None
    surface = spec.get("surface_treatment") or None
    if surface:
        surface = str(surface).strip()[:20]
        if surface in ("无", "none", "None", ""):
            surface = None
    return {"part_type": pt, "params": clean, "material": material,
            "quantity": quantity, "surface_treatment": surface}


def _log_llm_spec_raw(message: str, raw, meta: dict):
    """LLM参数提取原始输出落盘 (logs/llm_spec_raw.jsonl, 便于追溯)。"""
    try:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().isoformat(timespec="seconds"),
               "message": message[:500], "model": meta.get("model"),
               "source": meta.get("source"), "fallback_index": meta.get("fallback_index"),
               "note": meta.get("note"), "raw": raw}
        with open(log_dir / "llm_spec_raw.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[LLM-SPEC] raw log failed: {e}")


def llm_extract_part_spec(message: str, temperature: float = 0.1):
    """LLM推理: 一句话 → 结构化零件规格JSON。
    返回 (spec|None, raw_text, meta) — spec失败为None(调用方降级正则),
    raw_text/meta 用于推理链展示与落盘追溯。
    temperature 可传入 — TOT多管道竞争采样(不同温度)使用。"""
    meta = {"model": None, "source": None, "fallback_index": -1, "note": "LLM不可用"}
    if not _ai_available or not _fallback_chain:
        print("[LLM-SPEC] no AI model available, skipping LLM extraction")
        return None, "", meta
    try:
        raw = fallback_chat(f"用户输入: {message}", system_prompt=PART_SPEC_SYSTEM,
                            temperature=temperature, max_tokens=600)
        meta = dict(_LAST_CHAT_META)
        meta["note"] = "LLM提取成功"
        if not raw or '"part_type"' not in raw:
            meta["note"] = "LLM输出不含part_type"
            _log_llm_spec_raw(message, raw or "", meta)
            return None, raw or "", meta
        # 健壮: 如果模型返回错误JSON，直接退化
        if isinstance(raw, str) and raw.strip().startswith('{"error"'):
            print(f"[LLM-SPEC] model returned error, skipping")
            meta["note"] = "LLM返回错误JSON"
            _log_llm_spec_raw(message, raw, meta)
            return None, raw, meta
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            meta["note"] = "LLM输出未截取到JSON片段"
            _log_llm_spec_raw(message, raw, meta)
            return None, raw, meta
        result = validate_part_spec(json.loads(raw[start:end + 1]))
        if result is None:
            meta["note"] = "validate_part_spec校验失败"
        _log_llm_spec_raw(message, raw, meta)
        print(f"[LLM-SPEC] {message[:50]} -> {result}")
        return result, raw, meta
    except Exception as e:
        print(f"[LLM-SPEC] extraction failed: {e}")
        meta["note"] = f"LLM调用异常: {e}"
        return None, "", meta


registry = SkillAutoLoader(env).load_all()
bus = EventBus()
progress = ProgressReporter(bus)
conflict_checker = ConflictChecker(ai_wrapper)  # 使用包装器
audit = AuditLogger()
quote_adapter = QuoteAdapter()
history_lookup = HistoryLookup()
skill_registry = SkillCaller()

skill_registry.register("quote_calculate", quote_adapter.quote, {"description": "CNC加工精确报价计算"})
skill_registry.register("conflict_check", conflict_checker.check, {"description": "工艺冲突检测"})
skill_registry.register("history_lookup", history_lookup.lookup, {"description": "客户历史订单查询"})
history_lookup.seed_demo_data()

expert_engine = SerialExpertOrchestrator(ai_wrapper, registry["experts"], bus,
    skill_registry=skill_registry, schema_validator=SchemaValidator(registry["experts"]))

STARTUP_INFO = {
    "status": "ready", "hostname": env["hostname"],
    "cpu": env["cpu"]["brand"], "cores": env["cpu"]["cores_physical"],
    "memory_gb": env["memory_gb"],
    "gpu": env["gpu"][0]["name"] if env["gpu"] else "CPU Only",
    "model": best_config["name"] if best_config else "none",
    "model_source": best_config.get("source", "ollama") if best_config else "none",
    "model_params": best_config.get("param_size", best_config.get("param_count", "unknown")) if best_config else "unknown",
    "model_provider": best_config.get("provider", "ollama") if best_config else "none",
    "ai_available": _ai_available,
    "expert_count": best_config.get("expert_count", 3) if best_config else 3,
    "skills": len(registry["skills"]), "experts": list(registry["experts"].keys()),
    "tools": skill_registry.list_available(), "version": VERSION,
    "engine": get_engine_status(),
    "offline_features": ["quote", "conflict_check", "step_generate", "history_lookup"],
}

import time as _time
SERVER_START_TIME = _time.time()
CURRENT_TASK = {"active": False, "name": None, "progress": 0}

print("=" * 60)
print(f"🦞 Union·由你 — CNC AI 工艺大脑 v{VERSION}")
print("  一句话画图·3D预览·上传报价·输出打包")
print("=" * 60)
if best_config:
    src = best_config.get("source", "?")
    prov = best_config.get("provider", "?")
    print(f"🤖 模型: {best_config['name']} ({src}/{prov})")
    if src == "cloud":
        print(f"☁️  云端: {best_config.get('api_url', '?')}")
    elif src == "local":
        print(f"💻 本地: {best_config.get('api_url', '?')} ({best_config.get('param_count', '?')}B)")
    else:
        print(f"💻 本地: {best_config.get('size_gb', '?')}GB")
print("=" * 60)
print(f"🖥️  {env['cpu']['brand']} | {env['cpu']['cores_physical']}核 | {env['memory_gb']}GB")
print(f"🧠 模型: {best_config['name'] if best_config else 'none'} | 👥 {best_config.get('expert_count', 3) if best_config else 3}人董事会")
print(f"📐 STEP生成: trimesh | 🎨 3D预览: Three.js | 📦 ZIP打包: 就绪")
print("=" * 60)

app = FastAPI(title="Union·由你", version=VERSION)

# v12.0-fusion: 注册CNC快速通道路由器
app.include_router(cnc_quick_router)

# 全局设置: 所有JSON响应强制 UTF-8 charset
from fastapi.responses import JSONResponse as _JRC
class JSONResponse(_JRC):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("media_type", "application/json; charset=utf-8")
        super().__init__(*args, **kwargs)

# 静态文件服务
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT/"app"/"static")), name="static")

# ── 触发检测 ──
HIGH_RISK_MATERIALS = ["钛合金", "inconel", "高温合金", "哈氏合金", "钛", "INCONEL", "HASTELLOY", "17-4PH"]
HIGH_VALUE_KEYWORDS = ["10万", "100000", "十万", "高价", "大单"]
TIGHT_TOLERANCE = ["it4", "it5", "it6", "精磨"]

def detect_triggers(message: str) -> list:
    msg = message.lower()
    triggers = []
    for mat in HIGH_RISK_MATERIALS:
        if mat in msg: triggers.append(f"高风险材料: {mat}"); break
    if any(k in msg for k in HIGH_VALUE_KEYWORDS): triggers.append("高价值订单")
    if any(k in msg for k in TIGHT_TOLERANCE): triggers.append("严苛公差")
    return triggers

# ── API: 根页面/状态/健康 ──
@app.get("/", response_class=HTMLResponse)
async def index():
    # 读取合并后的 UI 页面
    merged_html_path = PROJECT_ROOT / "app" / "static" / "index_merged.html"
    if merged_html_path.exists():
        with open(merged_html_path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content=HTML_PAGE)  # 后备

@app.get("/api/status")
async def status(): return JSONResponse(content=STARTUP_INFO)

@app.get("/api/health")
async def health():
    return JSONResponse(content={
        "status": "healthy",
        "model": best_config["name"] if best_config else "none",
        "model_source": best_config.get("source", "none") if best_config else "none",
        "model_params": best_config.get("param_size", best_config.get("param_count", "unknown")) if best_config else "unknown",
        "experts": best_config.get("expert_count", 3) if best_config else 3,
        "skills": len(registry["skills"]),
        "expert_list": list(registry["experts"].keys()),
        "tools": skill_registry.list_available(),
        "audit_records": audit.count() if hasattr(audit, 'count') else 'N/A',
        "uptime_seconds": int(_time.time() - SERVER_START_TIME),
        "cpu_cores": env["cpu"]["cores_physical"],
        "memory_gb": env["memory_gb"],
        "current_task": CURRENT_TASK,
        "version": VERSION,
        "model_provider": best_config.get("provider", "none") if best_config else "none",
    })

@app.get("/api/version")
async def version(): return JSONResponse(content={"version": VERSION, "codename": VERSION_CODENAME})

# ══════════════════════════════════════════════════════════
# RAG 端点 — "小刀切梨"轻量检索
# ══════════════════════════════════════════════════════════

@app.get("/api/rag/status")
async def rag_status():
    return JSONResponse(content=get_stats())


@app.post("/api/rag/search")
async def rag_search(request: Request):
    data = await request.json()
    q = data.get("query", "")
    top_k = data.get("top_k", 5)
    results = search(q, top_k=top_k)
    return JSONResponse(content={"query": q, "results": results, "total": len(results)})


@app.post("/api/rag/index")
async def rag_index(request: Request):
    data = await request.json()
    doc_id = data.get("doc_id", f"doc_{int(_time.time())}")
    title = data.get("title", "未命名")
    content = data.get("content", "")
    doc_type = data.get("type", "text")
    tags = data.get("tags", [])
    r = index_document(doc_id, title, content, doc_type=doc_type, tags=tags)
    return JSONResponse(content=r)


@app.post("/api/rag/auto-index")
async def rag_auto_index():
    """自动索引: 订单+STEP+审计。"""
    r = auto_index_all()
    return JSONResponse(content=r)


@app.get("/api/rag/registry")
async def rag_registry(parent_path: str = ""):
    """浏览层级引索树。"""
    items = browse_registry(parent_path=parent_path)
    return JSONResponse(content={"parent": parent_path, "items": items, "total": len(items)})


@app.get("/api/rag/ui", response_class=HTMLResponse)
async def rag_ui():
    """RAG管理页面。"""
    return HTMLResponse(content=RAG_UI_HTML)



@app.get("/api/models/fallback")
async def get_fallback_chain():
    """查看当前降级链。"""
    chain = model_registry.select_with_fallback()
    return JSONResponse({
        "chain": [{"name": m["name"], "source": m["source"], "quality_score": m.get("quality_score")} for m in chain],
        "current": best_config.get("name", "none") if best_config else "none",
    })

@app.get("/api/models")
async def list_models():
    all_m = model_registry.get_all_ranked()
    return JSONResponse(content={
        "total": len(all_m),
        "current_model": best_config,
        "best": best_config,
        "models": [{"name": m["name"], "source": m["source"], "score": m["quality_score"],
                     "provider": m.get("provider", "?")} for m in all_m],
        "config_path": str(model_registry.config_path),
    })

@app.post("/api/models/test")
async def test_model_connection(body: dict):
    """测试模型连接。"""
    api_url = body.get("api_url", "")
    api_key = body.get("api_key", "")
    model_id = body.get("model_id", "")
    test_prompt = body.get("test_prompt", "你好，请回复OK")
    
    if not api_url:
        return JSONResponse({"success": False, "error": "缺少api_url"})
    
    def _do_test():
        import urllib.request
        messages = [{"role": "user", "content": test_prompt}]
        req_body = json.dumps({"model": model_id, "messages": messages, "max_tokens": 50, "stream": False})
        req = urllib.request.Request(
            api_url.rstrip("/") + "/chat/completions",
            data=req_body.encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    try:
        data = await run_blocking(_do_test)
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return JSONResponse({"success": True, "response": content[:200]})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

def _list_remote_models(api_url: str, api_key: str = "lm-studio", timeout: int = 5) -> list:
    """通过标准OpenAI协议 GET {api_url}/models 拉取端点上的真实模型ID列表。"""
    import urllib.request
    req = urllib.request.Request(
        api_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return [m.get("id", "") for m in data.get("data", []) if m.get("id")]


def _list_ollama_models(timeout: int = 3) -> list:
    """拉取本地 Ollama 已安装模型列表。"""
    import urllib.request
    req = urllib.request.Request("http://localhost:11434/api/tags")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("models", [])


@app.post("/api/models/list-remote")
async def list_remote_models(body: dict):
    """列出指定OpenAI兼容端点上的模型列表（供前端下拉选择）。"""
    api_url = body.get("api_url", "")
    api_key = body.get("api_key", "") or "lm-studio"
    if not api_url:
        return JSONResponse({"success": False, "error": "缺少api_url"})
    try:
        ids = await run_blocking(_list_remote_models, api_url, api_key, 8)
        return JSONResponse({"success": True, "models": ids, "api_url": api_url})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})


@app.post("/api/models/discover")
async def discover_models(body: dict = None):
    """自动搜索可用模型 — 通过标准OpenAI协议 /models 动态发现，零硬编码模型名。

    可选body: {"endpoints": [{"api_url": "...", "api_key": "...", "source": "cloud|local"}]}
    不传则使用默认端口列表 + 配置文件中已保存的端点。
    """
    found = []

    # 候选端点: 配置文件已保存的 + 默认本地端口 + 用户额外指定
    candidates = []
    for m in model_registry.load_cloud_models():
        candidates.append({"api_url": m["api_url"], "api_key": m.get("api_key", "lm-studio"), "source": m.get("source", "local")})
    for default_url in ("http://127.0.0.1:1234/v1", "http://localhost:1250/v1", "http://127.0.0.1:1280/v1"):
        candidates.append({"api_url": default_url, "api_key": "lm-studio", "source": "local"})
    if body and isinstance(body, dict):
        for ep in body.get("endpoints", []):
            if ep.get("api_url"):
                candidates.append({"api_url": ep["api_url"], "api_key": ep.get("api_key", "lm-studio"), "source": ep.get("source", "local")})

    # 去重 (api_url)
    seen_urls = set()
    for ep in candidates:
        url = ep["api_url"].rstrip("/")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            ids = await run_blocking(_list_remote_models, url, ep.get("api_key") or "lm-studio", 5)
            for model_id in ids:
                found.append({
                    "name": model_id, "model_id": model_id,
                    "source": ep["source"], "api_url": url,
                    "api_key": ep.get("api_key", "lm-studio"), "status": "online",
                })
            print(f"[DISCOVER] {url}: {len(ids)} models -> {ids[:5]}")
        except Exception as e:
            print(f"[DISCOVER] {url} failed: {e}")

    # 测试Ollama
    try:
        ollama_models = await run_blocking(_list_ollama_models, 3)
        for m in ollama_models:
            found.append({"name": m["name"], "model_id": m["name"], "source": "ollama", "api_url": "http://localhost:11434", "status": "online"})
    except Exception:
        pass

    return JSONResponse({"models": found})

@app.get("/api/progress")
async def task_progress(): return JSONResponse(content=CURRENT_TASK)

# ── API: 冲突检测 / 审计 ──
@app.get("/api/conflict-check")
@app.post("/api/conflict-check")
async def conflict_check(request: Request):
    if request.method == "POST":
        try: params = await request.json()
        except: params = dict(await request.form())
    else: params = dict(request.query_params)
    if not params: return JSONResponse(content={"error": "需要参数"}, status_code=400)
    return JSONResponse(content=conflict_checker.check(params))

@app.get("/api/audit")
async def get_audit(request: Request):
    task_id = request.query_params.get("task_id")
    limit = int(request.query_params.get("limit", 20))
    return JSONResponse(content={"records": audit.query(task_id=task_id, limit=limit),
                                 "chain_verify": audit.verify_chain()})

# ══════════════════════════════════════════════════════════
# XAI Reasoning Chain API — 可解释AI推理链
# ══════════════════════════════════════════════════════════

@app.get("/api/reasoning/recent")
async def reasoning_recent(limit: int = 10):
    """Get recent reasoning chains."""
    return JSONResponse(content={"chains": get_recent_chains(limit), "total": len(get_recent_chains(50))})

@app.get("/api/reasoning/{chain_id}")
async def reasoning_detail(chain_id: str):
    """Get a specific reasoning chain by ID."""
    chain = get_chain(chain_id)
    if not chain:
        return JSONResponse(content={"error": "Chain not found"}, status_code=404)
    return JSONResponse(content=chain)

@app.get("/api/reasoning", response_class=HTMLResponse)
async def reasoning_ui():
    """XAI Reasoning Chain viewer page."""
    return HTMLResponse(content=REASONING_UI_HTML)

@app.post("/api/conflict-check-xai")
async def conflict_check_xai(request: Request):
    """Conflict check WITH reasoning chain (XAI version)."""
    try: params = await request.json()
    except: return JSONResponse(content={"error": "需要JSON参数"}, status_code=400)
    if not params: return JSONResponse(content={"error": "需要参数"}, status_code=400)
    return JSONResponse(content=conflict_checker.check_with_reasoning(params))

@app.post("/api/quote-xai")
async def quote_xai(request: Request):
    """Quote WITH reasoning chain (XAI version)."""
    try:
        raw_body = await request.body()
        try:
            body = json.loads(raw_body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = json.loads(raw_body.decode("utf-8", errors="replace"))
    except Exception as e:
        return JSONResponse(content={"error": f"需要JSON参数: {str(e)}"}, status_code=400)
    
    result = quote_adapter.quote_with_reasoning(body)
    return JSONResponse(content=result)

# ── ★ API: 一句话画STEP ──
@app.post("/api/generate-step")
async def generate_step(request: Request):
    try: params = await request.json()
    except: return JSONResponse(content={"error": "需要JSON参数"}, status_code=400)
    
    part_type = params.get("part_type", params.get("type", "flange"))
    result = generate_part(part_type, params)
    if "error" in result: return JSONResponse(content=result, status_code=400)
    
    audit.log(task_id=f"step-{os.urandom(3).hex()}", event_type="step_generate", data=params)
    return JSONResponse(content=result)

# ── ★ API: 3D预览 (STL文件服务) ──
@app.get("/api/preview/{filename}")
async def preview_stl(filename: str):
    stl_path = PROJECT_ROOT / "data" / "step" / filename
    if not stl_path.exists():
        return JSONResponse(content={"error": "文件不存在"}, status_code=404)
    return FileResponse(stl_path, media_type="application/octet-stream")

# ── ★ API: 直接报价 (支持message自然语言 + 表单参数 + 完整尺寸) ──
@app.post("/api/quote")
async def quote_direct(request: Request):
    try:
        # 修复 UTF-8/GBK 编码问题
        raw_body = await request.body()
        try:
            body = json.loads(raw_body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                body = json.loads(raw_body.decode("gbk", errors="replace"))
            except:
                body = json.loads(raw_body.decode("utf-8", errors="replace"))
    except Exception as e:
        return JSONResponse(content={"error": f"需要JSON参数: {str(e)}"}, status_code=400)

    # 支持两种调用方式:
    #  1) 直接传 message: "6061法兰直径100厚20，5件阳极氧化"
    #  2) 直接传结构化字段 material/quantity/dimensions/...
    message = body.get("message", "")
    msg_params = quote_adapter.extract_params_from_message(message) if message else {}

    # 表单/结构体参数
    form_params = {
        "material": body.get("material"),
        "quantity": body.get("quantity"),
        "surface_treatment": body.get("surface_treatment", body.get("surface")),
        "weight_kg": body.get("weight_kg"),
        "volume_cm3": body.get("volume_cm3"),
        "tolerance": body.get("tolerance"),
        "process": body.get("process"),
        "shape": body.get("shape"),
        "dimensions": body.get("dimensions"),
        "machining_hours": body.get("machining_hours"),
        "precision": body.get("precision"),
        "roughness": body.get("roughness"),
        "pricing_mode": body.get("pricing_mode"),
        "measurement": body.get("measurement"),
        "jig_fee": body.get("jig_fee"),
        "tool_fee": body.get("tool_fee"),
        "other_fee": body.get("other_fee"),
        "profit_rate": body.get("profit_rate"),
        "discount": body.get("discount"),
        "wire_length": body.get("wire_length"),
        "wire_height": body.get("wire_height"),
    }
    form_params = {k: v for k, v in form_params.items() if v is not None and v != ''}

    merged = quote_adapter.merge_quote_params(msg_params, form_params)
    sources = merged.pop("_sources", {})

    # 统一：消息里的形状（如 flange）保持，未指定 shape 时根据 dimensions 推断
    if not merged.get("shape") and merged.get("dimensions"):
        dims = merged["dimensions"]
        if ("od" in dims) or ("D" in dims and "d" in dims):
            merged["shape"] = "flange"
            sources["shape"] = "消息(尺寸推断)"
        elif "d" in dims or "D" in dims:
            merged["shape"] = "round"
            sources["shape"] = "消息(尺寸推断)"
        elif "w" in dims and "h" in dims:
            merged["shape"] = "flat"
            sources["shape"] = "消息(尺寸推断)"

    material = merged["material"]
    quantity = int(merged["quantity"])
    surface = merged["surface_treatment"]

    # 冲突检查
    conflicts = conflict_checker.check({"material": material, "surface_treatment": surface})
    if not conflicts.get("valid", True):
        return JSONResponse(content={
            "error": "工艺冲突",
            "conflicts": conflicts.get("conflicts", []),
            "warnings": conflicts.get("warnings", [])
        })

    # 若消息/表单没给重量或体积，但有尺寸，则按形状尺寸估算体积
    if merged.get("weight_kg") in (None, '', 0) and merged.get("volume_cm3") in (None, '', 0) and merged.get("dimensions"):
        mat_code = quote_adapter.resolve_material(material)
        weight_est = quote_adapter.calc_weight_from_dimensions(
            merged.get("shape", "flat"), merged["dimensions"], mat_code)
        merged["weight_kg"] = round(weight_est, 4)
        sources["weight_kg"] = "消息尺寸×形状密度估算"

    result = quote_adapter.quote_with_reasoning(merged)
    result["param_sources"] = sources
    result["input_message"] = message
    audit.log(task_id=f"quote-{os.urandom(3).hex()}", event_type="direct_quote", data=result)
    return JSONResponse(content=result)

# ── ★ API: 批量报价 ──
@app.post("/api/batch-quote")
async def batch_quote(request: Request):
    """批量报价接口 - 支持多个零件同时报价"""
    try:
        raw_body = await request.body()
        try:
            data = json.loads(raw_body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                data = json.loads(raw_body.decode("gbk", errors="replace"))
            except:
                data = json.loads(raw_body.decode("utf-8", errors="replace"))
        
        parts = data.get("parts", [])
        
        if not parts:
            return JSONResponse(content={"error": "parts列表为空", "parts": []})
        
        if len(parts) > 50:
            return JSONResponse(content={"error": "单次最多50个零件", "parts": []})
        
        results = []
        total_price = 0
        
        for i, part in enumerate(parts):
            try:
                # 构造单个零件的报价参数
                quote_params = {
                    "part_name": part.get("name", f"零件{i+1}"),
                    "material": part.get("material", "AL6061"),
                    "quantity": int(part.get("quantity", 1)),
                    "surface_treatment": part.get("surface_treatment", "无"),
                    "tolerance": part.get("tolerance", "IT8"),
                    "process": part.get("process", "三轴CNC"),
                    "weight_kg": part.get("weight_kg"),
                    "volume_cm3": part.get("volume_cm3"),
                    "machine_hours": part.get("machine_hours"),
                    "part_type": part.get("part_type", "default"),
                }
                
                # 移除 None 值
                quote_params = {k: v for k, v in quote_params.items() if v is not None}
                
                # 调用报价引擎
                result = quote_adapter.quote(quote_params)
                result["part_index"] = i
                results.append(result)
                total_price += result.get("final_price", 0)
                
                # 审计日志
                audit.log(task_id=f"batch-{os.urandom(3).hex()}", event_type="batch_quote", data={"part_index": i, "params": quote_params, "result": result})
                
            except Exception as e:
                results.append({
                    "part_index": i,
                    "part_name": part.get("name", f"零件{i+1}"),
                    "error": str(e)
                })
        
        success_results = [r for r in results if "error" not in r]
        
        return JSONResponse(content={
            "parts": results,
            "total_parts": len(parts),
            "success_count": len(success_results),
            "total_price": round(total_price, 2),
            "batch_summary": {
                "materials": list(set(r.get("material", "") for r in success_results)),
                "total_weight": round(sum(r.get("weight_kg", 0) for r in success_results), 4),
                "total_machining_hours": round(sum(r.get("machine_hours", 0) for r in success_results), 2),
                "total_final_price": round(sum(r.get("final_price", 0) for r in success_results), 2),
            },
            "disclaimer": "此结论为AI建议，仅供参考。实际加工前请人工确认。",
            "shadow_mode": True,
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"error": f"批量报价失败: {str(e)}", "parts": []}, status_code=500)

# ── ★ API: 上传STEP报价 ──
@app.post("/api/upload-step")
async def upload_step_quote(file: UploadFile = File(...), material: str = Form("6061"),
                            quantity: int = Form(10), surface: str = Form("无"),
                            tolerance: str = Form("IT8"), process: str = Form("三轴CNC")):
    # 保存上传文件（使用唯一文件名避免覆盖）
    upload_dir = PROJECT_ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    uid_prefix = os.urandom(3).hex()
    safe_filename = f"{uid_prefix}_{file.filename}"
    file_path = upload_dir / safe_filename
    content = await file.read()
    file_path.write_bytes(content)
    
    stl_url = None
    parse_warning = None
    mesh_stats = None  # STL详细统计 (参考 cad-parser-stl)
    
    # 如果上传的是STL文件，直接复制到预览目录
    if file.filename.lower().endswith('.stl'):
        preview_dir = PROJECT_ROOT / "data" / "step"
        preview_dir.mkdir(parents=True, exist_ok=True)
        uid = os.urandom(4).hex()
        stl_name = f"upload_{uid}.stl"
        stl_path = preview_dir / stl_name
        stl_path.write_bytes(content)
        stl_url = f"/api/preview/{stl_name}"
    
    # ★ 优先尝试 trimesh+cascadio 生成3D预览（STEP/STP文件）
    # 这样即使STEP文本解析失败，3D预览仍可用
    if not stl_url and file.filename.lower().endswith(('.step', '.stp')):
        try:
            import trimesh
            loaded = trimesh.load(str(file_path))
            # Scene对象（多体STEP）→ 合并所有子mesh
            if hasattr(loaded, 'geometry'):
                meshes = [m for m in loaded.geometry.values() if hasattr(m, 'vertices') and len(m.vertices) > 0]
                if meshes:
                    loaded = trimesh.util.concatenate(meshes)
            # 单体mesh
            if hasattr(loaded, 'vertices') and len(loaded.vertices) > 0:
                # OpenCASCADE/cascadio默认单位为米，STEP文件为毫米
                # 检测并修正：如果extents < 1，说明是米制，需要×1000转毫米
                extents = loaded.extents
                if extents.max() < 1.0:
                    print(f'[trimesh] 检测到米制坐标(max={extents.max():.4f})，转为毫米')
                    loaded.apply_scale(1000.0)
                preview_dir = PROJECT_ROOT / "data" / "step"
                preview_dir.mkdir(parents=True, exist_ok=True)
                uid = os.urandom(4).hex()
                stl_name = f"upload_{uid}.stl"
                stl_path = preview_dir / stl_name
                loaded.export(str(stl_path))
                stl_url = f"/api/preview/{stl_name}"
                mesh_stats = _compute_mesh_stats(loaded)
                print(f'[trimesh] STEP→STL成功: {stl_name}, {len(loaded.vertices)} vertices')
            else:
                print(f'[trimesh] STEP加载后无有效mesh')
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f'[trimesh] STEP转STL失败: {e}')
    
    # STEP文本解析（提取包围盒）
    bbox = extract_bbox_from_step(str(file_path))
    if not bbox or "error" in bbox:
        # 检查是否是格式不支持的情况
        if bbox and "error" in bbox and "detected_format" in bbox:
            # 文件格式不支持，返回详细错误信息
            return JSONResponse(content={
                "error": bbox["error"],
                "detail": bbox.get("detail", ""),
                "suggestions": bbox.get("suggestions", []),
                "detected_format": bbox.get("detected_format", "unknown"),
                "file_size": bbox.get("file_size", 0),
                "file_name": file.filename,
                "supported_formats": [".step", ".stp", ".stl"],
                "disclaimer": "请使用支持的CAD格式重新导出文件。",
                "shadow_mode": True,
            }, status_code=400)
        
        # 即使STEP文本解析失败，3D预览仍可使用
        if stl_url:
            # 用trimesh mesh的bounding box作为fallback
            try:
                import trimesh as _tm
                _loaded = _tm.load(str(file_path))
                if hasattr(_loaded, 'geometry'):
                    _meshes = [m for m in _loaded.geometry.values() if hasattr(m, 'vertices') and len(m.vertices) > 0]
                    if _meshes:
                        _loaded = _tm.util.concatenate(_meshes)
                if hasattr(_loaded, 'extents'):
                    _ext = _loaded.extents
                    # 米制修正
                    if _ext.max() < 1.0:
                        _ext = _ext * 1000.0
                    bbox = {"dim_x": round(float(_ext[0]), 2), "dim_y": round(float(_ext[1]), 2), "dim_z": round(float(_ext[2]), 2)}
            except Exception:
                pass
        
        if not bbox or "error" in bbox:
            if stl_url:
                return JSONResponse(content={
                    "file_name": file.filename,
                    "bounding_box": {"x": 0, "y": 0, "z": 0},
                    "volume_mm3": 0, "volume_cm3": 0,
                    "material": material, "density_g_cm3": get_material_density(material),
                    "estimated_weight_kg": 0,
                    "conflicts": conflict_checker.check({"material": material, "surface_treatment": surface}),
                    "quote": None,
                    "stl_url": stl_url,
                    "parse_warning": "STEP包围盒解析失败，但3D预览可用",
                    "disclaimer": "包围盒 × 实体率 估算，实际重量以加工后称重为准。此结论为AI建议，仅供参考。",
                    "shadow_mode": True,
                })
            return JSONResponse(content={"error": "STEP解析失败，请确认文件格式", "detail": bbox}, status_code=400)
    
    # 体积/重量估算：优先使用 OCP B-Rep 精确体积
    density = get_material_density(material)
    if bbox.get("volume_source") == "ocp_brep" and "volume_mm3" in bbox:
        volume_mm3 = float(bbox["volume_mm3"])
        volume_cm3 = volume_mm3 / 1000
        weight_kg = (volume_cm3 * density) / 1000
        volume_source = "ocp_brep"
    else:
        # bbox估算，trimesh转换成功后会用真实体积覆盖
        volume_mm3 = estimate_volume_from_bbox(bbox)
        volume_cm3 = volume_mm3 / 1000
        weight_kg = (volume_cm3 * density) / 1000
        volume_source = "bbox_estimate"
    
    # 如果还没生成STL预览（STEP文本解析成功但trimesh没跑），再尝试一次
    if not stl_url:
        try:
            import trimesh
            loaded = trimesh.load(str(file_path))
            # Scene对象（多体STEP）→ 合并所有子mesh
            if hasattr(loaded, 'geometry'):
                meshes = [m for m in loaded.geometry.values() if hasattr(m, 'vertices') and len(m.vertices) > 0]
                if meshes:
                    loaded = trimesh.util.concatenate(meshes)
            # 单体mesh
            if hasattr(loaded, 'vertices') and len(loaded.vertices) > 0:
                # OpenCASCADE/cascadio默认单位为米，STEP文件为毫米
                # 检测并修正：如果extents < 1，说明是米制，需要×1000转毫米
                extents = loaded.extents
                if extents.max() < 1.0:
                    print(f'[trimesh] 检测到米制坐标(max={extents.max():.4f})，转为毫米')
                    loaded.apply_scale(1000.0)
                # 用trimesh真实体积替换bbox估算
                try:
                    if loaded.is_watertight and loaded.is_volume:
                        real_vol = abs(loaded.volume)  # mm³
                        if real_vol > 0:
                            volume_mm3 = real_vol
                            volume_cm3 = real_vol / 1000
                            weight_kg = (volume_cm3 * density) / 1000
                            volume_source = "trimesh_volume"
                            print(f'[trimesh] 使用真实体积: {volume_cm3:.2f} cm³ (替代bbox估算)')
                    else:
                        print(f'[trimesh] mesh非水密(watertight={loaded.is_watertight})，保留bbox估算')
                except Exception as ve:
                    print(f'[trimesh] 体积计算异常: {ve}，保留bbox估算')
                preview_dir = PROJECT_ROOT / "data" / "step"
                preview_dir.mkdir(parents=True, exist_ok=True)
                uid = os.urandom(4).hex()
                stl_name = f"upload_{uid}.stl"
                stl_path = preview_dir / stl_name
                loaded.export(str(stl_path))
                stl_url = f"/api/preview/{stl_name}"
                mesh_stats = _compute_mesh_stats(loaded)
                print(f'[trimesh] STEP→STL成功(fallback): {stl_name}')
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f'[trimesh] STEP转STL失败(fallback): {e}')
    
    # 报价 (v3.0: pass full params)
    # 估算加工时间: 基于体积和工艺
    est_hours = quote_adapter.estimate_machining_hours(
        weight_kg, process, shape="flat", tolerance=tolerance
    )
    quote_params = {
        "material": material, "surface_treatment": surface,
        "quantity": quantity, "weight_kg": round(weight_kg, 3),
        "volume_cm3": round(volume_cm3, 2),
        "tolerance": tolerance, "process": process,
        "bounding_box": [bbox["dim_x"], bbox["dim_y"], bbox["dim_z"]],
        # v3.0 新增
        "machining_hours": round(est_hours, 2),
        "pricing_mode": "by_quantity" if quantity <= 20 else "by_weight",
        "profit_rate": 0.30,
    }
    
    # 冲突检查
    conflicts = conflict_checker.check({"material": material, "surface_treatment": surface})
    
    # 调用报价引擎 (使用quote_with_reasoning获取推理链)
    if conflicts["valid"]:
        quote_result = quote_adapter.quote_with_reasoning(quote_params)
        reasoning_chain = quote_result.pop('reasoning_chain', None)
        quote_result.pop('reasoning_chain_id', None)
    else:
        quote_result = None
        reasoning_chain = None
    
    result = {
        "file_name": file.filename,
        "bounding_box": {"x": bbox["dim_x"], "y": bbox["dim_y"], "z": bbox["dim_z"]},
        "volume_mm3": round(volume_mm3, 0),
        "volume_cm3": round(volume_cm3, 2),
        "material": material, "density_g_cm3": density,
        "estimated_weight_kg": round(weight_kg, 3),
        "conflicts": conflicts,
        "quote": quote_result,
        "reasoning_chain": reasoning_chain,  # 包含推理链
        "stl_url": stl_url,
        "mesh_stats": mesh_stats,  # STL详细统计 (watertight/volume/area/vertex/face)
        "volume_source": volume_source,
        "disclaimer": "包围盒 × 实体率 估算，实际重量以加工后称重为准。此结论为AI建议，仅供参考。" if volume_source == "bbox_estimate" else "此结论为AI建议，仅供参考。实际加工前请人工确认。",
        "shadow_mode": True,
    }
    audit.log(task_id=f"upload-{os.urandom(3).hex()}", event_type="step_upload_quote", data=result)
    return JSONResponse(content=result)

# ══════════════════════════════════════════════════════════════════════
# ★ v12.0-fusion: 通用上传 /api/upload — 多文件类型解析器
# 支持: STEP/STL/DWG/DXF/PDF/PNG/JPG/BMP/WEBP/ZIP/XLSX
# ══════════════════════════════════════════════════════════════════════

# ── 配置加载 (禁止硬编码 PREFERENCE_10) ──
def _load_vlm_config() -> dict:
    """加载多模态VLM配置 — 优先环境变量, 次选 config/models.json, 末选安全默认。"""
    vlm_cfg = {}
    try:
        _cfg_path = PROJECT_ROOT / "config" / "models.json"
        with open(_cfg_path, encoding="utf-8") as _f:
            vlm_cfg = json.load(_f).get("vlm", {}) or {}
    except Exception:
        pass
    return {
        "api_url": os.environ.get("VLM_API_URL", vlm_cfg.get("api_url", "http://127.0.0.1:1234/v1")),
        "model_id": os.environ.get("VLM_MODEL_ID", vlm_cfg.get("model_id", "minicpm-v-4_5")),
        "api_key": os.environ.get("VLM_API_KEY", vlm_cfg.get("api_key", "lm-studio")),
        "max_tokens": int(os.environ.get("VLM_MAX_TOKENS", vlm_cfg.get("max_tokens", 800))),
    }


def _load_upload_config() -> dict:
    """加载通用上传端点配置 (zip递归深度/文件数上限/VLM提示词)。"""
    up_cfg = {}
    try:
        _cfg_path = PROJECT_ROOT / "config" / "models.json"
        with open(_cfg_path, encoding="utf-8") as _f:
            up_cfg = json.load(_f).get("upload", {}) or {}
    except Exception:
        pass
    return {
        "max_zip_depth": int(os.environ.get("UPLOAD_MAX_ZIP_DEPTH", up_cfg.get("max_zip_depth", 3))),
        "max_zip_files": int(os.environ.get("UPLOAD_MAX_ZIP_FILES", up_cfg.get("max_zip_files", 50))),
        "vlm_prompt": os.environ.get("UPLOAD_VLM_PROMPT",
            up_cfg.get("vlm_prompt", "提取图纸中的零件参数，只输出JSON: {part_type,params:{od,id,thickness,bolt_holes,bolt_d,bolt_pcd},material,quantity}")),
    }


# ── 正则参数提取 (复用 _legacy_extract_cad_spec 正则逻辑, 不依赖 cad_chain) ──
def _regex_extract_part_params(text: str):
    """从文本中用正则提取零件参数 (中文+英文+φ标注)。
    返回 (part_type, params) — part_type 默认 flange。"""
    import re
    if not text:
        return "flange", {"od": 100, "id": 50, "thickness": 20}
    msg_lower = text.lower()
    part_type = "flange"
    type_map = {"法兰": "flange", "轴套": "sleeve", "轴": "shaft", "箱体": "box",
                "支架": "bracket", "板": "plate", "方块": "box", "检查盖": "flange", "法兰盖": "flange",
                "闷盖": "flange", "盖": "flange", "圆盘": "flange", "轮": "gear", "齿轮": "shaft",
                "flange": "flange", "sleeve": "sleeve", "shaft": "shaft",
                "gear": "shaft", "box": "box", "bracket": "bracket",
                "plate": "plate", "block": "box", "cover": "flange", "disc": "flange"}
    for pt in list(type_map.keys()):
        if pt in msg_lower:
            part_type = type_map[pt]
            break
    params = {"od": 100, "id": 50, "thickness": 20}
    od_m = re.search(r'外径\s*(\d+)', text) or re.search(r'od\s*(\d+)', msg_lower) or re.search(r'outer\s*(\d+)', msg_lower)
    id_m = re.search(r'内径\s*(\d+)', text) or re.search(r'id\s*(\d+)', msg_lower) or re.search(r'inner\s*(\d+)', msg_lower) \
        or re.search(r'(?:中心孔|内孔|中孔)\s*(?:径|直径)?\s*(?:为|是)?\s*(\d+(?:\.\d+)?)', text)
    th_m = re.search(r'厚\s*(\d+)', text) or re.search(r'厚度\s*(\d+)', text) or re.search(r'th\s*(\d+)', msg_lower) or re.search(r'thickness\s*(\d+)', msg_lower)
    wxh_m = re.search(r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)', text)
    d_m = re.search(r'直径\s*(\d+)', text) or re.search(r'd\s*(\d+)', msg_lower)
    l_m = re.search(r'长\s*(\d+)', text) or re.search(r'l\s*(\d+)', msg_lower) or re.search(r'length\s*(\d+)', msg_lower)
    holes_m = re.search(r'(\d+)\s*[个只]\s*[Mm]?\d*\s*(?:安装孔|螺栓孔|光孔|孔)', text) or re.search(r'bolt[_\s]*holes?\s*(\d+)', msg_lower)
    holes_m2 = re.search(r'(\d+)\s*[×xX*]\s*[φΦ∅]?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:通孔|孔|螺栓孔)', text)
    bolt_d_m = re.search(r'(?:孔径|螺栓径|bolt[_\s]*d)\s*(\d+)', msg_lower) or re.search(r'm(\d+)\s*(?:螺栓|bolt)', msg_lower)
    pcd_m = re.search(r'(?:PCD|分布圆|分度圆)\s*(\d+)', text, re.I)
    phi_m = re.search(r'[φΦ∅]\s*(\d+(?:\.\d+)?)', text)  # φ标注: "φ120"→直径120

    if od_m: params["od"] = int(od_m.group(1))
    if id_m: params["id"] = int(float(id_m.group(1)))
    if th_m: params["thickness"] = int(th_m.group(1))
    if wxh_m:
        params["w"] = int(wxh_m.group(1)); params["h"] = int(wxh_m.group(2)); params["t"] = int(wxh_m.group(3))
    if d_m:
        params["d"] = int(d_m.group(1))
        if part_type == "flange":
            params["od"] = int(d_m.group(1))
    if phi_m and "od" not in params and part_type in ("flange", "sleeve", "shaft"):
        params["od"] = float(phi_m.group(1))
    if l_m: params["length"] = int(l_m.group(1))
    if holes_m: params["bolt_holes"] = int(holes_m.group(1))
    elif holes_m2:
        params["bolt_holes"] = int(holes_m2.group(1))
        params["bolt_d"] = float(holes_m2.group(2))
    if bolt_d_m: params["bolt_d"] = int(bolt_d_m.group(1))
    if pcd_m: params["bolt_pcd"] = int(pcd_m.group(1))
    if "bolt_holes" in params and "bolt_pcd" not in params:
        params["bolt_pcd"] = round(params.get("od", 100) * 0.75)
    if "bolt_holes" in params and "bolt_d" not in params:
        params["bolt_d"] = 8
    return part_type, params


def _build_part_spec_from_text(text: str, source_label: str = "正则") -> dict:
    """从文本提取 part_spec (正则优先, LLM增强)。
    返回 {part_type, params, material, quantity, surface_treatment} 或 None。"""
    # 1. 正则提取
    part_type, params = _regex_extract_part_params(text)
    # 2. LLM增强 (如果AI可用, 用 llm_extract_part_spec 从文本提取)
    llm_spec = None
    if _ai_available:
        try:
            llm_spec, _raw, _meta = llm_extract_part_spec(text, temperature=0.1)
        except Exception as _e:
            print(f"[UPLOAD] LLM提取失败({source_label}): {_e}")
    if llm_spec:
        # LLM值优先, 正则回填缺失项
        part_type = llm_spec["part_type"]
        params = dict(llm_spec["params"])
        _pt, _pp = _regex_extract_part_params(text)
        for _k, _v in _pp.items():
            if _k not in params:
                params[_k] = _v
        return {"part_type": part_type, "params": params,
                "material": llm_spec.get("material"), "quantity": llm_spec.get("quantity"),
                "surface_treatment": llm_spec.get("surface_treatment")}
    # 3. 仅正则
    return {"part_type": part_type, "params": params,
            "material": None, "quantity": None, "surface_treatment": None}


# ── VLM 多模态理解 (OpenAI兼容协议, urllib避免新依赖) ──
def _vlm_understand_image(image_path: str, prompt: str = None) -> dict:
    """调用多模态VLM理解图片, 返回 {text, part_spec, error?}。
    依赖: config/models.json vlm块 或环境变量。失败返回 {error}。"""
    import base64
    import urllib.request
    vlm_cfg = _load_vlm_config()
    up_cfg = _load_upload_config()
    _prompt = prompt or up_cfg["vlm_prompt"]
    # 1. PIL打开 + 统一转PNG base64
    try:
        from PIL import Image
        img = Image.open(image_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        return {"error": f"图片读取失败: {e}"}
    # 2. 构造OpenAI兼容多模态请求
    body = json.dumps({
        "model": vlm_cfg["model_id"],
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": _prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        "max_tokens": vlm_cfg["max_tokens"],
        "temperature": 0.1,
    }).encode("utf-8")
    req = urllib.request.Request(
        vlm_cfg["api_url"].rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {vlm_cfg['api_key']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return {"error": "VLM返回空内容"}
        # 解析JSON
        start = content.find("{")
        end = content.rfind("}")
        part_spec = None
        if start >= 0 and end > start:
            try:
                raw_spec = json.loads(content[start:end + 1])
                part_spec = validate_part_spec(raw_spec)
            except Exception:
                pass
        return {"text": content, "part_spec": part_spec}
    except Exception as e:
        return {"error": f"VLM调用失败({vlm_cfg['model_id']}@{vlm_cfg['api_url']}): {e}"}


# ── STL mesh 详细统计 (参考 cad-parser-stl/scripts/main.py) ──
def _compute_mesh_stats(loaded) -> dict:
    """计算 trimesh mesh 的详细统计: is_watertight/volume/surface_area/vertex/face。
    返回 None 如果 loaded 不是有效 mesh。"""
    try:
        if not hasattr(loaded, 'vertices') or len(loaded.vertices) == 0:
            return None
        stats = {
            "is_watertight": bool(getattr(loaded, 'is_watertight', False)),
            "vertex_count": len(loaded.vertices),
            "face_count": len(loaded.faces) if hasattr(loaded, 'faces') else 0,
        }
        # 体积 (mm³→cm³) 和表面积 (mm²) — 仅水密mesh有有意义体积
        if hasattr(loaded, 'volume') and stats["is_watertight"]:
            stats["volume_cm3"] = round(abs(float(loaded.volume)) / 1000, 3)
        else:
            stats["volume_cm3"] = None
        if hasattr(loaded, 'area'):
            stats["surface_area_mm2"] = round(float(loaded.area), 2)
        else:
            stats["surface_area_mm2"] = None
        return stats
    except Exception as e:
        print(f"[MESH-STATS] 计算失败: {e}")
        return None


# ── 解析器1: DWG/DXF (ezdxf) ──
def _parse_dwg_dxf(file_path: str) -> dict:
    """DWG/DXF解析 — 优先dwgread(libredwg)解析DWG原生格式, 降级ezdxf(仅DXF)。
    缺失依赖时优雅降级, 返回warning而非崩溃。参考 cad-parser-dwg/scripts/main.py。"""
    import shutil as _sh
    from pathlib import Path as _Path
    fp = _Path(file_path)
    is_dwg = fp.suffix.lower() == ".dwg"

    # DWG文件: 优先尝试dwgread(libredwg命令行, 禁止硬编码路径用shutil.which检测)
    if is_dwg and _sh.which("dwgread"):
        try:
            import subprocess
            result = subprocess.run(["dwgread", "-j", str(file_path)],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                dwg_data = json.loads(result.stdout)
                entities = dwg_data.get("entities", [])
                entity_counts = {}
                text_pieces = []
                diameters = []
                for ent in entities:
                    etype = ent.get("entity", "UNKNOWN")
                    entity_counts[etype] = entity_counts.get(etype, 0) + 1
                    if etype in ("TEXT", "MTEXT"):
                        txt = ent.get("text", "")
                        if txt and txt.strip():
                            text_pieces.append(txt.strip())
                    if etype == "CIRCLE":
                        r = ent.get("radius", 0)
                        if r:
                            diameters.append(r * 2)
                extracted_text = " | ".join(text_pieces[:100])
                part_spec = _build_part_spec_from_text(extracted_text, source_label="DWG文字") if extracted_text.strip() else None
                n_entities = len(entities)
                reasoning = f"dwgread(libredwg)解析{n_entities}个实体; 文字{len(text_pieces)}段, 圆{len(diameters)}个"
                return {"file_type": "dwg", "extracted_text": extracted_text,
                        "part_spec": part_spec, "confidence": 0.8, "reasoning": reasoning,
                        "entity_counts": entity_counts, "parser": "dwgread",
                        "diameters": [round(d, 2) for d in diameters[:20]]}
            else:
                print(f"[DWG] dwgread返回非0({result.returncode}): {(result.stderr or '')[:200]}")
        except Exception as e:
            print(f"[DWG] dwgread解析失败，降级ezdxf: {e}")

    # 降级: ezdxf (仅支持DXF, 不支持DWG)
    try:
        import ezdxf
    except ImportError:
        if is_dwg:
            return {"file_type": "dwg", "extracted_text": "", "part_spec": None,
                    "confidence": 0.0, "reasoning": "ezdxf未安装且dwgread不可用",
                    "error": "DWG解析需要ezdxf+dwgread，两者均不可用",
                    "warning": "DWG格式需要libredwg(dwgread)命令行工具，当前未安装。可安装libredwg-tools后启用DWG原生解析。"}
        return {"file_type": "dwg", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": "ezdxf未安装，无法解析DWG/DXF",
                "error": "ezdxf未安装，无法解析DWG/DXF"}

    # ezdxf不支持DWG格式 — 返回warning
    if is_dwg:
        return {"file_type": "dwg", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": "ezdxf不支持DWG格式(仅DXF), dwgread未安装",
                "warning": "DWG格式需要libredwg(dwgread)命令行工具，当前未安装，仅支持DXF。可安装libredwg-tools后启用DWG原生解析。",
                "error": "DWG格式需要libredwg(dwgread)命令行工具"}

    try:
        doc = ezdxf.readfile(file_path)
        msp = doc.modelspace()
        entity_counts = {"CIRCLE": 0, "LINE": 0, "ARC": 0, "LWPOLYLINE": 0,
                         "DIMENSION": 0, "TEXT": 0, "MTEXT": 0}
        text_pieces = []
        diameters = []
        radii = []
        for ent in msp:
            etype = ent.dxftype()
            if etype in entity_counts:
                entity_counts[etype] += 1
            if etype == "CIRCLE":
                r = ent.dxf.radius
                radii.append(r)
                diameters.append(r * 2)
            elif etype in ("TEXT", "MTEXT"):
                try:
                    txt = ent.dxf.text if etype == "TEXT" else ent.text
                    if txt and txt.strip():
                        text_pieces.append(txt.strip())
                except Exception:
                    pass
        # 汇总标注文字
        extracted_text = " | ".join(text_pieces[:100])
        # 从圆直径推断 od (取最大直径)
        params = {}
        if diameters:
            max_od = max(diameters)
            params["od"] = round(max_od, 2)
            if len(diameters) >= 2:
                sorted_d = sorted(diameters, reverse=True)
                params["id"] = round(sorted_d[1], 2)  # 第二大圆→内孔
        # 正则从标注文字提取参数 (φ标注/厚度/孔数等)
        pt_from_text, pp_from_text = _regex_extract_part_params(extracted_text)
        # 合并: 圆几何优先, 正则补缺
        merged_params = {"od": 100, "id": 50, "thickness": 20}
        merged_params.update(pp_from_text)
        merged_params.update(params)
        part_spec = {"part_type": pt_from_text, "params": merged_params,
                     "material": None, "quantity": None, "surface_treatment": None}
        n_entities = sum(entity_counts.values())
        reasoning = f"ezdxf解析{n_entities}个实体(圆{entity_counts['CIRCLE']}/线{entity_counts['LINE']}/弧{entity_counts['ARC']}/文字{entity_counts['TEXT']+entity_counts['MTEXT']}); 从{len(diameters)}个圆推断直径, 从{len(text_pieces)}段文字提取标注"
        return {"file_type": "dwg", "extracted_text": extracted_text,
                "part_spec": part_spec, "confidence": 0.75, "reasoning": reasoning,
                "entity_counts": entity_counts, "parser": "ezdxf",
                "diameters": [round(d, 2) for d in diameters[:20]]}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"file_type": "dwg", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"ezdxf解析异常: {e}",
                "error": f"DWG/DXF解析失败: {e}"}


# ── 解析器2: PDF (pdfplumber + 表单结构 + OCR/VLM降级) ──
def _parse_pdf(file_path: str) -> dict:
    """pdfplumber提取PDF文字+表单结构(labels/lines/checkboxes) + LLM理解 → part_spec。
    文字不足时降级链: tesseract OCR → pdf2image+VLM多模态。
    参考 suntime-pdf/extract_form_structure.py 的表单结构提取逻辑。"""
    try:
        import pdfplumber
    except ImportError:
        return {"file_type": "pdf", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": "pdfplumber未安装，无法解析PDF",
                "error": "pdfplumber未安装，无法解析PDF"}
    try:
        text_pieces = []
        n_pages = 0
        # 表单结构提取（参考 suntime-pdf/extract_form_structure.py）
        form_structure = {"labels": [], "lines": [], "checkboxes": [], "row_boundaries": []}
        with pdfplumber.open(file_path) as pdf:
            n_pages = len(pdf.pages)
            for page in pdf.pages[:20]:  # 最多20页
                # 文字提取
                try:
                    txt = page.extract_text() or ""
                    if txt.strip():
                        text_pieces.append(txt.strip())
                except Exception:
                    pass
                # 表单结构提取 (独立try, 失败不影响文字)
                try:
                    words = page.extract_words()
                    for w in words:
                        form_structure["labels"].append({
                            "text": w["text"],
                            "x0": round(float(w["x0"]), 1),
                            "top": round(float(w["top"]), 1)})
                    for line in page.lines:
                        if abs(float(line["x1"]) - float(line["x0"])) > page.width * 0.5:
                            form_structure["lines"].append({"y": round(float(line["top"]), 1)})
                    for rect in page.rects:
                        rw = float(rect["x1"]) - float(rect["x0"])
                        rh = float(rect["bottom"]) - float(rect["top"])
                        if 5 <= rw <= 15 and 5 <= rh <= 15 and abs(rw - rh) < 2:
                            form_structure["checkboxes"].append({
                                "cx": round((float(rect["x0"]) + float(rect["x1"])) / 2, 1),
                                "cy": round((float(rect["top"]) + float(rect["bottom"])) / 2, 1)})
                except Exception:
                    pass  # 表单结构提取失败不影响文字提取
        extracted_text = "\n".join(text_pieces)
        # 正则+LLM提取参数
        part_spec = None
        if extracted_text.strip():
            part_spec = _build_part_spec_from_text(extracted_text, source_label="PDF文字")
        # 文字不足 → 降级链: OCR(tesseract) → VLM多模态
        ocr_note = None
        vlm_note = None
        if not extracted_text.strip() or len(extracted_text) < 50:
            # OCR降级: 检测tesseract命令行工具(禁止硬编码路径, 用shutil.which)
            try:
                import shutil as _sh
                if _sh.which("tesseract"):
                    import pytesseract  # 需 pip install pytesseract
                    from pdf2image import convert_from_path
                    images = convert_from_path(file_path, dpi=200, first_page=1, last_page=5)
                    ocr_text = "\n".join(pytesseract.image_to_string(img, lang="chi_sim+eng") for img in images)
                    if ocr_text.strip():
                        extracted_text = ocr_text
                        ocr_note = "tesseract OCR(扫描版PDF)"
                        if not part_spec:
                            part_spec = _build_part_spec_from_text(extracted_text, source_label="OCR文字")
                else:
                    ocr_note = "tesseract未安装，跳过OCR"
            except ImportError:
                ocr_note = "pytesseract/pdf2image未安装，跳过OCR"
            except Exception as _oe:
                ocr_note = f"OCR失败: {_oe}"
            # VLM多模态 (OCR未果或文字仍少时)
            if (not extracted_text.strip() or len(extracted_text) < 30) and not (ocr_note and "tesseract OCR" in ocr_note):
                try:
                    from pdf2image import convert_from_path
                    images = convert_from_path(file_path, first_page=1, last_page=1, dpi=150)
                    if images:
                        tmp_png = file_path + ".page1.png"
                        images[0].save(tmp_png, "PNG")
                        vlm_result = _vlm_understand_image(tmp_png)
                        if "error" not in vlm_result:
                            extracted_text = vlm_result.get("text", extracted_text)
                            if vlm_result.get("part_spec"):
                                part_spec = vlm_result["part_spec"]
                            vlm_note = "pdf2image渲染+VLM多模态理解成功"
                        else:
                            vlm_note = f"VLM理解失败: {vlm_result['error']}"
                        try: os.remove(tmp_png)
                        except Exception: pass
                except ImportError:
                    if not vlm_note:
                        vlm_note = "pdf2image未安装，跳过PDF视觉理解(仅文字提取)"
                except Exception as e:
                    vlm_note = f"PDF渲染失败: {e}"
        reasoning = f"pdfplumber提取{n_pages}页文字({len(extracted_text)}字符)"
        if ocr_note:
            reasoning += f" → {ocr_note}"
        if vlm_note:
            reasoning += f"; {vlm_note}"
        confidence = 0.7 if part_spec else 0.3
        result = {"file_type": "pdf", "extracted_text": extracted_text[:5000],
                  "part_spec": part_spec, "confidence": confidence, "reasoning": reasoning,
                  "n_pages": n_pages}
        # 表单结构 (仅当有labels或checkboxes时返回, 限长避免响应过大)
        if form_structure["labels"] or form_structure["checkboxes"]:
            result["form_structure"] = {
                "labels": form_structure["labels"][:200],
                "lines": form_structure["lines"][:50],
                "checkboxes": form_structure["checkboxes"][:50],
                "label_count": len(form_structure["labels"]),
                "checkbox_count": len(form_structure["checkboxes"]),
            }
        return result
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"file_type": "pdf", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"PDF解析异常: {e}",
                "error": f"PDF解析失败: {e}"}


# ── 解析器3: 图片 (PIL + VLM多模态) ──
def _parse_image(file_path: str) -> dict:
    """PIL预处理 + minicpm-v-4_5 VLM多模态理解图片→part_spec。"""
    try:
        from PIL import Image
        img = Image.open(file_path)
        w, h = img.size
        fmt = img.format or "UNKNOWN"
    except Exception as e:
        return {"file_type": "image", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"图片读取失败: {e}",
                "error": f"图片读取失败: {e}"}
    try:
        up_cfg = _load_upload_config()
        vlm_result = _vlm_understand_image(file_path, up_cfg["vlm_prompt"])
        if "error" in vlm_result:
            return {"file_type": "image", "extracted_text": "",
                    "part_spec": None, "confidence": 0.0,
                    "reasoning": f"VLM理解失败: {vlm_result['error']}",
                    "image_size": [w, h], "image_format": fmt,
                    "error": vlm_result["error"]}
        content = vlm_result.get("text", "")
        part_spec = vlm_result.get("part_spec")
        # VLM未返回有效JSON → 用正则从VLM文本提取
        if not part_spec and content:
            part_spec = _build_part_spec_from_text(content, source_label="VLM文本")
        confidence = 0.8 if part_spec else 0.4
        reasoning = f"PIL读取({w}x{h} {fmt}) + VLM多模态理解({len(content)}字符)"
        return {"file_type": "image", "extracted_text": content[:3000],
                "part_spec": part_spec, "confidence": confidence, "reasoning": reasoning,
                "image_size": [w, h], "image_format": fmt}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"file_type": "image", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"图片解析异常: {e}",
                "image_size": [w, h], "image_format": fmt,
                "error": f"图片解析失败: {e}"}


# ── 解析器4: ZIP (zipfile递归) ──
def _parse_zip(file_path: str, depth: int = 0) -> dict:
    """zipfile解压 + 递归处理内部文件。汇总所有子结果, 取第一个有效part_spec。"""
    try:
        import zipfile
        import tempfile
    except ImportError:
        return {"file_type": "zip", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": "zipfile不可用",
                "error": "zipfile不可用"}
    up_cfg = _load_upload_config()
    if depth >= up_cfg["max_zip_depth"]:
        return {"file_type": "zip", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"递归深度超限({depth}>={up_cfg['max_zip_depth']})"}
    try:
        sub_results = []
        first_part_spec = None
        n_files = 0
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                n_files = len(names)
                if n_files > up_cfg["max_zip_files"]:
                    names = names[:up_cfg["max_zip_files"]]
                for name in names:
                    if name.endswith("/"):
                        continue  # 目录
                    try:
                        zf.extract(name, tmp_dir)
                        inner_path = os.path.join(tmp_dir, name)
                        sub = _dispatch_file_parser(inner_path, depth=depth + 1)
                        sub["inner_name"] = name
                        sub_results.append(sub)
                        if not first_part_spec and sub.get("part_spec"):
                            first_part_spec = sub["part_spec"]
                    except Exception as _e:
                        sub_results.append({"inner_name": name, "error": str(_e),
                                            "file_type": "unknown", "part_spec": None})
        # 汇总文字
        all_text = " | ".join(s.get("extracted_text", "") for s in sub_results if s.get("extracted_text"))
        n_ok = sum(1 for s in sub_results if s.get("part_spec"))
        reasoning = f"ZIP含{n_files}个文件, 递归解析{len(sub_results)}个, {n_ok}个提取到part_spec"
        return {"file_type": "zip", "extracted_text": all_text[:5000],
                "part_spec": first_part_spec, "confidence": 0.65 if first_part_spec else 0.2,
                "reasoning": reasoning, "sub_results": sub_results, "n_files": n_files}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"file_type": "zip", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"ZIP解析异常: {e}",
                "error": f"ZIP解析失败: {e}"}


# ── 解析器5: XLSX/XLS (openpyxl BOM) ──
def _parse_xlsx(file_path: str) -> dict:
    """openpyxl解析XLSX BOM表 — 提取表头+数据行, 识别零件参数。"""
    try:
        import openpyxl
    except ImportError:
        return {"file_type": "xlsx", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": "openpyxl未安装，无法解析XLSX",
                "error": "openpyxl未安装，无法解析XLSX"}
    try:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheets_data = []
        all_text_pieces = []
        for ws in wb.worksheets[:10]:  # 最多10个sheet
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > 200:
                    break  # 每sheet最多200行
                cells = [str(c) if c is not None else "" for c in row]
                rows.append(cells)
                all_text_pieces.append(" ".join(cells))
            sheets_data.append({"sheet": ws.title, "n_rows": len(rows), "rows": rows[:30]})
        wb.close()
        extracted_text = "\n".join(all_text_pieces)[:8000]
        # 从BOM文字提取part_spec
        part_spec = _build_part_spec_from_text(extracted_text, source_label="XLSX BOM")
        reasoning = f"openpyxl解析{len(sheets_data)}个sheet, {len(all_text_pieces)}行数据"
        return {"file_type": "xlsx", "extracted_text": extracted_text,
                "part_spec": part_spec, "confidence": 0.6, "reasoning": reasoning,
                "sheets": sheets_data}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"file_type": "xlsx", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"XLSX解析异常: {e}",
                "error": f"XLSX解析失败: {e}"}


# ── 文件类型分发器 (供 /api/upload 和 _parse_zip 递归调用) ──
_STEP_EXTS = (".step", ".stp", ".stl")
_DWG_EXTS = (".dwg", ".dxf")
_PDF_EXTS = (".pdf",)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
_ZIP_EXTS = (".zip",)
_XLSX_EXTS = (".xlsx", ".xls")


def _dispatch_file_parser(file_path: str, depth: int = 0) -> dict:
    """根据文件扩展名分发到对应解析器。返回统一结构。
    STEP/STL在此不解析几何(由 /api/upload 主流程处理trimesh), 仅标记类型。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _STEP_EXTS:
        return {"file_type": "step", "extracted_text": f"STEP/STL文件: {os.path.basename(file_path)}",
                "part_spec": None, "confidence": 0.5,
                "reasoning": "STEP/STL文件, 由主流程trimesh解析几何"}
    if ext in _DWG_EXTS:
        return _parse_dwg_dxf(file_path)
    if ext in _PDF_EXTS:
        return _parse_pdf(file_path)
    if ext in _IMAGE_EXTS:
        return _parse_image(file_path)
    if ext in _ZIP_EXTS:
        return _parse_zip(file_path, depth=depth)
    if ext in _XLSX_EXTS:
        return _parse_xlsx(file_path)
    # 未知类型 → 尝试作为文本读取
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as _f:
            txt = _f.read(5000)
        part_spec = _build_part_spec_from_text(txt, source_label="未知文本") if txt.strip() else None
        return {"file_type": "unknown", "extracted_text": txt, "part_spec": part_spec,
                "confidence": 0.3, "reasoning": f"未知扩展名{ext}, 尝试作为文本读取"}
    except Exception:
        return {"file_type": "unknown", "extracted_text": "", "part_spec": None,
                "confidence": 0.0, "reasoning": f"未知扩展名{ext}, 二进制文件无法解析"}


# ── ★ API: 通用上传 /api/upload (多文件类型) ──
@app.post("/api/upload")
async def upload_universal(file: UploadFile = File(...), material: str = Form("6061"),
                           quantity: int = Form(10), surface: str = Form("无"),
                           tolerance: str = Form("IT8"), process: str = Form("三轴CNC")):
    """通用上传端点 — 根据文件扩展名分发到对应解析器:
    STEP/STL→trimesh几何 | DWG/DXF→ezdxf | PDF→pdfplumber+LLM
    | 图片→PIL+VLM多模态 | ZIP→递归 | XLSX→openpyxl BOM
    提取part_spec后走 generate_part 生成STEP+报价。"""
    # 1. 保存上传文件
    upload_dir = PROJECT_ROOT / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    uid_prefix = os.urandom(3).hex()
    safe_filename = f"{uid_prefix}_{file.filename}"
    file_path = upload_dir / safe_filename
    content = await file.read()
    file_path.write_bytes(content)
    orig_name = file.filename or safe_filename
    ext = os.path.splitext(orig_name)[1].lower()
    reasoning_chain_steps = [f"文件类型识别: {ext}"]

    # 2. STEP/STL → 复用 upload_step_quote 逻辑 (trimesh几何)
    if ext in _STEP_EXTS:
        reasoning_chain_steps.append("分发: STEP/STL → trimesh几何解析")
        try:
            step_result = await upload_step_quote(file=file, material=material,
                                                  quantity=quantity, surface=surface,
                                                  tolerance=tolerance, process=process)
            # upload_step_quote 返回 JSONResponse, 解包并补充元信息
            if isinstance(step_result, JSONResponse):
                body = json.loads(step_result.body.decode("utf-8"))
                body["file_type"] = "step"
                body["reasoning_chain_upload"] = reasoning_chain_steps
                return JSONResponse(content=body, status_code=step_result.status_code)
            return step_result
        except Exception as e:
            return JSONResponse(content={"error": f"STEP处理失败: {e}",
                                         "file_type": "step"}, status_code=500)

    # 3. 其他类型 → 对应解析器
    try:
        parse_result = await run_blocking(_dispatch_file_parser, str(file_path), 0)
    except Exception as e:
        return JSONResponse(content={"error": f"解析器调度失败: {e}",
                                     "file_type": "unknown"}, status_code=500)

    file_type = parse_result.get("file_type", "unknown")
    extracted_text = parse_result.get("extracted_text", "")
    part_spec = parse_result.get("part_spec")
    parse_confidence = parse_result.get("confidence", 0.0)
    parse_reasoning = parse_result.get("reasoning", "")
    parse_error = parse_result.get("error")
    reasoning_chain_steps.append(f"解析: {parse_reasoning}")

    # 4. part_spec 校验
    validated_spec = None
    if part_spec:
        validated_spec = validate_part_spec(part_spec)
        if validated_spec:
            reasoning_chain_steps.append(
                f"参数提取成功: {validated_spec['part_type']} {json.dumps(validated_spec['params'], ensure_ascii=False)}")
        else:
            reasoning_chain_steps.append("参数提取: validate_part_spec校验失败")
    else:
        reasoning_chain_steps.append("参数提取: 无part_spec")

    # 5. 生成STEP + 报价 (如果part_spec有效)
    step_file = None
    stl_url = None
    quote = None
    gen_result = None
    if validated_spec:
        pt = validated_spec["part_type"]
        params = dict(validated_spec["params"])
        # 表单参数覆盖 (material/quantity/surface 优先用表单值)
        eff_material = material if material != "6061" else (validated_spec.get("material") or material)
        eff_quantity = quantity if quantity != 10 else (validated_spec.get("quantity") or quantity)
        eff_surface = surface if surface != "无" else (validated_spec.get("surface_treatment") or surface)
        reasoning_chain_steps.append(f"生成STEP: generate_part({pt}, {json.dumps(params, ensure_ascii=False)})")
        try:
            gen_result = await run_blocking(generate_part, pt, params)
            if gen_result and "error" not in gen_result:
                step_file = gen_result.get("step_file")
                stl_url = gen_result.get("stl_url") or gen_result.get("stl_file")
                reasoning_chain_steps.append(f"STEP生成成功: {step_file}")
                # 报价
                try:
                    volume_cm3 = gen_result.get("volume_cm3", 0)
                    weight_kg = round(get_weight(eff_material, volume_cm3) / 1000, 3) if volume_cm3 else 0
                    est_hours = quote_adapter.estimate_machining_hours(
                        weight_kg, process, shape="flat", tolerance=tolerance)
                    quote_params = {
                        "material": eff_material, "surface_treatment": eff_surface,
                        "quantity": eff_quantity, "weight_kg": weight_kg,
                        "volume_cm3": round(volume_cm3, 2),
                        "tolerance": tolerance, "process": process,
                        "bounding_box": gen_result.get("bounding_box", [0, 0, 0]),
                        "machining_hours": round(est_hours, 2),
                        "pricing_mode": "by_quantity" if eff_quantity <= 20 else "by_weight",
                        "profit_rate": 0.30,
                    }
                    conflicts = conflict_checker.check({"material": eff_material, "surface_treatment": eff_surface})
                    if conflicts["valid"]:
                        quote_result = quote_adapter.quote_with_reasoning(quote_params)
                        quote = quote_result
                        reasoning_chain_steps.append(f"报价成功: 单价={quote.get('unit_price')}, 总价={quote.get('final_price')}")
                    else:
                        reasoning_chain_steps.append(f"报价跳过: 冲突 {conflicts.get('conflicts')}")
                except Exception as qe:
                    reasoning_chain_steps.append(f"报价失败: {qe}")
            else:
                reasoning_chain_steps.append(f"STEP生成失败: {gen_result.get('error') if gen_result else '空结果'}")
        except Exception as ge:
            reasoning_chain_steps.append(f"STEP生成异常: {ge}")
            print(f"[UPLOAD] generate_part异常: {ge}")

    # 6. 构造响应
    result = {
        "file_name": orig_name,
        "file_type": file_type,
        "extracted_text": extracted_text,
        "part_spec": validated_spec,
        "part_spec_raw": part_spec,
        "confidence": parse_confidence,
        "step_file": step_file,
        "stl_url": stl_url,
        "quote": quote,
        "material": material,
        "quantity": quantity,
        "surface": surface,
        "tolerance": tolerance,
        "process": process,
        "reasoning_chain": reasoning_chain_steps,
        "parse_reasoning": parse_reasoning,
        "disclaimer": "此结论为AI建议，仅供参考。实际加工前请人工确认。",
        "shadow_mode": True,
    }
    if parse_error:
        result["parse_error"] = parse_error
    if gen_result and "volume_cm3" in gen_result:
        result["volume_cm3"] = gen_result["volume_cm3"]
    if parse_result.get("sub_results"):
        result["sub_results"] = parse_result["sub_results"]
    if parse_result.get("form_structure"):
        result["form_structure"] = parse_result["form_structure"]
    if parse_result.get("sheets"):
        result["sheets"] = parse_result["sheets"]
    audit.log(task_id=f"upload-universal-{os.urandom(3).hex()}",
              event_type="universal_upload", data=result)
    return JSONResponse(content=wrap_shadow(result))

# ── ★ API: 重新加载模块 ──
@app.post("/api/reload")
async def reload_modules():
    """重新加载关键模块（用于开发调试）"""
    import importlib
    modules_to_reload = [
        'src.runtime.export_bundler',
        'src.runtime.quote_xlsx_generator',
        'src.runtime.quote_adapter',
    ]
    
    results = []
    for module_name in modules_to_reload:
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                results.append({"module": module_name, "status": "ok"})
            else:
                results.append({"module": module_name, "status": "not_loaded"})
        except Exception as e:
            results.append({"module": module_name, "status": "error", "error": str(e)})
    
    return JSONResponse(content={"reloaded": results})

# ── ★ API: 输出打包 ──
@app.post("/api/export")
async def export_bundle(request: Request):
    try: params = await request.json()
    except: return JSONResponse(content={"error": "需要JSON参数"}, status_code=400)
    
    task_id = params.get("task_id", os.urandom(4).hex())
    files = params.get("files", [])
    quote_data = params.get("quote")
    reasoning_chain = params.get("reasoning_chain")  # 获取推理链
    metadata = params.get("metadata", {"task_id": task_id, "created": datetime.now().isoformat()})
    
    files_exist = [f for f in files if os.path.exists(f.get("path", ""))]
    result = create_bundle(task_id, files_exist, quote_data, metadata, reasoning_chain=reasoning_chain)
    audit.log(task_id=task_id, event_type="export", data=result)
    return JSONResponse(content=result)

# ── ★ API: 下载ZIP ──
@app.get("/api/download/{filename}")
async def download_zip(filename: str):
    zip_path = PROJECT_ROOT / "data" / "exports" / filename
    if not zip_path.exists():
        return JSONResponse(content={"error": "文件不存在"}, status_code=404)
    return FileResponse(zip_path, media_type="application/zip", filename=filename)

# ── ★ API: 一句话全链路 ──
@app.post("/api/one-click")
async def one_click(request: Request):
    """输入JSON参数 → 生成STEP+报价+打包ZIP，返回完整结果"""
    try:
        raw_body = await request.body()
        try:
            params = json.loads(raw_body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                params = json.loads(raw_body.decode("gbk", errors="replace"))
            except:
                params = json.loads(raw_body.decode("utf-8", errors="replace"))
    except Exception as e:
        return JSONResponse(content={"error": f"需要JSON参数: {str(e)}"}, status_code=400)
    
    part_type = params.get("part_type", "flange")
    material = params.get("material", "6061")
    quantity = params.get("quantity", 10)
    surface = params.get("surface", "无")
    
    results = {"pipeline": [], "step": 0}
    
    # Step1: 生成STEP
    gen_result = generate_part(part_type, params)
    if "error" in gen_result:
        return JSONResponse(content={"error": f"STEP生成失败: {gen_result['error']}"}, status_code=400)
    results["pipeline"].append({"step": "generate", "status": "ok", "data": gen_result})
    results["step"] = 1
    
    # Step2: 冲突检测
    conflicts = conflict_checker.check({"material": material, "surface_treatment": surface})
    results["pipeline"].append({"step": "conflict_check", "status": "ok", "data": conflicts})
    results["step"] = 2
    
    # Step3: 报价 (使用quote_with_reasoning获取推理链)
    quote_params = {"material": material, "surface_treatment": surface, "quantity": quantity}
    if "volume_cm3" in gen_result:
        quote_params["weight_kg"] = round(get_weight(material, gen_result["volume_cm3"]) / 1000, 3)
    
    if conflicts["valid"]:
        # 使用quote_with_reasoning获取带推理链的报价
        quote_result = quote_adapter.quote_with_reasoning(quote_params)
        # 提取推理链
        reasoning_chain = quote_result.pop('reasoning_chain', None)
        quote_result.pop('reasoning_chain_id', None)
        results["pipeline"].append({"step": "quote", "status": "ok", "data": quote_result})
    else:
        quote_result = None
        reasoning_chain = None
        conflict_msgs = [c["message"] for c in conflicts.get("conflicts", [])]
        results["pipeline"].append({"step": "quote", "status": "blocked", "reason": "; ".join(conflict_msgs)})
    results["step"] = 3
    
    # Step4: 打包 (有文件且无冲突，包含推理链)
    if gen_result.get("step_file") and quote_result:
        bundle_files = [
            {"path": gen_result["step_file"], "name": f"{part_type}.step"},
        ]
        if gen_result.get("stl_file"):
            bundle_files.append({"path": gen_result["stl_file"], "name": f"{part_type}.stl"})
        
        # 创建带推理链的bundle
        bundle = create_bundle(
            os.urandom(4).hex(), 
            bundle_files,
            quote_data={
                "material": material, 
                "quantity": quantity,
                "surface_treatment": surface,
                "surface": surface,
                "unit_price": quote_result.get("unit_price"),
                "final_price": quote_result.get("final_price"),
                "total_price": quote_result.get("final_price"),
                # 传递完整报价数据用于专业报价单
                "material_code": quote_result.get("material_code", material),
                "material_price": quote_adapter.materials.get(material, {}).get("price_kg", 30),
                "process": quote_result.get("process", "三轴CNC"),
                "weight_kg": quote_result.get("weight_kg", 0),
                "machine_hours": quote_result.get("machine_hours", 0),
                "hourly_rate": quote_result.get("hourly_rate", 120),
                "material_cost": quote_result.get("material_cost", 0),
                "machining_cost": quote_result.get("machining_cost", 0),
                "surface_cost": quote_result.get("surface_cost", 0),
                "extra_fees": quote_result.get("extra_fees", 0),
                "total_cost": quote_result.get("total_cost", 0),
                "profit": quote_result.get("profit", 0),
                "profit_rate": quote_result.get("profit_rate", 0.3),
                "discount": quote_result.get("discount", 1.0),
                "tolerance": quote_result.get("tolerance", "IT8"),
                "tol_coef": quote_result.get("tol_coef", 1.0),
                "roughness": quote_result.get("roughness", "Ra1.6"),
                "rough_coef": quote_result.get("rough_coef", 1.0),
                "shape": quote_result.get("shape", "flat"),
                "measurement_fee": quote_result.get("measurement_fee", 0),
                "jig_fee": quote_result.get("jig_fee", 0),
                "tool_fee": quote_result.get("tool_fee", 0),
                "pricing_mode": quote_result.get("pricing_mode", "by_quantity"),
                "lead_time_days": quote_result.get("lead_time_days", 7),
                "confidence": quote_result.get("confidence", 0.95),
            },
            metadata={"part_type": part_type, "params": params},
            reasoning_chain=reasoning_chain  # 传递推理链
        )
        results["pipeline"].append({"step": "export", "status": "ok", "data": bundle})
        results["zip_url"] = bundle.get("zip_url")
        results["has_reasoning"] = reasoning_chain is not None
    results["step"] = 4
    
    # Step5: 3D预览URL
    if gen_result.get("stl_url"):
        results["preview_url"] = gen_result["stl_url"]
    
    results["disclaimer"] = "此结论为AI建议，仅供参考。实际加工前请人工确认。"
    results["shadow_mode"] = True
    results["version"] = VERSION
    
    audit.log(task_id=f"oneclick-{os.urandom(4).hex()}", event_type="one_click", data={"params": params, "pipeline_count": len(results["pipeline"])})
    return JSONResponse(content=results)

# ── API: 演示 ──
@app.get("/api/demo")
async def demo():
    scenes = [
        ("S1: STEP生成", "generate"),
        ("S2: 常规报价", "quote"),
        ("S3: 冲突阻断", "conflict"),
        ("S4: 上传STEP报价", "upload"),
        ("S5: 专家会议", "panel"),
    ]
    results = []
    for name, stype in scenes:
        try:
            if stype == "generate":
                r = generate_part("flange", {"od": 100, "id": 50, "thickness": 20})
                results.append({"scene": name, "status": "ok" if "error" not in r else "error",
                               "preview": r.get("stl_url", ""), "bbox": r.get("bounding_box_mm", [])})
            elif stype == "quote":
                r = quote_adapter.quote({"material": "6061", "surface_treatment": "阳极氧化", "quantity": 50})
                results.append({"scene": name, "status": "ok", "price": r.get("final_price", 0)})
            elif stype == "conflict":
                r = conflict_checker.check({"material": "304", "surface_treatment": "阳极氧化", "quantity": 30})
                results.append({"scene": name, "status": "blocked" if not r["valid"] else "ok", "data": r})
            elif stype == "upload":
                results.append({"scene": name, "status": "api_ready",
                               "endpoint": "POST /api/upload-step (multipart)"})
            elif stype == "panel":
                triggers = detect_triggers("钛合金TC4 IT5 预算50000 能接吗")
                results.append({"scene": name, "status": "panel_triggered" if triggers else "no_trigger",
                               "triggers": triggers})
        except Exception as e:
            results.append({"scene": name, "status": "error", "error": str(e)})
    return JSONResponse(content={"title": f"v{VERSION} 演示模式", "scenes": results})

# ── API: 仪表盘 ──
@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard(): return HTMLResponse(content=HTML_DASHBOARD)

# ── 对话 ──
@app.post("/api/chat")
async def chat(request: Request):
    try:
        raw_body = await request.body()
        # 尝试 UTF-8 解码，失败则尝试 GBK（Windows curl 兼容）
        try:
            body = json.loads(raw_body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                body = json.loads(raw_body.decode("gbk", errors="replace"))
            except:
                body = json.loads(raw_body.decode("utf-8", errors="replace"))
        message = body.get("message", "").strip()
        print(f"[CHAT] Received message: {repr(message)}")
        form_material = body.get("material")  # 表单联动参数
        form_quantity = body.get("quantity")
        form_surface = body.get("surface_treatment")
        # 图纸上下文 (上传STEP后前端附带, 供对话框对图纸进行分析)
        context = body.get("context") or {}
        print(f"[CHAT] form params: material={form_material}, quantity={form_quantity}, surface={form_surface}")
        if not message: return JSONResponse(content=wrap_shadow({"reply": "请输入您的需求。"}))

        # ── 注入图纸上下文: 若有上传图纸信息, 在用户消息前拼接上下文, 让 LLM 对图纸分析 ──
        if context and isinstance(context, dict):
            ctx_parts = []
            if context.get("file_name"): ctx_parts.append(f"已上传文件: {context['file_name']}")
            if context.get("part_spec"): ctx_parts.append(f"零件规格: {json.dumps(context['part_spec'], ensure_ascii=False)}")
            if context.get("bounding_box"): ctx_parts.append(f"边界框(mm): {context['bounding_box']}")
            if context.get("volume_cm3") is not None: ctx_parts.append(f"体积: {context['volume_cm3']} cm³")
            if ctx_parts:
                message = "【图纸上下文】\n" + "\n".join(ctx_parts) + "\n\n【用户问题】\n" + message
                print(f"[CHAT] 注入图纸上下文, enriched message length={len(message)}")

        msg_lower = message.lower()
        is_quote = any(k in msg_lower for k in ["报价", "价格", "多少钱", "成本", "quote", "price", "cost", "费用"])
        is_check = any(k in msg_lower for k in ["能接", "能不能", "可否", "接不接", "可行", "可以吗", "能做"])
        is_draw = any(k in msg_lower for k in ["画", "绘制", "制图", "设计", "生成", "建模", "创建", "出图", "draw", "generate", "make", "做"]) and any(
            k in msg_lower for k in ["法兰", "轴套", "轴", "齿轮", "箱体", "支架", "板", "法兰盖", "闷盖", "检查盖", "盖", "圆盘", "轮",
                                     "flange", "sleeve", "shaft", "gear", "box", "bracket", "plate", "block", "cover", "disc"])
        
        # DEBUG
        print(f"[CHAT DEBUG] message={repr(message)}, msg_lower={repr(msg_lower)}, is_draw={is_draw}, is_quote={is_quote}")
        
        triggers = detect_triggers(message)
        if is_quote and not is_check: triggers = []
        last_stl_url = None  # 保存当前请求的stl_url
        cad_tot_chain = None  # TOT多管道竞争推理链 (TOT关闭/失败时为None)

        # ── 一句话画图: LLM推理优先 (JSON结构收集 → LLM推理 → OCC直接驱动) ──
        llm_spec, _llm_raw, _llm_meta = None, "", {"model": None, "source": None, "fallback_index": -1, "note": "未调用"}
        _part_kw = ("法兰", "轴套", "衬套", "光轴", "齿轮", "箱体", "支架", "平板", "垫板",
                    "法兰盖", "闷盖", "检查盖", "圆盘", "台阶",
                    "flange", "sleeve", "shaft", "plate", "bracket", "cover", "disc", "block")
        # TOT开启时跳过前置单次LLM提取 — LLM采样统一在TOT内部完成(避免重复调用)
        _tot_enabled = os.environ.get("TOT_ENABLED", "1") != "0"
        if (is_draw or any(k in msg_lower for k in _part_kw)) and not is_check and not _tot_enabled:
            llm_spec, _llm_raw, _llm_meta = await run_blocking(llm_extract_part_spec, message)
            if llm_spec:
                is_draw = True  # LLM确认为画零件，无需"画"动词
        elif _tot_enabled and any(k in msg_lower for k in _part_kw) and not is_check:
            is_draw = True  # TOT模式下零件关键词即触发(管道内部再判定)

        def _legacy_extract_cad_spec(message, msg_lower, llm_spec, cad_chain):
            """原"LLM优先→正则回填"单路径提取 (TOT关闭/失败时的回退路径)。
            返回 (part_type, params, _defaulted, _rx)。"""
            # 尝试提取零件类型和参数
            part_type = "flange"
            type_map = {"法兰": "flange", "轴套": "sleeve", "轴": "shaft", "箱体": "box",
                        "支架": "bracket", "板": "plate", "方块": "box", "检查盖": "flange", "法兰盖": "flange",
                        "闷盖": "flange", "盖": "flange", "圆盘": "flange", "轮": "gear", "齿轮": "shaft",
                        "flange": "flange", "sleeve": "sleeve", "shaft": "shaft",
                        "gear": "shaft", "box": "box", "bracket": "bracket",
                        "plate": "plate", "block": "box", "cover": "flange", "disc": "flange"}
            for pt in list(type_map.keys()):
                if pt in msg_lower:
                    part_type = type_map[pt]
                    break
            # 参数提取（中文+英文+宽x高x厚格式）
            import re
            params = {"od": 100, "id": 50, "thickness": 20}  # 默认法兰
            _rx = {}  # 正则成功提取项 (LLM值优先, 正则只补缺)
            _defaulted = []  # 默认值静默填充项 (用于警告展示)
            od_m = re.search(r'外径\s*(\d+)', message) or re.search(r'od\s*(\d+)', msg_lower) or re.search(r'outer\s*(\d+)', msg_lower)
            id_m = re.search(r'内径\s*(\d+)', message) or re.search(r'id\s*(\d+)', msg_lower) or re.search(r'inner\s*(\d+)', msg_lower) \
                or re.search(r'(?:中心孔|内孔|中孔)\s*(?:径|直径)?\s*(?:为|是)?\s*(\d+(?:\.\d+)?)', message)
            th_m = re.search(r'厚\s*(\d+)', message) or re.search(r'厚度\s*(\d+)', message) or re.search(r'th\s*(\d+)', msg_lower) or re.search(r'thickness\s*(\d+)', msg_lower)
            # 宽x高x厚格式
            wxh_m = re.search(r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)', message)
            d_m = re.search(r'直径\s*(\d+)', message) or re.search(r'd\s*(\d+)', msg_lower)
            l_m = re.search(r'长\s*(\d+)', message) or re.search(r'l\s*(\d+)', msg_lower) or re.search(r'length\s*(\d+)', msg_lower)
            # 安装孔/螺栓孔数量
            holes_m = re.search(r'(\d+)\s*[个只]\s*[Mm]?\d*\s*(?:安装孔|螺栓孔|光孔|孔)', message) or re.search(r'bolt[_\s]*holes?\s*(\d+)', msg_lower)
            # "4×φ10通孔"格式 → bolt_holes=4, bolt_d=10
            holes_m2 = re.search(r'(\d+)\s*[×xX*]\s*[φΦ∅]?\s*(\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:通孔|孔|螺栓孔)', message)
            bolt_d_m = re.search(r'(?:孔径|螺栓径|bolt[_\s]*d)\s*(\d+)', msg_lower) or re.search(r'm(\d+)\s*(?:螺栓|bolt)', msg_lower)
            pcd_m = re.search(r'(?:PCD|分布圆|分度圆)\s*(\d+)', message, re.I)  # 孔分布圆直径
            evenly_m = re.search(r'均布|均分|圆周分布', message)  # 均布孔佐证(记入推理链)

            if od_m: _rx["od"] = int(od_m.group(1))
            if id_m: _rx["id"] = int(float(id_m.group(1)))
            if th_m: _rx["thickness"] = int(th_m.group(1))
            if wxh_m:
                _rx["w"] = int(wxh_m.group(1)); _rx["h"] = int(wxh_m.group(2)); _rx["t"] = int(wxh_m.group(3))
            # "直径" → 对法兰映射为 od
            if d_m:
                _rx["d"] = int(d_m.group(1))
                if part_type == "flange":
                    _rx["od"] = int(d_m.group(1))
            if l_m: _rx["length"] = int(l_m.group(1))
            if holes_m: _rx["bolt_holes"] = int(holes_m.group(1))
            elif holes_m2:
                _rx["bolt_holes"] = int(holes_m2.group(1))
                _rx["bolt_d"] = float(holes_m2.group(2))
            if bolt_d_m: _rx["bolt_d"] = int(bolt_d_m.group(1))
            if pcd_m: _rx["bolt_pcd"] = int(pcd_m.group(1))
            params.update(_rx)
            for _rk, _rv in _rx.items():
                cad_chain.add_feature(f"正则:{_rk}", _rv, f"正则规则提取 {_rk}={_rv}")
            if evenly_m:
                cad_chain.add_feature("均布孔", True, "识别到'均布/均分/圆周分布'，螺栓孔沿圆周均布分布")
            # 自动计算 bolt_pcd (PCD = OD * 0.75 常用比例)
            if "bolt_holes" in params and "bolt_pcd" not in params:
                params["bolt_pcd"] = round(params.get("od", 100) * 0.75)
                _defaulted.append(f"bolt_pcd={params['bolt_pcd']}")
            # 默认螺栓孔直径
            if "bolt_holes" in params and "bolt_d" not in params:
                params["bolt_d"] = 8
                _defaulted.append("bolt_d=8")

            # 根据零件类型设置默认参数映射
            if part_type == "shaft" and "d" not in params and "od" in params:
                params["d"] = params["od"]
                params["length"] = params.get("length", 120)
            elif part_type == "sleeve" and "od" in params and "id" in params:
                params["length"] = params.get("length", 80)
            elif part_type == "plate" and "w" not in params:
                size_m = re.search(r'(\d+)', message)
                if size_m: params["w"] = int(size_m.group(1))
            elif part_type == "bracket" and "w" not in params:
                params["w"] = params.get("od", 80)
                params["h"] = params.get("id", 60)
                params["t"] = params.get("thickness", 8)

            # ── LLM结构化参数覆盖: JSON直接驱动OCC ──
            if llm_spec:
                cad_chain.add_step(StepType.CALCULATION, "validate_part_spec清洗",
                    f"LLM原始JSON经schema校验/清洗 → {json.dumps(llm_spec['params'], ensure_ascii=False)}",
                    evidence={"cleaned_params": llm_spec["params"],
                              "material": llm_spec.get("material"), "quantity": llm_spec.get("quantity"),
                              "surface_treatment": llm_spec.get("surface_treatment")},
                    confidence=0.95, source="validate_part_spec")
                part_type = llm_spec["part_type"]
                params = dict(llm_spec["params"])
                _defaulted = []  # 重置: 只计LLM路径的默认值填充
                # 语义纠偏(须在默认值填充前): 法兰盖/闷盖/圆盘且无"内径"提及 → 无内孔
                if part_type == "flange" and "id" not in params \
                        and any(k in message for k in ("法兰盖", "闷盖", "圆盘")) and "内径" not in message:
                    params["id"] = 0
                    cad_chain.add_inference("语义纠偏: 无内孔", "法兰盖/闷盖/圆盘且未提及内径 → id=0 (无内孔)", confidence=0.9)
                _defaults = {
                    "flange":  {"od": 100, "id": 50, "thickness": 20},
                    "sleeve":  {"od": 60, "id": 30, "length": 100},
                    "shaft":   {"d": 40, "length": 120},
                    "plate":   {"w": 150, "h": 100, "t": 10},
                    "box":     {"w": 200, "h": 100, "d": 150, "thickness": 5},
                    "bracket": {"w": 80, "h": 120, "t": 10},
                }
                for _dk, _dv in _defaults.get(part_type, {}).items():
                    if _dk not in params:
                        params[_dk] = _dv
                        _defaulted.append(f"{_dk}={_dv}")
                        cad_chain.add_warning(f"{part_type} 缺少 {_dk}，静默填充默认值 {_dv}", severity="warning")
                # 混合增强: 正则回填LLM遗漏项 (LLM值优先, 正则只补缺)
                for _rk, _rv in _rx.items():
                    if _rk not in params:
                        params[_rk] = _rv
                        cad_chain.add_feature(f"正则回填:{_rk}", _rv, f"LLM未提取 {_rk}，正则回填 {_rv}")
                if part_type == "flange":
                    if not params.get("bolt_holes"):
                        # 必须带量词"个/只"，允许数量后夹M径: "4个M10孔"/"4个孔"→4；兼容"4×φ10孔"格式
                        _hm = re.search(r'(\d+)\s*[个只]\s*[Mm]?\d*\s*(?:安装孔|螺栓孔|光孔|孔)', message)
                        if not _hm:
                            _hm = re.search(r'(\d+)\s*[×xX*]\s*[φΦ∅]?\s*(?:\d+(?:\.\d+)?)\s*(?:mm)?\s*(?:通孔|孔|螺栓孔)', message)
                        if _hm:
                            params["bolt_holes"] = int(_hm.group(1))
                            cad_chain.add_feature("正则回填:bolt_holes", params["bolt_holes"], "正则回填螺栓孔数量")
                    if params.get("bolt_holes") and "bolt_d" not in params:
                        _bm = re.search(r'[Mm](\d+)', message)
                        if _bm:
                            params["bolt_d"] = int(_bm.group(1))
                            cad_chain.add_feature("正则回填:bolt_d", params["bolt_d"], "正则回填螺栓孔径")
                    if params.get("bolt_holes") and "bolt_pcd" not in params:
                        _pm = re.search(r'(?:PCD|分布圆|分度圆)\s*(\d+)', message, re.I)
                        if _pm:
                            params["bolt_pcd"] = int(_pm.group(1))
                            cad_chain.add_feature("正则回填:bolt_pcd", params["bolt_pcd"], "正则回填分度圆直径")
                        else:
                            params["bolt_pcd"] = round(params.get("od", 100) * 0.75)
                            _defaulted.append(f"bolt_pcd={params['bolt_pcd']}")
                            cad_chain.add_warning(f"未指定分度圆，按经验猜测 bolt_pcd=0.75×od={params['bolt_pcd']}mm", severity="warning")
            else:
                # 无LLM规格: 记录正则路径残留的默认值 (法兰三件套)
                if part_type == "flange":
                    for _dk, _dv in (("od", 100), ("id", 50), ("thickness", 20)):
                        if _dk not in _rx:
                            _defaulted.append(f"{_dk}={_dv}")
                            cad_chain.add_warning(f"flange 缺少 {_dk}，静默填充默认值 {_dv}", severity="warning")
            # 法兰螺栓孔显式化: 保证OCC(默认0)与trimesh预览(默认4孔)一致
            if part_type == "flange":
                params.setdefault("bolt_holes", 0)
                if params["bolt_holes"]:
                    if "bolt_d" not in params:
                        params["bolt_d"] = 8
                        _defaulted.append("bolt_d=8")
                        cad_chain.add_warning("未指定螺栓孔径，默认 bolt_d=8mm", severity="warning")
                    if "bolt_pcd" not in params:
                        params["bolt_pcd"] = round(params.get("od", 100) * 0.75)
                        _defaulted.append(f"bolt_pcd={params['bolt_pcd']}")
                        cad_chain.add_warning(f"未指定分度圆，按经验猜测 bolt_pcd=0.75×od={params['bolt_pcd']}mm", severity="warning")
            return part_type, params, _defaulted, _rx

        # 模块级注册: 供 TOT pipeline_regex_candidate 通过 sys.modules['app.main'] 访问
        # (函数不捕获外部变量, 仅用参数+模块级名称, 注册安全)
        globals()["_legacy_extract_cad_spec"] = _legacy_extract_cad_spec

        if is_draw:
            # ── cad_extract 推理链 (XAI): 一句话→标准参数JSON 全程追溯 ──
            cad_chain = ReasoningChain("cad_extract", "CAD参数提取: 一句话→标准参数JSON")
            cad_chain.add_input("user_message", message, source="user")
            if llm_spec is not None:
                cad_chain.add_inference(
                    f"LLM提取成功 ({_llm_meta.get('model')})",
                    f"模型={_llm_meta.get('model')} (来源={_llm_meta.get('source')}, 降级深度={_llm_meta.get('fallback_index')})；"
                    f"原始输出已落盘 logs/llm_spec_raw.jsonl",
                    confidence=0.85, evidence={"raw": (_llm_raw or "")[:500]})
            elif not _tot_enabled:
                cad_chain.add_warning(f"LLM参数提取未成功 ({_llm_meta.get('note')})，降级为正则规则解析", severity="warning")
                cad_chain.add_inference("降级: 正则规则解析", "LLM不可用/失败，改用内置中文正则规则提取参数", confidence=0.6)

            # ── TOT多管道竞争: 候选管道打分择优 (TOT_ENABLED=0 或失败时回退原单路径) ──
            part_spec = None
            _defaulted = []
            if _tot_enabled:
                try:
                    from src.runtime.cad_pipeline_tot import run_tot_competition
                    _structured = {"part_type": body.get("part_type"),
                                   "params": body.get("params") or {}}
                    _tot_result = await run_blocking(
                        run_tot_competition, message, structured_spec=_structured)
                except Exception as _tot_e:
                    print(f"[TOT] 竞争执行异常，回退单路径: {_tot_e}")
                    _tot_result = None
                if _tot_result:
                    # TOT推理链总是赋值(即使无可用候选), 供前端展示竞争过程
                    cad_tot_chain = _tot_result.get("chain_dict")
                if _tot_result and _tot_result.get("part_spec"):
                    part_spec = _tot_result["part_spec"]
                    part_type = part_spec["part_type"]
                    params = dict(part_spec["params"])
                    _defaulted = _tot_result.get("defaulted", [])
                    _w = _tot_result.get("winner", {})
                    cad_chain.add_inference(
                        f"TOT择优: {_w.get('source', '?')}管道胜出 (置信%{_w.get('confidence', 0):.1f})",
                        f"共{_tot_result.get('total_candidates', 0)}条候选管道竞争打分，最高置信度管道作为默认执行路径",
                        confidence=min(_w.get("confidence", 0.5), 1.0),
                        evidence={"winner": _w.get("source"), "scores": _tot_result.get("scoreboard")})
            if part_spec is None:
                # TOT关闭/失败 → 原"LLM优先→正则回填"单路径
                part_type, params, _defaulted, _rx = _legacy_extract_cad_spec(
                    message, msg_lower, llm_spec, cad_chain)

            # 最终标准参数JSON (新增响应字段 part_spec + 推理链结论)
            part_spec = {"part_type": part_type, "params": params,
                         "material": (llm_spec or {}).get("material"),
                         "quantity": (llm_spec or {}).get("quantity"),
                         "surface_treatment": (llm_spec or {}).get("surface_treatment")}

            gen = generate_part(part_type, params)
            if "error" in gen:
                return JSONResponse(content=wrap_shadow({"reply": f"❌ {gen['error']}"}))
            # GProp体积退化警告透传到推理链
            if gen.get("volume_warning"):
                cad_chain.add_warning(gen.get("volume_warning_reason", "GProp体积计算失败，退化为包围盒估算"), severity="warning")
            cad_chain.add_conclusion(
                f"生成标准参数JSON: {part_type}",
                confidence=max(0.5, 0.95 - 0.08 * len(_defaulted)),
                rationale=f"最终参数: {json.dumps(params, ensure_ascii=False)}；默认值填充 {len(_defaulted)} 项",
                recommendations=[f"请核对默认值项: {', '.join(_defaulted)}"] if _defaulted else None)
            _cad_chain_id = register_chain(cad_chain)
            cad_chain_dict = get_chain(_cad_chain_id)  # 完整链dict(含chain_id)
            
            bbox = gen.get("bounding_box_mm", [100, 100, 20])
            preview = gen.get("stl_url", "")
            last_stl_url = preview
            
            # ★ 自动生成报价和打包
            step_file = gen.get("step_file")
            stl_file = gen.get("stl_file")
            volume_cm3 = gen.get("volume_cm3", 0) or (gen.get("volume_mm3", 0) / 1000.0)

            # 报价参数合并: 消息明确提及 > 表单选择 > 系统默认 (来源透明化)
            form_qparams = {
                "material": form_material,
                "quantity": int(form_quantity) if form_quantity else None,
                "surface_treatment": form_surface,
            }
            form_qparams = {k: v for k, v in form_qparams.items() if v is not None and v != ''}
            msg_qparams = {}
            if llm_spec:
                if llm_spec.get("material"): msg_qparams["material"] = llm_spec["material"]
                if llm_spec.get("quantity"): msg_qparams["quantity"] = llm_spec["quantity"]
                if llm_spec.get("surface_treatment"): msg_qparams["surface_treatment"] = llm_spec["surface_treatment"]
            qparams = quote_adapter.merge_quote_params(msg_qparams, form_qparams)
            sources = qparams.pop("_sources", {})
            material = qparams["material"]
            quantity = int(qparams["quantity"])
            surface = qparams["surface_treatment"]
            src_mat = sources.get("material", "默认")
            src_qty = sources.get("quantity", "默认")
            src_surf = sources.get("surface_treatment", "默认")

            # 重量: 优先生成器估算; 否则按精确体积×材料密度
            weight_g = gen.get("estimated_weight_g", 0)
            if not weight_g and volume_cm3:
                _mk = quote_adapter.resolve_material(material)
                _density = quote_adapter.materials.get(_mk, {}).get("density", 2.8)
                weight_g = volume_cm3 * _density
                sources["weight_g"] = "OCC精确体积×密度"
            
            quote_params = {
                "material": material,
                "quantity": quantity,
                "surface_treatment": surface,
                "weight_kg": round(weight_g / 1000, 3) if weight_g else 0,
                "volume_cm3": volume_cm3,
                "tolerance": "IT8",
                "process": "三轴CNC",
                "bounding_box": bbox,
                "machining_hours": quote_adapter.estimate_machining_hours(
                    weight_g / 1000 if weight_g else 0, "三轴CNC", shape="flat", tolerance="IT8"
                ),
                "pricing_mode": "by_quantity" if quantity <= 20 else "by_weight",
                "profit_rate": 0.30,
            }
            
            # 冲突检查和报价
            conflicts = await run_blocking(conflict_checker.check, {"material": material, "surface_treatment": surface})
            quote_result = None
            reasoning_chain = None
            
            if conflicts["valid"]:
                quote_result = quote_adapter.quote_with_reasoning(quote_params)
                reasoning_chain = quote_result.pop('reasoning_chain', None)
                quote_result.pop('reasoning_chain_id', None)
            
            # 自动打包生成ZIP
            zip_url = None
            print(f"[CHAT DEBUG] step_file={step_file}, quote_result={quote_result is not None}")
            if step_file and quote_result:
                try:
                    bundle_files = [{"path": step_file, "name": f"{part_type}.step"}]
                    if stl_file:
                        bundle_files.append({"path": stl_file, "name": f"{part_type}.stl"})
                    
                    print(f"[CHAT DEBUG] Calling create_bundle with {len(bundle_files)} files")
                    print(f"[CHAT DEBUG] bundle_files: {bundle_files}")
                    bundle = create_bundle(
                        os.urandom(4).hex(),
                        bundle_files,
                        quote_data={
                            "material": material,
                            "quantity": quantity,
                            "surface_treatment": surface,
                            "surface": surface,
                            "unit_price": quote_result.get("unit_price"),
                            "final_price": quote_result.get("final_price"),
                            "total_price": quote_result.get("final_price"),
                            "material_code": quote_result.get("material_code", material),
                            "material_price": quote_adapter.materials.get(material, {}).get("price_kg", 30),
                            "process": quote_result.get("process", "三轴CNC"),
                            "weight_kg": quote_result.get("weight_kg", 0),
                            "machine_hours": quote_result.get("machine_hours", 0),
                            "hourly_rate": quote_result.get("hourly_rate", 120),
                            "material_cost": quote_result.get("material_cost", 0),
                            "machining_cost": quote_result.get("machining_cost", 0),
                            "surface_cost": quote_result.get("surface_cost", 0),
                            "extra_fees": quote_result.get("extra_fees", 0),
                            "total_cost": quote_result.get("total_cost", 0),
                            "profit": quote_result.get("profit", 0),
                            "profit_rate": quote_result.get("profit_rate", 0.3),
                            "discount": quote_result.get("discount", 1.0),
                            "tolerance": quote_result.get("tolerance", "IT8"),
                            "tol_coef": quote_result.get("tol_coef", 1.0),
                            "roughness": quote_result.get("roughness", "Ra1.6"),
                            "rough_coef": quote_result.get("rough_coef", 1.0),
                            "shape": quote_result.get("shape", "flat"),
                            "measurement_fee": quote_result.get("measurement_fee", 0),
                            "jig_fee": quote_result.get("jig_fee", 0),
                            "tool_fee": quote_result.get("tool_fee", 0),
                            "pricing_mode": quote_result.get("pricing_mode", "by_quantity"),
                            "volume_cm3": volume_cm3,
                            "bounding_box": bbox,
                        },
                        metadata={"task_id": f"chat-{os.urandom(3).hex()}", "created": datetime.now().isoformat()},
                        reasoning_chain=reasoning_chain
                    )
                    print(f"[CHAT DEBUG] bundle result: {bundle}")
                    
                    if bundle.get("zip_url"):
                        zip_url = bundle.get("zip_url")
                        print(f"[CHAT] ZIP打包成功: {zip_url}")
                    else:
                        print(f"[CHAT] ZIP打包失败: {bundle}")
                except Exception as e:
                    import traceback; traceback.print_exc()
                    print(f"[CHAT] ZIP打包异常: {e}")
            
            # 关键几何参数 (展示给用户核对)
            _geom = []
            if params.get("od"): _geom.append(f"外径φ{params['od']}")
            if "id" in params: _geom.append(f"中心孔φ{params['id']}" if params["id"] else "无内孔")
            if params.get("thickness") and part_type in ("flange", "sleeve", "box", "bracket"): _geom.append(f"厚{params['thickness']}")
            if params.get("length"): _geom.append(f"长{params['length']}")
            if params.get("d") and part_type == "shaft": _geom.append(f"直径φ{params['d']}")
            if params.get("w") and params.get("h"): _geom.append(f"{params['w']}×{params['h']}×{params.get('t', '?')}mm")
            if params.get("bolt_holes"): _geom.append(f"均布{params['bolt_holes']}×φ{params.get('bolt_d', '?')}@PCD{params.get('bolt_pcd', '?')}")
            geom_desc = " / ".join(_geom) if _geom else "—"

            # 构建回复
            reply_lines = [
                f"## 📐 STEP已生成 ({gen.get('engine', '?')}引擎 · {'🧠LLM推理' if llm_spec else '📏规则解析'})",
                f"",
                f"| 参数 | 值 |",
                f"|------|-----|",
                f"| 零件类型 | {part_type} |",
                f"| 几何参数 | {geom_desc} |",
                f"| 尺寸 | {bbox[0]}×{bbox[1]}×{bbox[2]} mm |",
                f"| 体积 | {volume_cm3:.2f} cm³{' ⚠️包围盒估算' if gen.get('volume_warning') else ''} |",
                f"| 重量 | {weight_g:.1f} g |",
                f"| 材料 | {material}（{src_mat}） |",
                f"| 数量 | {quantity} 件（{src_qty}） |",
                f"| 表面处理 | {surface}（{src_surf}） |",
            ]
            if _defaulted:
                reply_lines.append(f"| ⚠️ 默认值填充 | {', '.join(_defaulted)} (请核对) |")
            if gen.get("volume_warning"):
                reply_lines.append(f"| ⚠️ 体积提示 | {gen.get('volume_warning_reason', 'GProp失败，包围盒估算')} |")
            reply_lines.extend([
                f"",
            ])
            
            if quote_result:
                reply_lines.extend([
                    f"## 💰 报价明细",
                    f"",
                    f"| 项目 | 金额 |",
                    f"|------|------|",
                    f"| 单价 | ¥{quote_result.get('unit_price', 0):.2f} |",
                    f"| 数量 | {quantity} 件 |",
                    f"| **总价** | **¥{quote_result.get('final_price', 0):.2f}** |",
                    f"",
                ])
            else:
                # 冲突提示
                conflict_msgs = conflicts.get("conflicts", [])
                if conflict_msgs:
                    reply_lines.extend([
                        f"## ⚠️ 工艺冲突",
                        f"",
                    ])
                    for c in conflict_msgs:
                        reply_lines.append(f"- ❌ [{c.get('severity','')}] {c.get('message','')}")
                    for w in conflicts.get("warnings", []):
                        reply_lines.append(f"- ⚠️ [{w.get('severity','')}] {w.get('message','')}")
                    reply_lines.extend([
                        f"",
                        f"> 💡 请修正材料或表面处理后重新请求报价",
                        f"",
                    ])
            
            if zip_url:
                reply_lines.extend([
                    f"## 📦 文件下载",
                    f"",
                    f"- **ZIP包**: [{zip_url.split('/')[-1]}]({zip_url})",
                    f"- **STEP文件**: [{step_file.split('/')[-1]}]({step_file})",
                    f"",
                    f"> ✅ ZIP包含: STEP文件 + STL预览 + 专业XLSX报价单 + 推理链JSON",
                ])
            else:
                reply_lines.extend([
                    f"## 📁 文件",
                    f"",
                    f"- **STEP文件**: `{step_file}`",
                    f"- **STL预览**: `{stl_file}`",
                ])
            
            reply_lines.append(f"\n> ⚠️ 此结论为AI建议，仅供参考。实际加工前请人工确认。")
            
            return JSONResponse(content=wrap_shadow({
                "reply": "\n".join(reply_lines),
                "step_file": step_file,
                "stl_file": stl_file,
                "stl_url": preview,
                "quote": quote_result,
                "reasoning_chain": reasoning_chain,
                "cad_reasoning_chain": cad_chain_dict,
                "cad_tot_chain": cad_tot_chain,
                "part_spec": part_spec,
                "zip_url": zip_url,
                "auto_bundle": True,
            }))

        if triggers:
            if not expert_engine:
                return JSONResponse(content=wrap_shadow({
                    "reply": f"检测到触发条件: {', '.join(triggers)}\n\n"
                             "专家会议需要AI模型支持。请安装Ollama并运行 `ollama pull qwen2.5:3b`，\n"
                             "或在 config/models.json 配置云端API后重试。\n\n"
                             "可用的离线功能：报价计算、冲突检测、STEP生成、历史查询。"
                }))

            CURRENT_TASK.update(active=True, name="专家会议", progress=10)
            expert_list = []
            if any(k in msg_lower for k in ["报价", "成本", "价格", "利润", "预算"]):
                expert_list.extend(["cfo_analysis", "bi_analyst"])
            if any(k in msg_lower for k in ["产能", "扩产"]):
                expert_list.extend(["strategist", "process_chief"])
            if "process_chief" not in expert_list: expert_list.append("process_chief")
            expert_list.append("ceo_decision")
            expert_list = list(dict.fromkeys(expert_list))
            CURRENT_TASK["progress"] = 20

            def _progress_cb(idx, ename):
                CURRENT_TASK["progress"] = 30 + idx * (60 // max(len(expert_list), 1))
                CURRENT_TASK["name"] = f"{ename} 分析中..."

            report = await run_blocking(expert_engine.convene, message,
                {"user_input": message, "triggers": triggers, "expert_panel": expert_list,
                 "timestamp": datetime.now().isoformat()},
                expert_list, progress_cb=_progress_cb)

            CURRENT_TASK.update(active=False, progress=100)
            audit.log(task_id=f"{datetime.now().strftime('%Y%m%d%H%M%S')}-panel",
                      event_type="expert_panel",
                      data={"topic": message[:200], "decision": report.get("decision"), "triggers": triggers})

            lines = [f"## 🏛️ 专家会议报告\n**触发**: {', '.join(triggers)}\n**参会**: {', '.join(expert_list)}\n"]
            lines.append(f"### 最终裁决: {report.get('decision', 'N/A')}")
            if report.get("veto_by"):
                lines.append(f"\n⚠️ **一票否决**: {report['veto_by']}\n> {report.get('reason', '')[:300]}")
            lines.append(f"\n> {report.get('rationale', '')[:500]}")
            transcript = report.get("transcript", [])
            if transcript:
                lines.append("\n### 专家意见")
                for t in transcript:
                    emoji = {"approve": "✅", "reject": "❌", "abstain": "🤔"}.get(t.get("recommendation"), "❓")
                    lines.append(f"- {emoji} **{t['expert']}**: {t.get('recommendation', 'N/A')}")
            lines.append("\n> ⚠️ 此结论为AI建议，仅供参考。实际加工前请人工确认。")
            return JSONResponse(content=wrap_shadow({"reply": "\n".join(lines)}))

        if is_quote:
            print(f"[DEBUG] is_quote=True, message={message}")
            # 消息 > 表单 > 默认 合并
            msg_params = quote_adapter.extract_params_from_message(message)
            print(f"[DEBUG] extract_params result: {msg_params}")
            form_params = {
                "material": form_material,
                "quantity": int(form_quantity) if form_quantity else None,
                "surface_treatment": form_surface,
            }
            form_params = {k: v for k, v in form_params.items() if v is not None and v != ''}
            params = quote_adapter.merge_quote_params(msg_params, form_params)
            sources = params.pop("_sources", {})
            print(f"[DEBUG] merged params: {params}, sources: {sources}")

            if params:
                conflicts = await run_blocking(conflict_checker.check_with_reasoning, params)
                if not conflicts["valid"]:
                    conflicts_text = ["## ⚠️ 工艺冲突"]
                    for c in conflicts["conflicts"]:
                        conflicts_text.append(f"- ❌ [{c['severity']}] {c['message']}")
                    for w in conflicts.get("warnings", []):
                        conflicts_text.append(f"- ⚠️ [{w['severity']}] {w['message']}")
                    conflicts_text.append("\n→ 请修正参数后重新报价")
                    return JSONResponse(content=wrap_shadow({
                        "reply": "\n".join(conflicts_text),
                        "reasoning_chain": conflicts.get("reasoning_chain"),
                        "reasoning_chain_id": conflicts.get("reasoning_chain_id"),
                    }))

            # 若消息给了尺寸但没给重量/体积，按形状尺寸×密度估算
            if params.get("dimensions") and params.get("weight_kg") in (None, '', 0) and params.get("volume_cm3") in (None, '', 0):
                # 未显式指定 shape 时，根据 dimensions 推断
                if not params.get("shape"):
                    dims = params["dimensions"]
                    if ("od" in dims) or ("D" in dims and "d" in dims):
                        params["shape"] = "flange"
                    elif "d" in dims or "D" in dims:
                        params["shape"] = "round"
                    elif "w" in dims and "h" in dims:
                        params["shape"] = "flat"
                mat_code = quote_adapter.resolve_material(params.get("material", "AL6061"))
                weight_kg_est = quote_adapter.calc_weight_from_dimensions(
                    params.get("shape", "flat"), params["dimensions"], mat_code)
                params["weight_kg"] = round(weight_kg_est, 4)
                sources["weight_kg"] = "消息尺寸×形状密度估算"

            result = quote_adapter.quote_with_reasoning(params or {})
            result["param_sources"] = sources
            audit.log(task_id=f"{datetime.now().strftime('%Y%m%d%H%M%S')}-quote",
                      event_type="quote", data={"params": params, "final_price": result.get("final_price")})
            warnings = "\n".join(f"> {w}" for w in result.get("warnings", [])) if result.get("warnings") else ""

            src_lines = []
            for k in ["material", "quantity", "surface_treatment", "shape", "dimensions", "weight_kg"]:
                if k in sources:
                    src_lines.append(f"- {k}: {sources[k]}")

            # 小计 = 单价 × 数量（与总价一致）；利润率以实际计算值为准
            _unit_price = float(result.get("unit_price", 0) or 0)
            _qty = int(result.get("quantity", 1) or 1)
            _subtotal = round(_unit_price * _qty, 2)
            _profit_pct = float(result.get("profit_rate", 0.30) or 0.30) * 100

            reply = (
                f"## 📊 报价明细 (quote-ptuning引擎)\n\n"
                f"**零件**: {result.get('part_name', 'N/A')}\n"
                f"**材料**: {result.get('material', 'N/A')} (来源: {sources.get('material', '默认')})\n"
                f"**表面**: {result.get('surface', 'N/A')} (来源: {sources.get('surface_treatment', '默认')})\n"
                f"**数量**: {result.get('quantity', 'N/A')}件 (来源: {sources.get('quantity', '默认')})\n"
                f"**重量**: {result.get('weight_kg', 0):.3f} kg (来源: {sources.get('weight_kg', '默认')})\n\n"
                f"| 项目 | 金额 |\n|------|------|\n"
                f"| 单价 | ¥{result.get('unit_price', 0):.2f} |\n"
                f"| 小计 | ¥{_subtotal:.2f} |\n"
                f"| 利润({_profit_pct:.0f}%) | ¥{result.get('profit', 0):.2f} |\n"
                f"| **总价** | **¥{result.get('final_price', 0):.2f}** |\n\n"
                f"{warnings}\n\n"
                f"### 参数来源\n{chr(10).join(src_lines) if src_lines else '- 全部使用默认值'}\n\n"
                f"> ⚠️ 此结论为AI建议，仅供参考"
            )
            return JSONResponse(content=wrap_shadow({
                "reply": reply,
                "quote": result,
                "stl_url": last_stl_url,
                "reasoning_chain": result.get("reasoning_chain"),
                "reasoning_chain_id": result.get("reasoning_chain_id"),
            }))

        if ai:
            try:
                # 若有图纸上下文, 增强系统提示让 LLM 优先分析图纸
                _sys_prompt = "你是Union·由你，CNC AI工艺大脑。请用中文简洁回答CNC加工问题。"
                if context and isinstance(context, dict) and any(context.get(k) for k in ("file_name", "part_spec", "bounding_box", "volume_cm3")):
                    _sys_prompt = ("你是Union·由你，CNC AI工艺大脑。用户已上传STEP图纸并附带图纸上下文(文件名/零件规格/边界框/体积)。"
                                   "请基于上下文对图纸进行结构化分析: 1)识别零件类型与关键几何参数 2)估算加工工艺与难点 3)给出加工建议。"
                                   "用中文简洁回答, 可使用Markdown表格。")
                response = await run_blocking(
                    fallback_chat, message, _sys_prompt)
            except EngineError as e:
                print(f"[CHAT] engine error: {e}")
                return JSONResponse(content=wrap_shadow({
                    "reply": "AI模型服务暂时不可用，请稍后重试，或使用离线报价/冲突检测/STEP生成功能。",
                    "error": {"code": "engine_error", "detail": str(e)},
                }), status_code=503)
            # 确保 reply 始终非空 (LLM 返回 None/空字符串时给默认提示)
            if not response or not (response.strip() if isinstance(response, str) else False):
                if context and isinstance(context, dict) and any(context.get(k) for k in ("file_name", "part_spec", "bounding_box", "volume_cm3")):
                    _off_lines = ["## 📐 图纸分析 (离线模式)"]
                    if context.get("file_name"): _off_lines.append(f"\n**文件**: {context['file_name']}")
                    if context.get("part_spec"):
                        _off_lines.append(f"\n**零件规格**:\n```json\n{json.dumps(context['part_spec'], ensure_ascii=False, indent=2)}\n```")
                    if context.get("bounding_box"): _off_lines.append(f"\n**边界框(mm)**: {context['bounding_box']}")
                    if context.get("volume_cm3") is not None: _off_lines.append(f"\n**体积**: {context['volume_cm3']} cm³")
                    _off_lines.append("\n> ⚠️ AI模型未返回详细分析, 以上为图纸上下文摘要。请配置 Ollama 或云端 API 后获取完整分析。")
                    response = "\n".join(_off_lines)
                else:
                    response = "我已收到您的消息，但当前无法生成详细回复。请尝试提供更多细节，或上传图纸后输入'解析'进行分析。"
            return JSONResponse(content=wrap_shadow({"reply": response}))
        else:
            # 无 AI 模型时, 若有图纸上下文则给出离线摘要
            if context and isinstance(context, dict) and any(context.get(k) for k in ("file_name", "part_spec", "bounding_box", "volume_cm3")):
                _off_lines = ["## 📐 图纸分析 (离线模式 - 无AI模型)",
                              f"\n> 当前无AI模型可用, 以下为图纸上下文摘要:"]
                if context.get("file_name"): _off_lines.append(f"\n**文件**: {context['file_name']}")
                if context.get("part_spec"):
                    _off_lines.append(f"\n**零件规格**:\n```json\n{json.dumps(context['part_spec'], ensure_ascii=False, indent=2)}\n```")
                if context.get("bounding_box"): _off_lines.append(f"\n**边界框(mm)**: {context['bounding_box']}")
                if context.get("volume_cm3") is not None: _off_lines.append(f"\n**体积**: {context['volume_cm3']} cm³")
                _off_lines.append("\n> 💡 安装Ollama并运行 `ollama pull qwen2.5:3b`，或在 config/models.json 配置云端API后可获得完整AI分析。")
                return JSONResponse(content=wrap_shadow({"reply": "\n".join(_off_lines)}))
            return JSONResponse(content=wrap_shadow({
                "reply": "当前无AI模型可用。请安装Ollama并运行 `ollama pull qwen2.5:3b`，或在 config/models.json 配置云端API。\n\n"
                         "可用的离线功能：\n"
                         "- 报价计算：输入材料+数量+表面处理\n"
                         "- 冲突检测：输入材料+表面处理\n"
                         "- STEP生成：输入零件类型+尺寸参数\n"
                         "- 历史查询：输入客户名称"
            }))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content=wrap_shadow({"reply": f"❌ 内部错误: {str(e)}"}), status_code=500)

# ── ★ OpenAI 兼容协议 ──
@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI兼容接口 — 可接入任何支持OpenAI协议的客户端/Agent。"""
    try:
        body = await request.json()
    except:
        return JSONResponse(content={"error": {"message": "Invalid JSON", "type": "invalid_request_error"}}, status_code=400)

    messages = body.get("messages", [])
    model = body.get("model", "cnc-ai-brain")
    stream = body.get("stream", False)
    temperature = body.get("temperature", 0.3)
    max_tokens = body.get("max_tokens", 2048)

    if not messages:
        return JSONResponse(content={"error": {"message": "messages is required", "type": "invalid_request_error"}}, status_code=400)

    # 提取用户消息
    user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_msg = m.get("content", "")
            break
    if not user_msg:
        user_msg = messages[-1].get("content", "") if messages else ""

    # 复用 chat 逻辑
    msg_lower = user_msg.lower()
    is_quote = any(k in msg_lower for k in ["报价", "价格", "多少钱", "成本", "quote", "price", "cost", "费用"])
    is_draw = any(k in msg_lower for k in ["画", "生成", "建模", "创建", "draw", "generate", "make", "做"]) and any(
        k in msg_lower for k in ["法兰", "轴套", "轴", "齿轮", "箱体", "支架", "板", "法兰盖", "闷盖",
                                 "flange", "sleeve", "shaft", "gear", "box", "bracket", "plate", "block"])

    reply_text = ""
    stl_url = None

    if is_draw:
        import re
        part_type = "flange"
        type_map = {"法兰": "flange", "轴套": "sleeve", "轴": "shaft", "箱体": "box",
                    "支架": "bracket", "板": "plate", "方块": "box",
                    "flange": "flange", "sleeve": "sleeve", "shaft": "shaft",
                    "gear": "shaft", "box": "box", "bracket": "bracket",
                    "plate": "plate", "block": "box"}
        for pt in list(type_map.keys()):
            if pt in msg_lower:
                part_type = type_map[pt]
                break
        params = {"od": 100, "id": 50, "thickness": 20}
        od_m = re.search(r'外径\s*(\d+)', user_msg) or re.search(r'od\s*(\d+)', msg_lower) or re.search(r'outer\s*(\d+)', msg_lower)
        id_m = re.search(r'内径\s*(\d+)', user_msg) or re.search(r'id\s*(\d+)', msg_lower) or re.search(r'inner\s*(\d+)', msg_lower)
        th_m = re.search(r'厚\s*(\d+)', user_msg) or re.search(r'厚度\s*(\d+)', user_msg) or re.search(r'th\s*(\d+)', msg_lower)
        wxh_m = re.search(r'(\d+)\s*[xX×]\s*(\d+)\s*[xX×]\s*(\d+)', user_msg)
        d_m = re.search(r'直径\s*(\d+)', user_msg) or re.search(r'd\s*(\d+)', msg_lower)
        l_m = re.search(r'长\s*(\d+)', user_msg) or re.search(r'l\s*(\d+)', msg_lower) or re.search(r'length\s*(\d+)', msg_lower)
        if od_m: params["od"] = int(od_m.group(1))
        if id_m: params["id"] = int(id_m.group(1))
        if th_m: params["thickness"] = int(th_m.group(1))
        if wxh_m: params.update({"w": int(wxh_m.group(1)), "h": int(wxh_m.group(2)), "t": int(wxh_m.group(3))})
        if d_m: params["d"] = int(d_m.group(1))
        if l_m: params["length"] = int(l_m.group(1))
        gen = generate_part(part_type, params)
        if "error" in gen:
            reply_text = f"生成失败: {gen['error']}"
        else:
            bbox = gen.get("bounding_box_mm", [100, 100, 20])
            stl_url = gen.get("stl_url", "")
            reply_text = (f"STEP已生成: {part_type}, 尺寸{bbox[0]}×{bbox[1]}×{bbox[2]}mm, "
                         f"体积{gen.get('volume_cm3','-')}cm³, 预览: {stl_url}")
    elif is_quote:
        params = quote_adapter.extract_params_from_message(user_msg)
        # 形状推断 + 尺寸估算重量
        if params.get("dimensions") and params.get("weight_kg") in (None, '', 0) and params.get("volume_cm3") in (None, '', 0):
            if not params.get("shape"):
                dims = params["dimensions"]
                if ("od" in dims) or ("D" in dims and "d" in dims):
                    params["shape"] = "flange"
                elif "d" in dims or "D" in dims:
                    params["shape"] = "round"
                elif "w" in dims and "h" in dims:
                    params["shape"] = "flat"
            mat_code = quote_adapter.resolve_material(params.get("material", "AL6061"))
            params["weight_kg"] = round(quote_adapter.calc_weight_from_dimensions(
                params.get("shape", "flat"), params["dimensions"], mat_code), 4)
        result = quote_adapter.quote(params or {})
        reply_text = f"报价: 单价¥{result.get('unit_price',0)}, 总价¥{result.get('final_price',0)} ({result.get('material','-')}, {result.get('quantity','-')}件)"
    elif ai:
        sys_prompt = ""
        for m in messages:
            if m.get("role") == "system":
                sys_prompt = m.get("content", ""); break
        try:
            reply_text = await run_blocking(
                fallback_chat, user_msg, sys_prompt or "你是Union·由你，CNC AI工艺大脑。")
        except EngineError as e:
            return JSONResponse(content={
                "error": {"message": f"model unavailable: {e}", "type": "server_error"}
            }, status_code=503)
    else:
        reply_text = "CNC AI Brain 离线模式。支持: 画图(法兰/轴套/平板)、报价、冲突检测。"

    # OpenAI 标准响应格式
    import time as _t
    response = {
        "id": f"chatcmpl-{os.urandom(4).hex()}",
        "object": "chat.completion",
        "created": int(_t.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply_text},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }
    if stl_url:
        response["stl_url"] = stl_url

    return JSONResponse(content=response)


@app.post("/api/models/switch")
async def switch_model(body: dict):
    """运行时切换AI模型（无需重启）。"""
    global ai, best_config
    target = body.get("model", "")
    if not target:
        return JSONResponse({"error": "missing 'model' field"}, status_code=400)

    # Find model in registry
    all_models = model_registry.get_all_ranked()
    found = None
    for m in all_models:
        if m["name"].lower() == target.lower():
            found = m
            break

    if not found:
        available = [m["name"] for m in all_models]
        return JSONResponse({"error": f"model '{target}' not found", "available": available}, status_code=404)

    # Switch
    old_name = best_config.get("name", "none") if best_config else "none"
    best_config = found
    model_name = found.get("name", "")
    source = found.get("source", "ollama")

    try:
        if source in ("cloud", "local"):
            from src.ai_engine.openai_engine import OpenAIEngine
            ai = OpenAIEngine(
                api_key=found.get("api_key", "none"),
                api_url=found["api_url"],
                model=found.get("model_id", model_name),
            )
        else:
            ai = OllamaEngine(model_name)
        return JSONResponse({
            "ok": True,
            "old": old_name,
            "new": model_name,
            "source": source,
            "quality_score": found.get("quality_score"),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/models/config")
async def get_model_config():
    """读取当前生效的模型配置（供首页加载时回填，避免硬编码默认值）。"""
    try:
        config_path = PROJECT_ROOT / "config" / "models.json"
        config_data = {}
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

        def _pick(source: str):
            # models 键(UI保存)优先，其次 cloud/local 键
            for m in config_data.get("models", []):
                if m.get("source") == source and m.get("api_url"):
                    return m
            for m in config_data.get(source, []):
                if m.get("api_url"):
                    return m
            return None

        cloud = _pick("cloud")
        local = _pick("local")
        runtime = config_data.get("runtime", {})
        return JSONResponse({
            "success": True,
            "cloud": cloud and {"api_url": cloud.get("api_url", ""), "api_key": cloud.get("api_key", ""),
                                "model_id": cloud.get("model_id", ""), "quality_score": cloud.get("quality_score", 95)},
            "local": local and {"api_url": local.get("api_url", ""), "api_key": local.get("api_key", ""),
                                "model_id": local.get("model_id", ""), "quality_score": local.get("quality_score", 88)},
            "timeout": runtime.get("timeout", 30),
            "retry": runtime.get("retry", 2),
            "current_model": best_config.get("name") if best_config else None,
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/models/config")
async def save_model_config(body: dict):
    """保存模型配置到config/models.json，并热重载注册表+降级链（无需重启）。"""
    try:
        config_path = PROJECT_ROOT / "config" / "models.json"

        # 读取现有配置
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        else:
            config_data = {"models": []}

        # 更新云端模型配置
        cloud_config = body.get("cloud", {})
        if cloud_config.get("api_url") and cloud_config.get("api_key"):
            cloud_model = None
            for m in config_data.get("models", []):
                if m.get("source") == "cloud":
                    cloud_model = m
                    break

            if not cloud_model:
                cloud_model = {"source": "cloud", "provider": "openai"}
                config_data.setdefault("models", []).append(cloud_model)

            cloud_model["api_url"] = cloud_config["api_url"]
            cloud_model["api_key"] = cloud_config["api_key"]
            cloud_model["model_id"] = cloud_config.get("model_id", "gpt-4o")
            cloud_model["quality_score"] = cloud_config.get("quality_score", 95)
            cloud_model["name"] = cloud_config.get("model_id", "gpt-4o")

        # 更新本地模型配置（标准OpenAI兼容协议: LM Studio / llamacpp / vLLM等）
        local_config = body.get("local", {})
        if local_config.get("api_url"):
            local_model = None
            for m in config_data.get("models", []):
                if m.get("source") == "local" and m.get("provider") != "ollama":
                    local_model = m
                    break

            if not local_model:
                local_model = {"source": "local", "provider": "openai"}
                config_data.setdefault("models", []).append(local_model)

            local_model["api_url"] = local_config["api_url"]
            local_model["api_key"] = local_config.get("api_key", "none")
            local_model["model_id"] = local_config.get("model_id", "minicpm-o-4_5")
            local_model["quality_score"] = local_config.get("quality_score", 88)
            local_model["name"] = local_config.get("model_id", "minicpm-o-4_5")

        # 持久化运行时参数（超时/重试）
        if body.get("timeout") or body.get("retry"):
            config_data.setdefault("runtime", {})
            if body.get("timeout"):
                config_data["runtime"]["timeout"] = body["timeout"]
            if body.get("retry") is not None:
                config_data["runtime"]["retry"] = body["retry"]

        # 保存配置
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        # 重新加载模型注册表 + 重建降级链
        global model_registry, all_models, best_config, ai, _fallback_chain
        model_registry = ModelRegistry(config_path)
        all_models = model_registry.get_all_ranked()
        _fallback_chain = model_registry.select_with_fallback()
        print(f"[CONFIG] Reloaded. Fallback chain: {[m['name'] for m in _fallback_chain]}")

        from src.ai_engine.openai_engine import OpenAIEngine

        # 尝试切换到新配置的模型（云端优先，其次本地）
        if cloud_config.get("api_url") and cloud_config.get("api_key"):
            try:
                ai = OpenAIEngine(
                    api_key=cloud_config["api_key"],
                    api_url=cloud_config["api_url"],
                    model=cloud_config.get("model_id", "gpt-4o"),
                )
                best_config = {
                    "name": cloud_config.get("model_id", "gpt-4o"),
                    "source": "cloud",
                    "api_url": cloud_config["api_url"],
                    "api_key": cloud_config["api_key"],
                    "model_id": cloud_config.get("model_id", "gpt-4o"),
                    "quality_score": cloud_config.get("quality_score", 95),
                }
            except Exception as e:
                print(f"[WARN] 切换到云端模型失败: {e}")
        elif local_config.get("api_url"):
            try:
                ai = OpenAIEngine(
                    api_key=local_config.get("api_key", "none"),
                    api_url=local_config["api_url"],
                    model=local_config.get("model_id", "minicpm-o-4_5"),
                )
                best_config = {
                    "name": local_config.get("model_id", "minicpm-o-4_5"),
                    "source": "local",
                    "api_url": local_config["api_url"],
                    "api_key": local_config.get("api_key", "none"),
                    "model_id": local_config.get("model_id", "minicpm-o-4_5"),
                    "quality_score": local_config.get("quality_score", 88),
                }
                print(f"[CONFIG] Switched to local model: {best_config['name']}")
            except Exception as e:
                print(f"[WARN] 切换到本地模型失败: {e}")

        return JSONResponse({"success": True, "message": "配置已保存并热生效", "current_model": best_config.get("name") if best_config else None})

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

@app.get("/v1/models")
async def openai_list_models():
    """列出可用模型 — OpenAI兼容。"""
    models = [{"id": "cnc-ai-brain", "object": "model", "owned_by": "union-cnc", "created": 1700000000}]
    if best_config:
        models.append({"id": best_config["name"], "object": "model", "owned_by": best_config.get("source","local"), "created": 1700000000})
    return JSONResponse(content={"object": "list", "data": models})

# ── HTML 仪表盘 ──
HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>仪表盘 | CNC AI Brain v12.0.0-fusion</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}
h1{color:#38bdf8;font-size:20px;margin-bottom:4px}
.sub{color:#94a3b8;font-size:12px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.card{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155}
.card .label{font-size:11px;color:#94a3b8;margin-bottom:4px}
.card .value{font-size:28px;font-weight:bold}
.card .value.green{color:#22c55e}.card .value.blue{color:#38bdf8}.card .value.yellow{color:#f59e0b}
.bar{background:#1e293b;border-radius:8px;padding:10px 14px;margin-bottom:6px;display:flex;align-items:center;gap:10px}
.bar .tag{font-size:10px;padding:2px 8px;border-radius:4px;background:#2563eb;color:#fff}
.bar .tag.red{background:#dc2626}.bar .tag.green{background:#22c55e}.bar .tag.yellow{background:#f59e0b}
.bar .text{font-size:13px;color:#cbd5e1}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
th{text-align:left;font-size:11px;color:#94a3b8;padding:6px 0;border-bottom:1px solid #334155}
td{padding:6px 0;border-bottom:1px solid #1e293b}
.api-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;margin-top:10px}
.api-item{background:#1e293b;border-radius:8px;padding:10px;font-size:12px}
.api-item .method{color:#38bdf8;font-weight:bold}
.api-item .path{color:#cbd5e1;font-family:monospace;font-size:11px}
h2{font-size:15px;margin:20px 0 10px;color:#94a3b8}
</style></head>
<body>
<h1>⚙️ CNC AI Brain v12.0.0-fusion</h1>
<div class="sub">一句话画STEP + 3D预览 + 上传报价 + 输出打包</div>
<div class="grid">
<div class="card"><div class="label">今日报价</div><div class="value blue" id="cnt-quote">-</div></div>
<div class="card"><div class="label">专家会议</div><div class="value blue" id="cnt-panel">-</div></div>
<div class="card"><div class="label">STEP生成</div><div class="value yellow" id="cnt-step">-</div></div>
<div class="card"><div class="label">审计链</div><div class="value green" id="audit-status">-</div></div>
<div class="card"><div class="label">运行时长</div><div class="value green" id="uptime">-</div></div>
</div>
<h2>📐 报价梯度</h2>
<table><thead><tr><th>材料</th><th>10件</th><th>50件</th><th>单价</th><th>倍率</th></tr></thead><tbody id="price-table"></tbody></table>
<h2>🔒 冲突规则</h2>
<div id="rules-list"></div>
<h2>🔌 API 端点 (v12.0.0-fusion)</h2>
<div class="api-grid" id="api-list"></div>
<script>
(async function(){
  try{
    let h=await fetch('/api/health'),hd=await h.json();
    document.getElementById('uptime').textContent=Math.floor(hd.uptime_seconds/60)+'min';
    let a=await fetch('/api/audit'),ad=await a.json();
    document.getElementById('cnt-quote').textContent=(ad.records||[]).filter(r=>r.event_type==='quote').length;
    document.getElementById('cnt-panel').textContent=(ad.records||[]).filter(r=>r.event_type==='expert_panel').length;
    document.getElementById('cnt-step').textContent=(ad.records||[]).filter(r=>r.event_type==='step_generate').length;
    document.getElementById('audit-status').textContent=ad.chain_valid?'✅':'❌';
    document.getElementById('price-table').innerHTML=[
      ['45钢','¥1,178','¥5,891','¥117.81','基准'],
      ['6061铝合金','¥1,541','¥7,656','¥154.06','1.3x'],
      ['304不锈钢','¥1,813','¥9,063','¥181.25','1.5x'],
      ['316L不锈钢','¥2,175','¥10,875','¥217.50','1.8x'],
      ['钛合金TC4','¥6,344','¥31,719','¥634.38','5.4x'],
    ].map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('');
    document.getElementById('rules-list').innerHTML=[
      ['green','6061+阳极氧化','✅'],
      ['green','45钢+发黑','✅'],
      ['red','304+阳极氧化','❌'],
      ['yellow','304+电镀','⚠️'],
      ['red','钛合金+镀锌','❌'],
      ['yellow','6061+电镀+IT6','⚠️'],
    ].map(r=>'<div class="bar"><span class="tag '+r[0]+'">'+r[1]+'</span><span class="text">'+r[2]+'</span></div>').join('');
    document.getElementById('api-list').innerHTML=[
      ['POST','/api/generate-step','一句话画STEP'],
      ['GET','/api/preview/{file}','3D预览(STL)'],
      ['POST','/api/upload-step','上传STEP自动报价'],
      ['POST','/api/export','输出打包(ZIP)'],
      ['POST','/api/one-click','全链路一键'],
      ['GET','/api/download/{file}','下载ZIP'],
    ].map(r=>'<div class="api-item"><span class="method">'+r[0]+'</span> <span class="path">'+r[1]+'</span><br><span style="font-size:10px;color:#64748b">'+r[2]+'</span></div>').join('');
  }catch(e){console.error(e)}
})();
</script>
</body></html>"""

# ── RAG管理页面 ──
RAG_UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>📚 Union·由你 — 知识库 RAG</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Noto Sans CJK SC','WenQuanYi Micro Hei','Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;padding:20px;max-width:1000px;margin:auto}
h1{color:#38bdf8;font-size:20px;margin-bottom:16px;display:flex;align-items:center;gap:10px}
.card{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #334155}
.card h3{color:#38bdf8;font-size:14px;margin-bottom:8px}
.card .v{font-size:28px;color:#38bdf8;font-weight:bold}
.card .l{font-size:11px;color:#94a3b8}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px}
input,textarea,button{width:100%;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px;color:#e2e8f0;font-size:13px;margin:4px 0}
button{background:#0284c7;color:#fff;cursor:pointer;font-weight:bold;border:none}
button:hover{background:#0369a1}
button.danger{background:#dc2626}
button.success{background:#16a34a}
.result-item{background:#0f172a;border-radius:8px;padding:12px;margin:8px 0;border:1px solid #334155}
.result-item .s{color:#22c55e;font-size:12px}
.tag{display:inline-block;background:#1e40af;color:#93c5fd;font-size:11px;padding:2px 8px;border-radius:10px;margin:2px}
.reg-item{padding:8px;margin:4px 0;border-left:3px solid #334155;font-size:13px}
.reg-item .l{color:#64748b;font-size:11px}
.stats{display:flex;gap:10px;flex-wrap:wrap}
.stat-box{background:#0f172a;border-radius:8px;padding:8px 16px;text-align:center;min-width:80px}
.stat-box .num{font-size:24px;color:#38bdf8;font-weight:bold}
.stat-box .lbl{font-size:11px;color:#94a3b8}
.toast{position:fixed;bottom:24px;right:24px;background:#1e293b;border:1px solid #334155;border-radius:8px;padding:12px 20px;font-size:13px;max-width:300px;z-index:100}
.btn-row{display:flex;gap:8px}
.btn-row button{flex:1}
</style>
</head>
<body>
<h1>📚 知识库 — 小刀切梨 RAG</h1>

<!-- 状态统计 -->
<div class="stats" id="stats"><div class="stat-box"><div class="num">-</div><div class="lbl">文档</div></div></div>

<div class="grid">
<div class="card">
<h3>🔍 自然语言搜索</h3>
<input id="q" placeholder="搜索: 304法兰报价 / 钛合金历史价格 / 相似零件..." />
<button onclick="doSearch()">搜索</button>
<div id="searchResults"></div>
</div>

<div class="card">
<h3>📄 添加文档</h3>
<input id="newId" placeholder="文档ID (可选自动生成)" />
<input id="newTitle" placeholder="标题" />
<textarea id="newContent" rows="3" placeholder="内容 (英文单词之间保留空格，中文自动保持)"></textarea>
<input id="newTags" placeholder="标签 (逗号分隔)" />
<button class="success" onclick="addDoc()">索引</button>
</div>
</div>

<div class="card">
<h3>⚡ 自动索引</h3>
<p style="font-size:12px;color:#94a3b8;margin-bottom:8px">从已有数据源批量索引: 历史订单 + STEP文件 + 审计日志</p>
<div class="btn-row">
<button onclick="autoIndex()">🚀 一键索引</button>
<button onclick="refreshStatus()">🔄 刷新状态</button>
<button class="danger" onclick="clearResults()">🗑️ 清空结果</button>
</div>
<div id="indexResult" style="margin-top:8px;font-size:12px"></div>
</div>

<div class="card">
<h3>📂 层级引索树</h3>
<button onclick="loadRegistry()">展开树</button>
<div id="registryTree" style="margin-top:8px"></div>
</div>

<div class="toast" id="toast" style="display:none"></div>

<script>
async function api(url, data) {
    const opt = data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)} : {};
    const r = await fetch(url, opt); return r.json();
}
function toast(msg, dur=3000) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.style.display = 'block';
    setTimeout(()=>t.style.display='none', dur);
}

async function refreshStatus() {
    const s = await api('/api/rag/status');
    document.getElementById('stats').innerHTML =
        `<div class="stat-box"><div class="num">${s.documents||0}</div><div class="lbl">文档</div></div>` +
        `<div class="stat-box"><div class="num">${s.registry_entries||0}</div><div class="lbl">引索条目</div></div>` +
        `<div class="stat-box"><div class="num">${s.embedding_dim||'-'}</div><div class="lbl">向量维度</div></div>`;
}

async function doSearch() {
    const q = document.getElementById('q').value;
    if(!q) return toast('请输入搜索词');
    const r = await api('/api/rag/search', {query:q, top_k:8});
    const div = document.getElementById('searchResults');
    if (!r.results || r.results.length === 0) {
        div.innerHTML = '<div class="result-item" style="color:#94a3b8">无匹配结果</div>';
        return;
    }
    div.innerHTML = r.results.map(d => {
        const tags = (d.tags||[]).map(t=>'<span class="tag">'+t+'</span>').join('');
        return `<div class="result-item">
            <div style="display:flex;justify-content:space-between">
                <b>${d.title||d.doc_id}</b>
                <span class="s">${d.score > 0 ? '⚡'+d.score : d.method||'关键词'}</span>
            </div>
            <div style="font-size:11px;color:#94a3b8;margin:4px 0">${d.doc_type||'text'} ${d.created_at||''}</div>
            <div style="font-size:12px;margin:4px 0">${d.content_preview||''}</div>
            <div>${tags}</div>
        </div>`;
    }).join('');
    toast('找到 ' + r.results.length + ' 条结果');
}

async function addDoc() {
    const data = {
        doc_id: document.getElementById('newId').value || undefined,
        title: document.getElementById('newTitle').value,
        content: document.getElementById('newContent').value,
        tags: document.getElementById('newTags').value.split(',').map(s=>s.trim()).filter(Boolean)
    };
    if (!data.title || !data.content) return toast('请填写标题和内容');
    const r = await api('/api/rag/index', data);
    if (r.status === 'ok') {
        toast('✅ 索引成功: ' + r.doc_id);
        refreshStatus();
    } else {
        toast('❌ 失败: ' + (r.error||'未知错误'));
    }
}

async function autoIndex() {
    const btn = document.querySelector('button[onclick="autoIndex()"]');
    btn.disabled = true; btn.textContent = '索引中...';
    const r = await api('/api/rag/auto-index');
    const div = document.getElementById('indexResult');
    div.innerHTML = Object.entries(r).map(([k,v]) =>
        `<div>${k}: ${v.status==='ok' ? '✅' : '❌'} ${JSON.stringify(v)}</div>`
    ).join('');
    btn.disabled = false; btn.textContent = '🚀 一键索引';
    refreshStatus();
    toast('✅ 索引完成');
}

async function loadRegistry() {
    const r = await api('/api/rag/registry');
    const div = document.getElementById('registryTree');
    if (!r.items || r.items.length === 0) {
        div.innerHTML = '<div style="color:#94a3b8;font-size:12px">引索树为空, 请先一键索引</div>';
        return;
    }
    div.innerHTML = r.items.map(item =>
        '<div class="reg-item" style="margin-left:'+(item.level*16)+'px">' +
        '<span>' + (item.item_type === 'order' ? '📄' : item.item_type === 'step' ? '🔩' : '📁') + '</span> ' +
        '<b>' + item.name + '</b> ' +
        '<span class="l">' + item.path + '</span>' +
        '</div>'
    ).join('');
}

refreshStatus();
</script>
</body></html>
"""

# ── XAI Reasoning Chain Viewer ──
REASONING_UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>XAI Reasoning Chain | Union CNC AI Brain</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Noto Sans CJK SC','Microsoft YaHei',sans-serif;background:#0f172a;color:#e2e8f0;padding:20px;max-width:1200px;margin:auto}
h1{color:#38bdf8;font-size:22px;margin-bottom:16px;display:flex;align-items:center;gap:10px}
h2{color:#94a3b8;font-size:16px;margin:20px 0 10px}
.card{background:#1e293b;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #334155}
.step{background:#0f172a;border-radius:8px;padding:12px;margin:8px 0;border-left:4px solid #334155}
.step.input_parse{border-color:#3b82f6}.step.feature_extract{border-color:#8b5cf6}
.step.rule_match{border-color:#ef4444}.step.calculation{border-color:#22c55e}
.step.inference{border-color:#f59e0b}.step.exclusion{border-color:#64748b}
.step.conclusion{border-color:#10b981}.step.tool_call{border-color:#06b6d4}
.step.warning{border-color:#f97316}.step.veto{border-color:#dc2626}
.step .header{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.step .num{background:#334155;color:#94a3b8;font-size:10px;padding:2px 8px;border-radius:4px}
.step .type{font-size:10px;padding:2px 8px;border-radius:4px;background:#1e40af;color:#93c5fd}
.step .title{color:#e2e8f0;font-weight:600;font-size:14px}
.step .desc{color:#94a3b8;font-size:12px;margin:4px 0}
.step .evidence{background:#1e293b;padding:8px;border-radius:4px;font-size:11px;color:#64748b;margin-top:6px;max-height:100px;overflow:auto}
.step .conf{display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;margin-top:4px}
.conf.high{background:#166534;color:#86efac}.conf.medium{background:#854d0e;color:#fde047}
.conf.low{background:#991b1b;color:#fca5a5}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-bottom:16px}
.meta .box{background:#0f172a;border-radius:8px;padding:10px;text-align:center}
.meta .box .val{font-size:24px;font-weight:bold;color:#38bdf8}
.meta .box .lbl{font-size:11px;color:#94a3b8}
.chain-list{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.chain-btn{padding:8px 16px;background:#1e293b;border:1px solid #334155;border-radius:8px;
  color:#e2e8f0;cursor:pointer;font-size:12px;transition:all .2s}
.chain-btn:hover{background:#334155;border-color:#3b82f6}
.chain-btn.active{background:#1e40af;border-color:#3b82f6}
select,input{background:#0f172a;border:1px solid #334155;border-radius:8px;padding:8px 12px;color:#e2e8f0;font-size:13px}
button{background:#0284c7;color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:13px}
button:hover{background:#0369a1}
.test-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}
textarea{width:100%;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px;color:#e2e8f0;font-size:12px;font-family:monospace;rows:4}
</style>
</head>
<body>
<h1>XAI Reasoning Chain</h1>
<p style="color:#94a3b8;font-size:13px;margin-bottom:16px">
  Industrial Explainable AI - Every decision shows its full reasoning process
</p>

<div class="meta" id="meta"></div>

<h2>Recent Chains</h2>
<div class="chain-list" id="chainList"></div>
<div id="chainDetail"></div>

<h2>Test XAI Endpoints</h2>
<div class="test-grid">
<div class="card">
<h3 style="color:#38bdf8;font-size:14px;margin-bottom:8px">Conflict Check (XAI)</h3>
<select id="cc-material" style="width:100%;margin:4px 0">
  <option value="304">304 Stainless</option><option value="6061">6061 Aluminum</option>
  <option value="钛合金">Titanium TC4</option><option value="316L">316L Stainless</option>
</select>
<select id="cc-surface" style="width:100%;margin:4px 0">
  <option value="阳极氧化">Anodizing</option><option value="电镀">Plating</option>
  <option value="钝化">Passivation</option><option value="无">None</option>
</select>
<button onclick="testConflict()">Check Conflict (XAI)</button>
<div id="cc-result" style="margin-top:8px;font-size:12px"></div>
</div>
<div class="card">
<h3 style="color:#38bdf8;font-size:14px;margin-bottom:8px">Quote (XAI)</h3>
<select id="q-material" style="width:100%;margin:4px 0">
  <option value="6061">6061 Aluminum</option><option value="304">304 Stainless</option>
  <option value="TC4">Titanium TC4</option><option value="S45C">45 Steel</option>
</select>
<input id="q-qty" type="number" value="10" style="width:100%;margin:4px 0" placeholder="Quantity">
<button onclick="testQuote()">Calculate Quote (XAI)</button>
<div id="q-result" style="margin-top:8px;font-size:12px"></div>
</div>
</div>

<script>
async function api(url,data){
  const opt=data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{};
  const r=await fetch(url,opt);return r.json();
}

async function loadRecent(){
  const d=await api('/api/reasoning/recent');
  const list=document.getElementById('chainList');
  if(!d.chains||d.chains.length===0){
    list.innerHTML='<div style="color:#64748b;font-size:12px">No chains yet. Use the test buttons below.</div>';
    return;
  }
  list.innerHTML=d.chains.map(c=>
    `<div class="chain-btn" onclick="loadChain('${c.chain_id}')">${c.task_type}: ${c.task_title?.substring(0,30)||'chain'}</div>`
  ).join('');
}

async function loadChain(id){
  const c=await api('/api/reasoning/'+id);
  if(c.error){document.getElementById('chainDetail').innerHTML='<div style="color:#ef4444">Not found</div>';return;}
  
  document.getElementById('meta').innerHTML=
    `<div class="box"><div class="val">${c.total_steps}</div><div class="lbl">Steps</div></div>`+
    `<div class="box"><div class="val">${c.elapsed_ms?.toFixed(0)||0}ms</div><div class="lbl">Elapsed</div></div>`+
    `<div class="box"><div class="val">${(c.overall_confidence*100).toFixed(0)}%</div><div class="lbl">Confidence</div></div>`+
    `<div class="box"><div class="val">${c.task_type}</div><div class="lbl">Task Type</div></div>`;

  const steps=c.steps||[];
  document.getElementById('chainDetail').innerHTML=
    `<div class="card"><h2>${c.task_title}</h2>`+
    `<div style="color:#94a3b8;font-size:12px;margin-bottom:12px">${c.overall_conclusion||''}</div>`+
    steps.map(s=>{
      const conf=s.confidence>0.7?'high':s.confidence>0.4?'medium':'low';
      const ev=s.evidence?JSON.stringify(s.evidence,null,1).substring(0,300):'';
      return `<div class="step ${s.step_type}">`+
        `<div class="header"><span class="num">#${s.step_id}</span><span class="type">${s.step_type}</span></div>`+
        `<div class="title">${s.title}</div>`+
        `<div class="desc">${s.description}</div>`+
        (ev?`<div class="evidence">${ev}</div>`:'')+
        `<span class="conf ${conf}">Confidence: ${(s.confidence*100).toFixed(0)}%</span>`+
        (s.formula?`<span style="font-size:10px;color:#64748b;margin-left:8px">Formula: ${s.formula}</span>`:'')+
        `</div>`;
    }).join('')+
    (c.summary?`<div style="margin-top:12px;padding:12px;background:#0f172a;border-radius:8px;font-size:11px;color:#64748b;white-space:pre-wrap">${c.summary}</div>`:'')+
    `</div>`;
}

async function testConflict(){
  const m=document.getElementById('cc-material').value;
  const s=document.getElementById('cc-surface').value;
  document.getElementById('cc-result').innerHTML='Checking...';
  const r=await api('/api/conflict-check-xai',{material:m,surface_treatment:s});
  const rc=r.reasoning_chain;
  document.getElementById('cc-result').innerHTML=
    `<div style="color:${r.valid?'#22c55e':'#ef4444'}">${r.valid?'PASS':'BLOCKED'} - ${r.total_issues} issue(s)</div>`+
    (rc?`<div style="color:#64748b">Chain: ${rc.total_steps} steps, ${(rc.overall_confidence*100).toFixed(0)}% conf</div>`:'');
  if(r.reasoning_chain_id) loadChain(r.reasoning_chain_id);
  loadRecent();
}

async function testQuote(){
  const m=document.getElementById('q-material').value;
  const q=parseInt(document.getElementById('q-qty').value)||10;
  document.getElementById('q-result').innerHTML='Calculating...';
  const r=await api('/api/quote-xai',{material:m,quantity:q,surface_treatment:'无'});
  document.getElementById('q-result').innerHTML=
    `<div style="color:#22c55e">Final: ${r.final_price?.toFixed(2)} yuan | Unit: ${r.unit_price?.toFixed(2)} | Profit: ${(r.profit_rate*100).toFixed(0)}%</div>`+
    (r.reasoning_chain?`<div style="color:#64748b">Chain: ${r.reasoning_chain.total_steps} steps</div>`:'');
  if(r.reasoning_chain_id) loadChain(r.reasoning_chain_id);
  loadRecent();
}

loadRecent();
</script>
</body></html>
"""

# ── HTML 3D预览主页面 — 比赛版 ──
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Union·由你 — CNC AI 工艺大脑</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#08080d;--bg-soft:#0e0e18;--surface:rgba(16,16,26,.72);
  --border:rgba(255,255,255,.08);--border-strong:rgba(255,255,255,.14);
  --text:#ededf0;--text-2:#a1a1aa;--text-3:#71717a;
  --accent:#6366f1;--accent-2:#a855f7;--accent-glow:rgba(99,102,241,.35);
  --ok:#34d399;--warn:#fbbf24;--err:#f87171;
  --radius:14px;--ease:cubic-bezier(.22,1,.36,1);
}
html,body{height:100%}
body{font-family:'Inter','Noto Sans CJK SC','WenQuanYi Micro Hei','Microsoft YaHei',sans-serif;
  background:radial-gradient(1200px 800px at 20% -10%,rgba(99,102,241,.10),transparent 60%),
    radial-gradient(900px 700px at 110% 110%,rgba(168,85,247,.08),transparent 55%),
    linear-gradient(180deg,#0a0a14 0%,#08080d 100%);
  color:var(--text);height:100vh;overflow:hidden;user-select:none;letter-spacing:-.01em;
  -webkit-font-smoothing:antialiased}

/* ===== 顶栏 — 玻璃态 + 微光描边 ===== */
#topbar{position:fixed;top:0;left:0;right:0;z-index:100;height:52px;
  background:linear-gradient(180deg,rgba(10,10,20,.78),rgba(10,10,20,.55));
  backdrop-filter:blur(20px) saturate(140%);-webkit-backdrop-filter:blur(20px) saturate(140%);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 24px;
  box-shadow:0 1px 0 rgba(255,255,255,.04) inset,0 8px 32px rgba(0,0,0,.45)}
#topbar .brand{display:flex;align-items:center;gap:10px;font-size:16px;font-weight:600;letter-spacing:-.02em}
#topbar .brand .logo{width:22px;height:22px;border-radius:6px;
  background:linear-gradient(135deg,var(--accent),var(--accent-2));
  box-shadow:0 0 14px var(--accent-glow),0 0 0 1px rgba(255,255,255,.12) inset;
  display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px;font-weight:700}
#topbar .brand span{color:var(--text-2);font-weight:400;font-size:13px}
#topbar .status{display:flex;align-items:center;gap:14px;font-size:12px;color:var(--text-2)}
#topbar .status .seg{display:flex;align-items:center;gap:6px}
#topbar .status .label{color:var(--text-3);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
#topbar .status .val{color:var(--text);font-weight:500}
#topbar .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);
  box-shadow:0 0 0 0 rgba(52,211,153,.5);animation:breathe 2.4s var(--ease) infinite}
@keyframes breathe{0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,.45)}50%{box-shadow:0 0 0 5px rgba(52,211,153,0)}}

/* ===== 全屏3D背景 ===== */
#viewer{position:fixed;top:0;left:0;width:100%;height:100%;z-index:0}
#viewer-placeholder{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  color:var(--text-3);font-size:13px;text-align:center;pointer-events:none;z-index:1;
  letter-spacing:.02em}
#viewer-placeholder .icon{font-size:42px;margin-bottom:14px;opacity:.55;
  filter:drop-shadow(0 0 18px rgba(99,102,241,.35))}
#viewer-placeholder .hint{margin-top:6px;font-size:11px;color:var(--text-3);opacity:.7}

/* ===== 结果面板 — 玻璃态 + 滑入 ===== */
#result-panel{position:fixed;right:22px;top:72px;width:400px;max-height:calc(100vh - 200px);overflow-y:auto;
  z-index:90;display:none;
  background:var(--surface);backdrop-filter:blur(22px) saturate(140%);-webkit-backdrop-filter:blur(22px) saturate(140%);
  border:1px solid var(--border);border-radius:var(--radius);padding:18px 18px 20px;
  box-shadow:0 1px 0 rgba(255,255,255,.05) inset,0 20px 60px rgba(0,0,0,.55),0 0 0 1px rgba(0,0,0,.4);
  font-size:13px;line-height:1.65;animation:panelIn .42s var(--ease)}
@keyframes panelIn{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:translateX(0)}}
#result-panel .close{position:absolute;top:12px;right:14px;cursor:pointer;color:var(--text-3);
  font-size:15px;line-height:1;width:20px;height:20px;display:flex;align-items:center;justify-content:center;
  border-radius:6px;transition:all .18s var(--ease)}
#result-panel .close:hover{color:var(--text);background:rgba(255,255,255,.06)}
#result-panel h2{color:var(--text);font-size:14px;font-weight:600;margin:2px 0 10px;letter-spacing:-.01em;
  display:flex;align-items:center;gap:8px}
#result-panel h2 .bar{width:3px;height:13px;border-radius:2px;
  background:linear-gradient(180deg,var(--accent),var(--accent-2));box-shadow:0 0 8px var(--accent-glow)}
#result-panel h3{font-size:12px;color:var(--text-2);font-weight:600;margin:14px 0 6px;
  text-transform:uppercase;letter-spacing:.06em}
#result-panel strong{color:var(--text);font-weight:600}
#result-panel a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(99,102,241,.3)}
#result-panel em{color:var(--text-3);font-size:11px;font-style:normal}
#result-panel code{background:rgba(255,255,255,.05);padding:1px 6px;border-radius:4px;
  font-family:'JetBrains Mono','Consolas',monospace;font-size:11px;color:var(--text-2);
  border:1px solid var(--border)}

/* 结构化卡片区块 */
.section{margin-top:14px;padding-top:14px;border-top:1px solid var(--border)}
.section:first-child{margin-top:6px;padding-top:0;border-top:none}
.section-title{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;
  color:var(--text-2);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
.section-title .ico{width:14px;height:14px;opacity:.7}

/* 参数表格 */
.param-table{display:grid;grid-template-columns:1fr auto;gap:1px;
  background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.param-table .row{display:contents}
.param-table .k,.param-table .v{background:rgba(10,10,18,.6);padding:7px 11px;font-size:12px}
.param-table .k{color:var(--text-2);font-family:'JetBrains Mono','Consolas',monospace;font-size:11px}
.param-table .v{color:var(--text);text-align:right;font-family:'JetBrains Mono','Consolas',monospace}
.param-table .v .unit{color:var(--text-3);font-size:10px;margin-left:3px}
.param-table .row{animation:stagger .4s var(--ease) both}
@keyframes stagger{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}

/* 推理链 */
.chain-step{margin:8px 0;padding:10px 12px;border-radius:10px;
  background:rgba(255,255,255,.025);border:1px solid var(--border);
  animation:stagger .4s var(--ease) both;transition:all .2s var(--ease)}
.chain-step:hover{border-color:var(--border-strong);background:rgba(255,255,255,.04)}
.chain-step.winner{border-color:rgba(99,102,241,.45);background:rgba(99,102,241,.08);
  box-shadow:0 0 0 1px rgba(99,102,241,.25),0 0 22px rgba(99,102,241,.18)}
.chain-step .head{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.chain-step .step-type{font-size:11px;font-weight:600;color:var(--text);
  font-family:'JetBrains Mono','Consolas',monospace}
.chain-step .winner-tag{font-size:9px;padding:2px 7px;border-radius:10px;
  background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;font-weight:600;
  letter-spacing:.05em;text-transform:uppercase;box-shadow:0 0 10px var(--accent-glow)}
.chain-step .reasoning{font-size:11px;color:var(--text-2);line-height:1.55;margin-bottom:8px}
.chain-step .conclusion{font-size:12px;color:var(--text);padding:6px 8px;border-radius:6px;
  background:rgba(255,255,255,.04);border:1px solid var(--border)}
.conf-bar{height:4px;border-radius:2px;background:rgba(255,255,255,.06);overflow:hidden;margin-top:8px}
.conf-bar .fill{height:100%;border-radius:2px;
  background:linear-gradient(90deg,var(--accent),var(--accent-2));
  box-shadow:0 0 8px var(--accent-glow);animation:fillIn .6s var(--ease) both}
@keyframes fillIn{from{width:0!important}}
.conf-label{display:flex;justify-content:space-between;font-size:10px;color:var(--text-3);margin-top:4px;
  font-family:'JetBrains Mono','Consolas',monospace}

/* 几何/报价信息网格 */
.info-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.info-card{padding:10px 12px;border-radius:8px;background:rgba(255,255,255,.025);
  border:1px solid var(--border);transition:all .2s var(--ease)}
.info-card:hover{border-color:var(--border-strong);transform:translateY(-1px)}
.info-card .lbl{font-size:10px;color:var(--text-3);text-transform:uppercase;letter-spacing:.06em}
.info-card .val{font-size:16px;font-weight:600;color:var(--text);margin-top:3px;
  font-family:'JetBrains Mono','Consolas',monospace;letter-spacing:-.02em}
.info-card .val .u{font-size:10px;color:var(--text-3);margin-left:2px;font-weight:400}
.info-card.highlight{background:rgba(99,102,241,.08);border-color:rgba(99,102,241,.3)}
.info-card.highlight .val{color:var(--accent)}

/* 下载按钮组 */
.dl-group{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.dl-btn{flex:1;min-width:90px;padding:9px 12px;border-radius:8px;
  background:rgba(255,255,255,.03);border:1px solid var(--border);
  color:var(--text);font-size:11px;font-weight:500;cursor:pointer;text-decoration:none;
  display:flex;align-items:center;justify-content:center;gap:6px;
  transition:all .2s var(--ease);font-family:inherit}
.dl-btn:hover{border-color:rgba(99,102,241,.5);background:rgba(99,102,241,.08);
  transform:translateY(-1px);box-shadow:0 4px 14px rgba(99,102,241,.18)}
.dl-btn .ext{font-size:9px;color:var(--text-3);font-family:'JetBrains Mono','Consolas',monospace;
  padding:1px 5px;border-radius:3px;background:rgba(255,255,255,.05)}

/* 模型信息条 */
.model-bar{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;
  background:rgba(255,255,255,.025);border:1px solid var(--border);font-size:11px;color:var(--text-2)}
.model-bar .name{color:var(--text);font-weight:500;font-family:'JetBrains Mono','Consolas',monospace}
.model-bar .src{color:var(--text-3);margin-left:auto;font-size:10px}

/* ===== 底部输入区 ===== */
#bottom-panel{position:fixed;bottom:0;left:0;right:0;z-index:50;
  background:linear-gradient(transparent,rgba(8,8,13,.92) 35%,rgba(8,8,13,.98));
  padding:28px 32px 22px;display:flex;flex-direction:column;align-items:center;gap:12px}
#input-row{width:100%;max-width:740px;display:flex;gap:8px;
  background:rgba(20,20,32,.6);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border:1px solid var(--border);border-radius:60px;padding:5px;
  transition:all .3s var(--ease);position:relative;overflow:hidden}
#input-row::before{content:'';position:absolute;inset:0;border-radius:60px;padding:1px;
  background:linear-gradient(135deg,rgba(99,102,241,.4),transparent 40%,rgba(168,85,247,.3));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude;opacity:0;transition:opacity .3s}
#input-row:focus-within{border-color:var(--border-strong);box-shadow:0 0 0 4px rgba(99,102,241,.10),0 8px 30px rgba(0,0,0,.4)}
#input-row:focus-within::before{opacity:1}
#input-row input{flex:1;padding:12px 22px;background:transparent;border:none;outline:none;
  color:var(--text);font-size:15px;font-family:inherit;letter-spacing:-.01em}
#input-row input::placeholder{color:var(--text-3);font-size:14px}
#input-row button#send-btn{padding:10px 26px;
  background:linear-gradient(135deg,var(--accent),var(--accent-2));
  border:none;border-radius:40px;color:#fff;font-size:14px;font-weight:600;
  cursor:pointer;white-space:nowrap;transition:all .18s var(--ease);
  box-shadow:0 0 0 1px rgba(255,255,255,.12) inset,0 4px 18px rgba(99,102,241,.4)}
#input-row button#send-btn:hover{transform:translateY(-1px);box-shadow:0 0 0 1px rgba(255,255,255,.18) inset,0 6px 24px rgba(99,102,241,.55)}
#input-row button#send-btn:active{transform:translateY(0) scale(.98)}
#input-row button#send-btn:disabled{opacity:.45;transform:none;cursor:default;box-shadow:none}

/* 快速动作按钮 */
#quick-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
#quick-actions button{padding:7px 16px;background:rgba(20,20,32,.5);backdrop-filter:blur(10px);
  -webkit-backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:40px;
  color:var(--text-2);font-size:12px;cursor:pointer;transition:all .2s var(--ease);font-family:inherit;
  letter-spacing:-.01em}
#quick-actions button:hover{background:rgba(99,102,241,.10);border-color:rgba(99,102,241,.4);
  color:var(--text);transform:translateY(-1px)}
#quick-actions button:active{transform:translateY(0) scale(.97)}

/* ===== Shimmer 骨架屏 ===== */
.skeleton{display:flex;flex-direction:column;gap:10px;padding:4px 0}
.skel-line{height:12px;border-radius:6px;background:linear-gradient(90deg,
  rgba(255,255,255,.04) 0%,rgba(255,255,255,.10) 50%,rgba(255,255,255,.04) 100%);
  background-size:200% 100%;animation:shimmer 1.4s linear infinite}
.skel-line.short{width:55%}.skel-line.mid{width:78%}.skkel-line.long{width:95%}
.skel-block{height:62px;border-radius:8px;border:1px solid var(--border);
  background:linear-gradient(90deg,rgba(255,255,255,.025) 0%,rgba(255,255,255,.06) 50%,rgba(255,255,255,.025) 100%);
  background-size:200% 100%;animation:shimmer 1.4s linear infinite}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
.skel-title{height:13px;width:120px;border-radius:6px;margin-bottom:10px;
  background:linear-gradient(90deg,rgba(99,102,241,.15) 0%,rgba(168,85,247,.25) 50%,rgba(99,102,241,.15) 100%);
  background-size:200% 100%;animation:shimmer 1.4s linear infinite}

/* 加载点 */
.spinner{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 8px var(--accent-glow);animation:pulse 1s var(--ease) infinite}
.spinner:nth-child(2){animation-delay:.18s}.spinner:nth-child(3){animation-delay:.36s}
@keyframes pulse{0%,100%{opacity:.25;transform:scale(.85)}50%{opacity:1;transform:scale(1.1)}}

/* 消息泡泡 */
.msg{width:100%;padding:6px 0}
.msg.bot .reply{color:var(--text);font-size:13px;line-height:1.7}
.msg.bot .reply h2{color:var(--text);font-size:14px;margin:8px 0 4px}
.msg.bot .reply h3{font-size:13px;margin:6px 0 2px;color:var(--text)}
.msg.user{text-align:right;color:var(--text-2);font-size:12px;padding-bottom:0;
  font-family:'JetBrains Mono','Consolas',monospace;opacity:.85}
.msg.user .you{color:var(--accent);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-right:6px}

/* 滚动条 */
#result-panel::-webkit-scrollbar{width:5px}
#result-panel::-webkit-scrollbar-track{background:transparent}
#result-panel::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:4px}
#result-panel::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.16)}

/* 响应式 */
@media (max-width:720px){
  #result-panel{right:10px;left:10px;width:auto;top:64px;max-height:50vh}
  #topbar .status .seg:not(.core){display:none}
  #bottom-panel{padding:20px 14px 16px}
  #input-row{max-width:100%}
  .info-grid{grid-template-columns:1fr}
}
@media (prefers-reduced-motion:reduce){
  *{animation-duration:.01ms!important;transition-duration:.01ms!important}
}
</style>
</head>
<body>

<!-- 顶栏 -->
<div id="topbar">
  <div class="brand">Union<span>·由你</span></div>
  <div class="status"><span class="dot"></span>系统就绪 · 离线端侧</div>
</div>

<!-- 全屏3D预览 -->
<div id="viewer">
  <div id="viewer-placeholder">
    <div class="icon">⚙️</div>
    生成零件后自动显示 3D 预览
  </div>
</div>

<!-- 结果浮动面板 -->
<div id="result-panel">
  <span class="close" onclick="closePanel()">✕</span>
  <div id="result-content"></div>
</div>

<!-- 底部操作区 -->
<div id="bottom-panel">
  <div id="quick-actions">
    <button onclick="quickDemo('flange')">🔩 法兰 100×50×20</button>
    <button onclick="quickDemo('conflict')">⚠️ 304+阳极氧化</button>
    <button onclick="quickDemo('titanium')">🏆 钛合金决策</button>
  </div>
  <div id="input-row">
    <input id="user-input" placeholder="说人话，做零件..." autofocus>
    <button id="send-btn" onclick="send()">生成 →</button>
  </div>
</div>

<script src="/static/three.min.js"></script>
<script>
// ====== 3D - 零外部依赖，纯THREE ======
let scene,camera,renderer,currentMesh;
let theta=0.4,phi=0.7,radius=280,dragging=false,pm={x:0,y:0};

function initViewer(){
    try{
    const v=document.getElementById('viewer');
    scene=new THREE.Scene();scene.background=new THREE.Color(0x0a0a1a);
    camera=new THREE.PerspectiveCamera(40,v.clientWidth/v.clientHeight,1,2000);
    camera.position.set(180,140,220);camera.lookAt(0,0,0);
    renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});
    renderer.setSize(v.clientWidth,v.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
    v.appendChild(renderer.domElement);
    // 手动轨道控制
    renderer.domElement.addEventListener('mousedown',function(e){dragging=true;pm={x:e.clientX,y:e.clientY};});
    renderer.domElement.addEventListener('mousemove',function(e){if(!dragging)return;theta+=(e.clientX-pm.x)*0.005;phi=Math.max(0.1,Math.min(1.5,phi+(e.clientY-pm.y)*0.005));pm={x:e.clientX,y:e.clientY};});
    renderer.domElement.addEventListener('mouseup',function(){dragging=false;});
    renderer.domElement.addEventListener('wheel',function(e){e.preventDefault();radius=Math.max(80,Math.min(600,radius+e.deltaY*0.5));});
    renderer.domElement.addEventListener('touchstart',function(e){if(e.touches.length===1){dragging=true;pm={x:e.touches[0].clientX,y:e.touches[0].clientY};}});
    renderer.domElement.addEventListener('touchmove',function(e){if(!dragging||e.touches.length!==1)return;theta+=(e.touches[0].clientX-pm.x)*0.005;phi=Math.max(0.1,Math.min(1.5,phi+(e.touches[0].clientY-pm.y)*0.005));pm={x:e.touches[0].clientX,y:e.touches[0].clientY};});
    renderer.domElement.addEventListener('touchend',function(){dragging=false;});
    // 光照
    scene.add(new THREE.AmbientLight(0x404060));
    var dl=new THREE.DirectionalLight(0xffffff,1.2);dl.position.set(100,200,150);scene.add(dl);
    var dl2=new THREE.DirectionalLight(0x4488ff,.6);dl2.position.set(-100,-50,-80);scene.add(dl2);
    scene.add(new THREE.GridHelper(300,30,0x222244,0x111133));
    animate();
    }catch(e){console.warn('[CNC] 3D初始化失败:',e.message);}
}
function animate(){
    requestAnimationFrame(animate);
    if(!scene||!camera||!renderer)return;
    theta+=0.003;
    camera.position.x=radius*Math.sin(theta)*Math.cos(phi);
    camera.position.y=radius*Math.sin(phi);
    camera.position.z=radius*Math.cos(theta)*Math.cos(phi);
    camera.lookAt(0,0,0);
    renderer.render(scene,camera);
}
// 内置STL解析器
function loadSTL(url){
    if(!url) return;
    fetch(url).then(function(r){return r.arrayBuffer();}).then(function(buf){
        try{
            if(!scene) initViewer();
            var dv=new DataView(buf),verts=[];
            if(new TextDecoder().decode(buf.slice(0,5))==='solid'){
                var lines=new TextDecoder().decode(buf).split('\\n');
                for(var i=0;i<lines.length;i++){
                    var m=lines[i].match(/\\s*vertex\\s+([\\-+Ee\\d.]+)\\s+([\\-+Ee\\d.]+)\\s+([\\-+Ee\\d.]+)/);
                    if(m) verts.push(parseFloat(m[1]),parseFloat(m[2]),parseFloat(m[3]));
                }
            }else{
                var count=dv.getUint32(80,true);
                for(var i=0;i<count;i++){var off=84+i*50;for(var j=0;j<3;j++){var vo=off+12+j*12;verts.push(dv.getFloat32(vo,true),dv.getFloat32(vo+4,true),dv.getFloat32(vo+8,true));}}
            }
            if(verts.length===0) return;
            var geo=new THREE.BufferGeometry();
            geo.setAttribute('position',new THREE.BufferAttribute(new Float32Array(verts),3));
            geo.computeVertexNormals();
            var mat=new THREE.MeshPhongMaterial({color:0x4488cc,specular:0x222244,shininess:40,transparent:true,opacity:0.9});
            if(currentMesh) scene.remove(currentMesh);
            currentMesh=new THREE.Mesh(geo,mat);
            geo.computeBoundingBox();
            var c=geo.boundingBox.getCenter(new THREE.Vector3());
            currentMesh.position.sub(c);
            scene.add(currentMesh);
            var ph=document.getElementById('viewer-placeholder');
            if(ph) ph.style.display='none';
        }catch(e){console.warn('[CNC] STL解析失败:',e.message);}
    }).catch(function(e){console.warn('[CNC] STL加载失败:',e.message);});
}

// ========== 结果面板 ==========
function showPanel(html){
    document.getElementById('result-content').innerHTML=html;
    document.getElementById('result-panel').style.display='block';
}
function closePanel(){
    document.getElementById('result-panel').style.display='none';
}
function addMsg(role,text){
    let t=text;
    t=t.replace(/### (.+)/g,'<h3>$1</h3>').replace(/## (.+)/g,'<h2>$1</h2>');
    t=t.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
    t=t.replace(/> (.+)/g,'<em>$1</em>').replace(/\\n/g,'<br>');
    if(role==='user'){showPanel('<div class="msg user">🔍 '+t+'</div>');}
    else {showPanel('<div class="msg bot">'+t+'</div>');}
}

// ========== API 调用 ==========
async function send(){
    const input=document.getElementById('user-input');
    const msg=input.value.trim();
    if(!msg) return;
    addMsg('user',msg);
    input.value='';
    const btn=document.getElementById('send-btn');
    btn.disabled=true; btn.textContent='⏳ 处理中...';
    try{
        const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
        const d=await r.json();
        addMsg('bot',d.reply||'无响应');
        if(d.stl_url) loadSTL(d.stl_url);
    }catch(e){addMsg('bot','⚠️ '+e.message);}
    btn.disabled=false; btn.textContent='生成 →';
}

// 快捷演示按钮
async function quickDemo(action){
    const msgs={
        flange:'画一个法兰 外径100内径50厚20 6061 50件 阳极氧化',
        conflict:'304不锈钢 阳极氧化 报价',
        titanium:'钛合金TC4 法兰 50件 IT5公差 预算5万'
    };
    document.getElementById('user-input').value=msgs[action]||'';
    send();
}

// 快捷键
document.getElementById('user-input').addEventListener('keydown',function(e){if(e.key==='Enter') send();});

// 窗口自适应
window.addEventListener('resize',()=>{
    if(!renderer) return;
    const v=document.getElementById('viewer');
    camera.aspect=v.clientWidth/v.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(v.clientWidth,v.clientHeight);
});

// 页面启动时自动初始化3D
window.addEventListener('DOMContentLoaded',()=>initViewer());
</script>
</body>
</html>"""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7862, help="服务端口")
    parser.add_argument("--reload", action="store_true", help="启用热重载")
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info", reload=args.reload)
