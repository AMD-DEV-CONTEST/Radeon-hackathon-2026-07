#!/usr/bin/env python3
"""StagePoster 端到端接口测试。

覆盖 api/server.go Handler() 注册的全部路由，包含前缀路由下的每个子路径。
用法：
    .venv-vllm/bin/python scripts/e2e-test.py [phase ...]

phase 取值：negative assets generate reference poster session all
GPU 相关的 phase（poster / session / generate）会真的出图，单张约 36s。
"""

import hashlib
import io
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8080")
TOKEN = os.environ.get("POSTER_API_TOKEN", "")

PASS, FAIL = [], []
_ctx = ssl._create_unverified_context()


def call(method, path, body=None, headers=None, raw=False, timeout=120):
    url = BASE + path
    data = None
    hdrs = dict(headers or {})

    if TOKEN:
        hdrs.setdefault("Authorization", "Bearer " + TOKEN)

    if body is not None and not raw:
        data = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif raw:
        data = body

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except Exception as exc:  # noqa: BLE001 - 网络层失败也是一条测试结果
        return 0, str(exc).encode(), {}


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    return ok


def expect(name, method, path, want, body=None, headers=None, raw=False,
           timeout=120, verify=None):
    """发一个请求并断言状态码；verify 拿到解析后的 JSON 再做额外断言。"""
    status, payload, resp_headers = call(
        method, path, body, headers, raw, timeout
    )

    wants = want if isinstance(want, (list, tuple)) else [want]
    ok = status in wants
    detail = f"[{method} {path}] -> {status}, want {wants}"

    parsed = None
    if payload[:1] in (b"{", b"["):
        try:
            parsed = json.loads(payload)
        except Exception:  # noqa: BLE001
            parsed = None

    if ok and verify is not None:
        message = verify(parsed, payload, resp_headers)
        if message:
            ok, detail = False, f"[{method} {path}] {message}"

    if not ok and parsed is None:
        detail += f" body={payload[:120]!r}"
    elif not ok:
        detail += f" body={json.dumps(parsed, ensure_ascii=False)[:160]}"

    check(name, ok, detail)
    return parsed if parsed is not None else payload


def multipart(fields, files):
    """手搓 multipart/form-data，避免引入第三方依赖。"""
    boundary = "----e2e" + uuid.uuid4().hex
    buf = io.BytesIO()

    for key, value in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        )
        buf.write(f"{value}\r\n".encode())

    for key, (filename, content) in files.items():
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{key}"; '
            f'filename="{filename}"\r\n'.encode()
        )
        buf.write(f"Content-Type: {ctype}\r\n\r\n".encode())
        buf.write(content)
        buf.write(b"\r\n")

    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), {
        "Content-Type": f"multipart/form-data; boundary={boundary}"
    }


def make_png(width=256, height=256, alpha=True):
    from PIL import Image, ImageDraw

    mode = "RGBA" if alpha else "RGB"
    fill = (0, 0, 0, 0) if alpha else (250, 250, 250)
    image = Image.new(mode, (width, height), fill)
    draw = ImageDraw.Draw(image)
    box = [width // 6, height // 6, width * 5 // 6, height * 5 // 6]
    draw.ellipse(box, fill=(210, 40, 40, 255) if alpha else (210, 40, 40))
    draw.rectangle(
        [width // 3, height // 2, width * 2 // 3, height * 3 // 4],
        fill=(20, 20, 20, 255) if alpha else (20, 20, 20),
    )

    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def make_jpeg(width=512, height=512):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (18, 18, 26))
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        [width // 4, height // 5, width * 3 // 4, height * 3 // 5],
        fill=(230, 200, 150),
    )
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue()


def upload_asset(kind, filename, content):
    """上传一个素材，返回 assetId；失败返回 None。"""
    body, headers = multipart({"kind": kind}, {"file": (filename, content)})
    status, payload, _ = call(
        "POST", "/api/assets", body, headers, raw=True
    )

    if status not in (200, 201):
        return None

    try:
        return json.loads(payload).get("assetId")
    except Exception:  # noqa: BLE001
        return None


EVENT = {
    "title": "E2E 验收之夜",
    "artist": "Test Vector",
    "date": "2026-08-20",
    "time": "20:00",
    "venue": "回声实验场",
    "presalePrice": "¥120",
    "doorPrice": "¥160",
}
VISUAL = {
    "style": "metal-gothic-v1",
    "theme": "工业金属与霓虹废墟",
    "musicGenre": "industrial metal",
    "mood": ["dark", "epic"],
    "preferredColors": ["#1b1b22", "#d94f2b"],
}


def poll_poster(poster_id, wanted, limit=420, label="poster"):
    """轮询到 wanted 之一或终态；顺路记录 progress 字段的演进。"""
    deadline = time.time() + limit
    seen_percent, seen_eta, last = [], [], None

    while time.time() < deadline:
        status, payload, _ = call("GET", f"/api/posters/{poster_id}")
        if status != 200:
            return None, f"GET returned {status}"

        data = json.loads(payload)
        state = data.get("status")
        progress = data.get("progress") or {}

        if progress.get("percent") is not None:
            seen_percent.append(progress["percent"])
        if progress.get("etaSeconds") is not None:
            seen_eta.append(progress["etaSeconds"])

        if state != last:
            print(
                f"    {label}: {state} "
                f"percent={progress.get('percent')} "
                f"eta={progress.get('etaSeconds')} "
                f"stage={progress.get('stage')}"
            )
            last = state

        if state in wanted:
            return data, (seen_percent, seen_eta)
        if state in ("failed", "canceled"):
            return data, (seen_percent, seen_eta)

        time.sleep(3)

    return None, "timeout"


def poll_session(session_id, wanted, limit=420):
    deadline = time.time() + limit
    last = None

    while time.time() < deadline:
        status, payload, _ = call("GET", f"/api/ai/sessions/{session_id}")
        if status != 200:
            return None
        data = json.loads(payload)
        state = data.get("status")

        if state != last:
            print(f"    session: {state}")
            last = state

        if state in wanted or state in (
            "failed", "canceled", "succeeded", "completed_with_warnings"
        ):
            return data

        time.sleep(3)

    return None


# --------------------------------------------------------------------------
# Phase: negative / 只读 —— 不烧 GPU
# --------------------------------------------------------------------------
def phase_negative():
    print("\n=== PHASE negative: 路由、方法、分页、错误语义 ===")

    expect("GET /health", "GET", "/health", 200,
           verify=lambda j, *_: None if j and j.get("status") == "ok"
           else f"unexpected body {j}")

    expect(
        "GET /api/system/dependencies", "GET", "/api/system/dependencies", 200,
        verify=lambda j, *_: None if j and "capabilities" in j
        else "missing capabilities",
    )

    # 集合端点的方法约束
    expect("POST-only /api/posters rejects GET", "GET", "/api/posters", 405)
    expect("POST-only /api/ai/sessions rejects GET", "GET",
           "/api/ai/sessions", 405)
    expect("GET-only /api/jobs rejects POST", "POST", "/api/jobs", 405, body={})
    expect("GET-only /api/assets/{id} rejects POST", "POST",
           "/api/assets/whatever", 405, body={})

    # 分页：越界必须 400，不能静默夹取
    for query, name in [
        ("?limit=0", "limit=0"),
        ("?limit=101", "limit=101"),
        ("?limit=-1", "limit=-1"),
        ("?limit=abc", "limit=abc"),
        ("?offset=-1", "offset=-1"),
        ("?offset=xyz", "offset=xyz"),
    ]:
        expect(f"GET /api/jobs {name} -> 400", "GET", f"/api/jobs{query}", 400)
        expect(f"GET /api/assets {name} -> 400", "GET",
               f"/api/assets{query}", 400)

    def envelope(j, *_):
        for key in ("items", "count", "total", "limit", "offset"):
            if key not in j:
                return f"envelope missing {key}"
        if j["limit"] != 5:
            return f"limit echoed as {j['limit']}"
        if j["count"] != len(j["items"]):
            return "count does not match len(items)"
        return None

    expect("GET /api/jobs pagination envelope", "GET",
           "/api/jobs?limit=5&offset=0", 200, verify=envelope)
    expect("GET /api/assets pagination envelope", "GET",
           "/api/assets?limit=5&offset=0", 200, verify=envelope)
    expect("GET /api/jobs limit=100 accepted", "GET",
           "/api/jobs?limit=100", 200)
    expect("GET /api/jobs huge offset -> empty page", "GET",
           "/api/jobs?limit=5&offset=100000", 200,
           verify=lambda j, *_: None if j["items"] == [] and j["count"] == 0
           else "expected empty page")

    # 缺 id 的前缀路由
    expect("GET /api/posters/ -> 400", "GET", "/api/posters/", 400)
    expect("GET /api/assets/ -> 400", "GET", "/api/assets/", 400)
    expect("GET /api/jobs/ -> 400", "GET", "/api/jobs/", 400)
    expect("GET /api/ai/sessions/ -> 400", "GET", "/api/ai/sessions/", 400)

    # 不存在的资源
    ghost = "poster_e2eghost"
    expect("GET unknown poster -> 404", "GET", f"/api/posters/{ghost}", 404)
    expect("GET unknown poster result -> 404", "GET",
           f"/api/posters/{ghost}/result", 404)
    expect("GET unknown poster thumbnail -> 404", "GET",
           f"/api/posters/{ghost}/thumbnail", 404)
    expect("GET unknown poster timeline -> 404", "GET",
           f"/api/posters/{ghost}/timeline", 404)
    expect("GET unknown poster reviews -> 404", "GET",
           f"/api/posters/{ghost}/reviews", [200, 404])
    expect("GET unknown asset -> 404", "GET", "/api/assets/asset_ghost", 404)
    expect("GET unknown asset content -> 404", "GET",
           "/api/assets/asset_ghost/content", 404)
    expect("GET unknown asset process -> 404", "GET",
           "/api/assets/asset_ghost/process", 404)
    expect("GET unknown job -> 404", "GET", "/api/jobs/job_ghost", 404)
    expect("GET unknown job result -> 404", "GET",
           "/api/jobs/job_ghost/result", 404)
    expect("GET unknown session -> 404", "GET",
           "/api/ai/sessions/session_ghost", 404)

    # 未注册的子路径
    expect("GET bogus poster subroute -> 404", "GET",
           f"/api/posters/{ghost}/bogus", 404)
    expect("GET nested asset subroute -> 404", "GET",
           "/api/assets/a/b/c", 404)
    expect("GET unknown top-level path -> 404", "GET", "/api/nope", 404)
    expect("GET root -> 404", "GET", "/", 404)

    # 请求体校验
    expect("POST /api/posters empty body -> 400", "POST", "/api/posters", 400,
           body={})
    expect("POST /api/posters unknown field -> 400", "POST", "/api/posters",
           400, body={"event": EVENT, "visual": VISUAL, "city": "上海"})
    expect("POST /api/posters bad style -> 400", "POST", "/api/posters", 400,
           body={"event": EVENT,
                 "visual": dict(VISUAL, style="editorial_top")})
    expect("POST /api/posters malformed JSON -> 400", "POST", "/api/posters",
           400, body=b"{not json", raw=True,
           headers={"Content-Type": "application/json"})
    expect("POST /api/generate empty prompt -> 400", "POST", "/api/generate",
           400, body={"prompt": ""})
    expect("POST /api/ai/design no title -> 400", "POST", "/api/ai/design",
           400, body={"event": {}, "visual": VISUAL, "message": "hi"})
    expect("POST /api/assets no file field -> 400", "POST", "/api/assets", 400,
           body=b"", raw=True,
           headers={"Content-Type": "multipart/form-data; boundary=x"})

    # 500 不得回显内部细节
    def no_path_leak(j, payload, _h):
        text = payload.decode("utf-8", "replace")
        for needle in ("/workspace", "/storage/", ".db", "goroutine"):
            if needle in text:
                return f"response leaks {needle!r}: {text[:200]}"
        return None

    expect("404 body carries no filesystem path", "GET",
           f"/api/posters/{ghost}/result", 404, verify=no_path_leak)


# --------------------------------------------------------------------------
# Phase: assets
# --------------------------------------------------------------------------
def phase_assets():
    print("\n=== PHASE assets: 上传、读取、抠图状态 ===")
    created = {}

    def await_processed(asset_id):
        """处理是异步的：等 processStatus 落到终态再断言。"""
        deadline = time.time() + 30
        data = {}

        while time.time() < deadline:
            status, payload, _ = call("GET", f"/api/assets/{asset_id}")
            if status == 200:
                data = json.loads(payload)
                if data.get("processStatus") in ("ready", "failed"):
                    return data
            time.sleep(1)

        return data

    def await_cutout(asset_id, want, label):
        data = await_processed(asset_id)
        cutout = data.get("cutout") or {}

        return check(
            f"{label} cutout settles to {want[0]}",
            cutout.get("status") == want[0]
            and cutout.get("hasAlpha") is want[1],
            f"processStatus={data.get('processStatus')} "
            f"cutout={json.dumps(cutout, ensure_ascii=False)}",
        )

    body, headers = multipart(
        {"kind": "logo"}, {"file": ("e2e-alpha.png", make_png(alpha=True))}
    )
    result = expect("POST /api/assets transparent PNG", "POST", "/api/assets",
                    [200, 201], body=body, headers=headers, raw=True)
    if isinstance(result, dict) and result.get("assetId"):
        created["alpha"] = result["assetId"]
        # 上传响应里两个枚举都不能是空串。
        check(
            "upload response uses real enum values",
            result.get("processStatus") == "pending"
            and (result.get("cutout") or {}).get("status") == "pending",
            f"processStatus={result.get('processStatus')!r} "
            f"cutout={json.dumps(result.get('cutout'))}",
        )
        await_cutout(created["alpha"], ("ready", True), "transparent PNG")

    body, headers = multipart(
        {"kind": "person"}, {"file": ("e2e-opaque.jpg", make_jpeg())}
    )
    result = expect("POST /api/assets opaque JPEG", "POST", "/api/assets",
                    [200, 201], body=body, headers=headers, raw=True)
    if isinstance(result, dict) and result.get("assetId"):
        created["opaque"] = result["assetId"]
        await_cutout(created["opaque"], ("opaque", False), "opaque JPEG")

    body, headers = multipart(
        {"kind": "reference"}, {"file": ("e2e-ref.jpg", make_jpeg(640, 960))}
    )
    result = expect("POST /api/assets reference JPEG", "POST", "/api/assets",
                    [200, 201], body=body, headers=headers, raw=True)
    if isinstance(result, dict) and result.get("assetId"):
        created["reference"] = result["assetId"]

    body, headers = multipart(
        {"kind": "logo"}, {"file": ("e2e.txt", b"not an image at all")}
    )
    expect("POST /api/assets rejects non-image", "POST", "/api/assets",
           [400, 415], body=body, headers=headers, raw=True)

    body, headers = multipart(
        {"kind": "not_a_kind"}, {"file": ("e2e.png", make_png())}
    )
    expect("POST /api/assets rejects bad kind", "POST", "/api/assets", 400,
           body=body, headers=headers, raw=True)

    body, headers = multipart({"kind": "logo"}, {"file": ("empty.png", b"")})
    expect("POST /api/assets rejects empty file", "POST", "/api/assets",
           [400, 415], body=body, headers=headers, raw=True)

    for label, asset_id in created.items():
        await_processed(asset_id)

        expect(f"GET /api/assets/{{id}} ({label})", "GET",
               f"/api/assets/{asset_id}", 200,
               verify=lambda j, *_: None if j.get("assetId")
               else "missing assetId")

        expect(
            f"GET /api/assets/{{id}}/content ({label})", "GET",
            f"/api/assets/{asset_id}/content", 200,
            verify=lambda j, payload, h: None
            if h.get("Content-Type", "").startswith("image/")
            and len(payload) > 100
            else f"ctype={h.get('Content-Type')} len={len(payload)}",
        )

        def steps_ok(j, *_):
            steps = {s["name"]: s["status"] for s in (j.get("steps") or [])}

            # reference 素材走的是色彩 / 构图分析，没有抠图这一步。
            if label == "reference":
                if steps.get("color_analysis") != "completed":
                    return f"color_analysis={steps.get('color_analysis')}"
                if steps.get("composition_analysis") != "completed":
                    return (
                        "composition_analysis="
                        f"{steps.get('composition_analysis')}"
                    )
                return None

            if steps.get("background_removal") != "skipped":
                return f"background_removal={steps.get('background_removal')}"
            if steps.get("alpha_inspection") != "completed":
                return f"alpha_inspection={steps.get('alpha_inspection')}"
            return None

        expect(f"GET /api/assets/{{id}}/process ({label})", "GET",
               f"/api/assets/{asset_id}/process", 200, verify=steps_ok)

    expect("GET /api/assets list includes new uploads", "GET",
           "/api/assets?limit=100", 200,
           verify=lambda j, *_: None
           if any(a.get("assetId") in created.values()
                  for a in j.get("items", []))
           else "uploads absent from list")

    return created


# --------------------------------------------------------------------------
# Phase: reference —— 参考图条件化
# --------------------------------------------------------------------------
def phase_reference(assets):
    print("\n=== PHASE reference: 参考图真的进采样 ===")

    status, payload, _ = call("GET", "/api/system/dependencies")
    capability = {}
    if status == 200:
        capability = (json.loads(payload).get("capabilities") or {}).get(
            "referenceImageConditioning"
        ) or {}

    available = capability.get("available") is True
    print(f"    capability: {json.dumps(capability, ensure_ascii=False)}")

    # 不存在的参考图素材：两条创建路径都必须是 404，不是 500 也不是 502。
    expect("POST /api/generate unknown reference -> 404", "POST",
           "/api/generate", 404,
           body={"prompt": "x", "referenceAssetId": "asset_e2e_ghost"})

    expect("POST /api/posters unknown reference -> 404", "POST",
           "/api/posters", 404,
           body={"event": EVENT,
                 "visual": dict(VISUAL,
                                referenceAssetId="asset_e2e_ghost")})

    if not available:
        check("reference conditioning unavailable is self-describing",
              bool(capability.get("reason")),
              "capability must carry a reason when unavailable")
        return

    reference_id = assets.get("reference") or upload_asset(
        "reference", "e2e-reference.jpg", make_jpeg(640, 960)
    )
    if not reference_id:
        check("reference asset uploaded", False)
        return

    # 越界强度要被收进区间而不是报错。
    expect("POST /api/generate accepts out-of-range strength", "POST",
           "/api/generate", [200, 201, 202],
           body={"prompt": "industrial metal poster, dark ruin",
                 "seed": 515151,
                 "referenceAssetId": reference_id,
                 "controlStrength": 99.0})

    # 同 seed、同 prompt，只差参考图 —— 出图必须不同。
    seed = 313131
    prompt = "industrial metal gig poster, ruined cathedral, volumetric light"
    digests = {}

    for label, body in (
        ("plain", {"prompt": prompt, "seed": seed}),
        ("conditioned", {"prompt": prompt, "seed": seed,
                         "referenceAssetId": reference_id,
                         "controlStrength": 0.75}),
    ):
        status, payload, _ = call("POST", "/api/generate", body)
        if status not in (200, 201, 202):
            check(f"submit {label}", False, f"{status} {payload[:160]}")
            return

        job_id = json.loads(payload)["jobId"]
        deadline = time.time() + 600
        state = None

        while time.time() < deadline:
            status, payload, _ = call("GET", f"/api/jobs/{job_id}")
            if status != 200:
                break
            state = json.loads(payload).get("status")
            if state in ("ready", "succeeded", "failed"):
                break
            time.sleep(3)

        if state not in ("ready", "succeeded"):
            check(f"{label} job completes", False, f"status={state}")
            return

        status, image, _ = call("GET", f"/api/jobs/{job_id}/result")
        if status != 200:
            check(f"{label} result downloadable", False, str(status))
            return

        digests[label] = hashlib.sha256(image).hexdigest()[:16]
        print(f"    {label}: sha={digests[label]} "
              f"{len(image)/1024:.0f} KB")

    # 修复前这两张必然逐字节相同 —— 参考图压根没接进工作流。
    check(
        "reference image changes the generated pixels",
        digests.get("plain") != digests.get("conditioned"),
        f"plain={digests.get('plain')} "
        f"conditioned={digests.get('conditioned')}",
    )


# --------------------------------------------------------------------------
# Phase: generate （裸 ComfyUI 任务）
# --------------------------------------------------------------------------
def phase_generate():
    print("\n=== PHASE generate: 裸任务 + 负向提示词生效 ===")

    seed = 606011
    result = expect(
        # 异步任务返回 202 Accepted，不是 201。
        "POST /api/generate", "POST", "/api/generate", [200, 201, 202],
        body={
            "prompt": "industrial metal gig poster, dark ruin, volumetric light",
            "negativePrompt": "purple, cyan, neon, text, watermark",
            "seed": seed,
        },
    )

    if not isinstance(result, dict) or not result.get("jobId"):
        check("generate returned jobId", False, str(result)[:160])
        return None

    job_id = result["jobId"]
    check("generate echoes seed", result.get("seed") == seed,
          f"seed={result.get('seed')}")

    deadline = time.time() + 300
    state = None
    while time.time() < deadline:
        status, payload, _ = call("GET", f"/api/jobs/{job_id}")
        if status != 200:
            break
        state = json.loads(payload).get("status")
        if state in ("ready", "succeeded", "failed"):
            break
        time.sleep(3)

    check(f"GET /api/jobs/{{id}} reaches ready (got {state})",
          state in ("ready", "succeeded"))

    expect("GET /api/jobs/{id}/result returns image", "GET",
           f"/api/jobs/{job_id}/result", 200,
           verify=lambda j, payload, h: None
           if h.get("Content-Type", "").startswith("image/")
           and len(payload) > 10000
           else f"ctype={h.get('Content-Type')} len={len(payload)}")

    return job_id


# --------------------------------------------------------------------------
# Phase: poster （完整海报流程）
# --------------------------------------------------------------------------
def phase_poster(assets):
    print("\n=== PHASE poster: 创建 -> 候选 -> 选图 -> 合成 -> 出图 ===")

    branding = {}
    if assets.get("alpha"):
        branding["eventLogoAssetId"] = assets["alpha"]

    created = expect(
        "POST /api/posters", "POST", "/api/posters", [200, 201, 202],
        body={"event": EVENT, "branding": branding, "visual": VISUAL},
    )

    if not isinstance(created, dict) or not created.get("posterId"):
        check("poster created", False, str(created)[:200])
        return None

    poster_id = created["posterId"]
    print(f"    posterId={poster_id}")

    # partial_ready 不是可选图状态 —— CLAUDE.md 明确写了它不是终态，
    # reconciler 还要继续处理剩下的候选。必须等到 awaiting_selection。
    data, progress = poll_poster(
        poster_id, ("awaiting_selection",), limit=600
    )
    if not data:
        check("poster reaches awaiting_selection", False, str(progress))
        return poster_id

    check(
        f"poster reaches awaiting_selection (got {data.get('status')})",
        data.get("status") == "awaiting_selection",
    )

    if isinstance(progress, tuple):
        percents, etas = progress
        check("progress.percent advances monotonically",
              percents == sorted(percents) and len(set(percents)) > 1,
              f"percent samples={percents[:12]}")
        check("progress.etaSeconds present and decreasing",
              len(etas) > 1 and etas[-1] <= etas[0],
              f"eta samples={etas[:12]}")

    candidates = data.get("candidates") or []
    ready = [c for c in candidates if c.get("status") == "ready"]
    check(f"candidates ready ({len(ready)}/{len(candidates)})", len(ready) >= 1)

    if not ready:
        return poster_id

    for candidate in ready[:2]:
        cid = candidate.get("candidateId")
        expect(
            f"GET candidate image {cid}", "GET",
            f"/api/posters/{poster_id}/candidates/{cid}/image", 200,
            verify=lambda j, payload, h: None
            if h.get("Content-Type", "").startswith("image/")
            and len(payload) > 10000
            else f"ctype={h.get('Content-Type')} len={len(payload)}",
        )

    expect("GET candidate image with bogus id -> 404", "GET",
           f"/api/posters/{poster_id}/candidates/cand_ghost/image", 404)

    def timeline_ok(j, *_):
        # 这个端点返回的是海报快照 + 复审记录 + 任务级 metrics，
        # 没有独立的事件流数组。
        for key in ("posterId", "poster", "reviews", "metrics"):
            if key not in j:
                return f"missing {key}; got {list(j)}"
        if "wallClockSeconds" not in (j.get("metrics") or {}):
            return f"metrics missing wallClockSeconds: {j.get('metrics')}"
        return None

    expect("GET /api/posters/{id}/timeline", "GET",
           f"/api/posters/{poster_id}/timeline", 200, verify=timeline_ok)

    expect("POST select with bogus candidate -> 400/404", "POST",
           f"/api/posters/{poster_id}/select", [400, 404],
           body={"candidateId": "cand_ghost"})

    chosen = ready[0]["candidateId"]
    expect("POST /api/posters/{id}/select", "POST",
           f"/api/posters/{poster_id}/select", [200, 202],
           body={"candidateId": chosen})

    data, _ = poll_poster(
        poster_id, ("succeeded", "completed_with_warnings"), limit=480,
        label="compose"
    )
    check(
        f"poster composes to terminal success "
        f"(got {data.get('status') if data else 'timeout'})",
        bool(data) and data.get("status") in
        ("succeeded", "completed_with_warnings"),
    )

    for kind, path in (("result", "result"), ("thumbnail", "thumbnail")):
        expect(
            f"GET /api/posters/{{id}}/{kind}", "GET",
            f"/api/posters/{poster_id}/{path}", 200,
            verify=lambda j, payload, h: None
            if h.get("Content-Type", "").startswith("image/")
            and len(payload) > 5000
            else f"ctype={h.get('Content-Type')} len={len(payload)}",
        )

    def reviews_envelope(j, *_):
        for key in ("items", "count", "total", "limit", "offset"):
            if key not in j:
                return f"envelope missing {key}; got {list(j)}"
        # reviews 是 items 的历史别名，两者必须一致。
        if j.get("reviews") != j.get("items"):
            return "reviews alias diverges from items"
        return None

    expect("GET /api/posters/{id}/reviews envelope", "GET",
           f"/api/posters/{poster_id}/reviews?limit=10&offset=0", 200,
           verify=reviews_envelope)

    expect("GET reviews rejects limit=0", "GET",
           f"/api/posters/{poster_id}/reviews?limit=0", 400)

    print("    triggering an explicit review round (VLM)...")
    expect("POST /api/posters/{id}/review", "POST",
           f"/api/posters/{poster_id}/review", [200, 201, 202, 409],
           timeout=300)

    expect("GET reviews after review round", "GET",
           f"/api/posters/{poster_id}/reviews", 200,
           verify=lambda j, *_: None if j.get("total", 0) >= 1
           else f"no review rows: total={j.get('total')}")

    return poster_id


def phase_poster_lifecycle():
    """cancel 与 candidate retry —— 单独一张海报，不干扰主流程。"""
    print("\n=== PHASE poster lifecycle: cancel / retry ===")

    created = expect(
        "POST /api/posters (lifecycle)", "POST", "/api/posters",
        [200, 201, 202],
        body={"event": dict(EVENT, title="E2E 取消测试"), "visual": VISUAL},
    )
    if not isinstance(created, dict) or not created.get("posterId"):
        return

    poster_id = created["posterId"]
    time.sleep(6)

    expect("POST /api/posters/{id}/cancel", "POST",
           f"/api/posters/{poster_id}/cancel", [200, 202, 409])

    data, _ = poll_poster(poster_id, ("canceled",), limit=90, label="cancel")
    check(
        f"canceled poster settles (got {data.get('status') if data else '?'})",
        bool(data) and data.get("status") in ("canceled", "failed",
                                              "succeeded"),
    )

    expect("cancel spelling is single-l 'canceled'", "GET",
           f"/api/posters/{poster_id}", 200,
           verify=lambda j, *_: None if j.get("status") != "cancelled"
           else "status uses British 'cancelled'")

    expect("POST cancel on unknown poster -> 404", "POST",
           "/api/posters/poster_e2eghost/cancel", 404)
    # 已取消的海报上，状态检查先于候选 ID 校验，所以 409 也是对的。
    expect("POST retry on unknown candidate -> 404/409", "POST",
           f"/api/posters/{poster_id}/candidates/cand_ghost/retry",
           [404, 409])


# --------------------------------------------------------------------------
# Phase: session （AI 会话）
# --------------------------------------------------------------------------
def phase_session(assets):
    print("\n=== PHASE session: AI 会话全流程 ===")

    # 单独跑 session phase 时没经过 assets phase，得自己传素材，
    # 否则"使用证据"那条断言会因为压根没绑素材而假失败。
    assets = dict(assets or {})
    if not assets.get("opaque"):
        assets["opaque"] = upload_asset(
            "person", "session-performer.jpg", make_jpeg()
        )
    if not assets.get("alpha"):
        assets["alpha"] = upload_asset(
            "logo", "session-logo.png", make_png(alpha=True)
        )

    def design_ok(j, *_):
        # 响应是 {"result": {...}, "metrics": {...}}，plans 在 result 里面。
        result = j.get("result") or {}
        if not result.get("plans") and not result.get("reply"):
            return f"no plans/reply under result: {list(j)}"
        return None

    expect("POST /api/ai/design", "POST", "/api/ai/design", 200,
           body={"event": EVENT, "visual": VISUAL,
                 "message": "想要更压抑的工业感，主视觉别出现文字"},
           timeout=300, verify=design_ok)

    bind = []
    if assets.get("opaque"):
        bind.append({"assetId": assets["opaque"], "purpose": "performer"})

    created = expect(
        "POST /api/ai/sessions", "POST", "/api/ai/sessions",
        [200, 201, 202],
        body={"brief": {"event": EVENT, "visual": VISUAL, "branding": {}},
              "assets": bind},
        timeout=300,
    )
    if not isinstance(created, dict) or not created.get("sessionId"):
        check("session created", False, str(created)[:200])
        return None

    session_id = created["sessionId"]
    print(f"    sessionId={session_id}")

    expect("GET /api/ai/sessions/{id}", "GET",
           f"/api/ai/sessions/{session_id}", 200,
           verify=lambda j, *_: None if j.get("sessionId") == session_id
           else "id mismatch")

    if assets.get("alpha"):
        expect("POST /api/ai/sessions/{id}/assets", "POST",
               f"/api/ai/sessions/{session_id}/assets", [200, 201],
               body={"assets": [{"assetId": assets["alpha"],
                                 "purpose": "event_logo"}]})

    expect("POST bind unknown asset -> 400/404", "POST",
           f"/api/ai/sessions/{session_id}/assets", [400, 404],
           body={"assets": [{"assetId": "asset_ghost",
                             "purpose": "event_logo"}]})

    expect("POST bind bad purpose -> 400", "POST",
           f"/api/ai/sessions/{session_id}/assets", 400,
           body={"assets": [{"assetId": assets.get("alpha", "asset_ghost"),
                             "purpose": "mascot"}]})

    expect("POST empty message -> 400", "POST",
           f"/api/ai/sessions/{session_id}/messages", 400,
           body={"content": "   "})

    print("    sending a message (VLM, may take a while)...")
    reply = expect(
        "POST /api/ai/sessions/{id}/messages", "POST",
        f"/api/ai/sessions/{session_id}/messages", 200,
        body={"content": "主视觉要一个金属王座，暗红打光，不要任何文字"},
        timeout=420,
        verify=lambda j, *_: None if j.get("session")
        else f"no session in reply: {list(j)}",
    )

    if isinstance(reply, dict) and reply.get("session"):
        session = reply["session"]
        metrics = reply.get("metrics") or {}
        check("message reply carries metrics",
              metrics.get("latencyMs", 0) > 0,
              json.dumps(metrics))

        used = [
            a for a in (session.get("assets") or [])
            if a.get("actuallyUsed")
        ]
        check(
            "bound asset records real usage evidence",
            bool(used) and "brief" in (used[0].get("usedInStage") or []),
            json.dumps(
                [{"id": a.get("assetId"), "used": a.get("actuallyUsed"),
                  "stage": a.get("usedInStage")}
                 for a in (session.get("assets") or [])],
                ensure_ascii=False,
            ),
        )

    data = poll_session(
        session_id, ("awaiting_plan_selection", "needs_user_input"), limit=300
    )
    plans = (data or {}).get("plans") or []
    check(f"session produced design plans ({len(plans)})", len(plans) >= 1,
          f"status={(data or {}).get('status')}")

    if not plans:
        expect("POST /api/ai/sessions/{id}/cancel", "POST",
               f"/api/ai/sessions/{session_id}/cancel", [200, 202])
        return session_id

    expect("POST confirm unknown plan -> 404", "POST",
           f"/api/ai/sessions/{session_id}/plans/plan_ghost/confirm",
           [400, 404])

    plan_id = plans[0].get("planId")
    expect("POST /api/ai/sessions/{id}/plans/{planId}/confirm", "POST",
           f"/api/ai/sessions/{session_id}/plans/{plan_id}/confirm",
           [200, 202], timeout=300)

    data = poll_session(session_id, ("awaiting_candidate_selection",),
                        limit=600)
    state = (data or {}).get("status")
    check(f"session reaches candidate selection (got {state})",
          state == "awaiting_candidate_selection")

    if state != "awaiting_candidate_selection":
        expect("POST cancel session", "POST",
               f"/api/ai/sessions/{session_id}/cancel", [200, 202, 409])
        return session_id

    poster = data.get("poster") or {}
    ready = [c for c in (poster.get("candidates") or [])
             if c.get("status") == "ready"]
    check(f"session candidates ready ({len(ready)})", len(ready) >= 1)

    if not ready:
        return session_id

    expect("POST select unknown candidate -> 400/404", "POST",
           f"/api/ai/sessions/{session_id}/candidates/cand_ghost/select",
           [400, 404])

    cid = ready[0]["candidateId"]
    expect("POST /api/ai/sessions/{id}/candidates/{cid}/select", "POST",
           f"/api/ai/sessions/{session_id}/candidates/{cid}/select",
           [200, 202], timeout=300)

    data = poll_session(session_id,
                        ("succeeded", "completed_with_warnings"), limit=900)
    state = (data or {}).get("status")
    check(f"session composes (got {state})",
          state in ("succeeded", "completed_with_warnings", "looping",
                    "needs_user_input"))

    expect("POST /api/ai/sessions/{id}/finalize", "POST",
           f"/api/ai/sessions/{session_id}/finalize", [200, 202, 409],
           timeout=600)

    final = poll_session(session_id,
                         ("succeeded", "completed_with_warnings"), limit=600)
    if final:
        summary = final.get("reviewSummary") or {}
        print(f"    reviewSummary={json.dumps(summary, ensure_ascii=False)}")
        poster_out = final.get("poster") or {}
        if poster_out.get("posterId"):
            expect("session poster result downloadable", "GET",
                   f"/api/posters/{poster_out['posterId']}/result",
                   [200, 404, 409])

    # 取消一个新建会话，确认拼写与幂等
    created = expect("POST /api/ai/sessions (cancel target)", "POST",
                     "/api/ai/sessions", [200, 201, 202],
                     body={"brief": {"event": EVENT, "visual": VISUAL,
                                     "branding": {}}}, timeout=300)
    if isinstance(created, dict) and created.get("sessionId"):
        victim = created["sessionId"]
        expect("POST cancel session", "POST",
               f"/api/ai/sessions/{victim}/cancel", [200, 202])
        expect("canceled session uses single-l spelling", "GET",
               f"/api/ai/sessions/{victim}", 200,
               verify=lambda j, *_: None if j.get("status") == "canceled"
               else f"status={j.get('status')}")
        expect("cancel is idempotent", "POST",
               f"/api/ai/sessions/{victim}/cancel", [200, 202, 409])

    expect("POST cancel unknown session -> 404", "POST",
           "/api/ai/sessions/session_ghost/cancel", 404)
    expect("POST finalize unknown session -> 404", "POST",
           "/api/ai/sessions/session_ghost/finalize", 404)
    expect("POST message to unknown session -> 404", "POST",
           "/api/ai/sessions/session_ghost/messages", 404,
           body={"content": "hello"})

    return session_id


def main():
    phases = sys.argv[1:] or ["all"]
    run_all = "all" in phases
    started = time.time()

    print(f"StagePoster E2E  base={BASE}  phases={phases}")

    assets = {}

    if run_all or "negative" in phases:
        phase_negative()

    if run_all or "assets" in phases:
        assets = phase_assets()

    if run_all or "generate" in phases:
        phase_generate()

    if run_all or "reference" in phases:
        phase_reference(assets)

    if run_all or "poster" in phases:
        phase_poster(assets)
        phase_poster_lifecycle()

    if run_all or "session" in phases:
        phase_session(assets)

    elapsed = int(time.time() - started)
    print(f"\n===== RESULT  pass={len(PASS)}  fail={len(FAIL)}  "
          f"elapsed={elapsed}s =====")

    if FAIL:
        print("FAILED:")
        for name in FAIL:
            print(f"  - {name}")
        return 1

    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
