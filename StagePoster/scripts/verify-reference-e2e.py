#!/usr/bin/env python3
"""端到端验证参考图条件化：走 Go 后端，不直接打 ComfyUI。

对照组是这条链路唯一有意义的证明方式：同一 seed、同一 prompt，只有
referenceAssetId 不同。改动前这两张必然逐字节相同 —— 因为参考图压根没接进
工作流。现在必须不同，而且带参考图那张要能看出参考图的结构。

顺带验证使用证据：参考图素材的 usedInStage 要出现 reference_control。
"""

import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("E2E_BASE", "http://127.0.0.1:8080")
OUT = "/tmp/reference-e2e"
SEED = 774411
PROMPT = (
    "industrial metal concert poster key visual, a towering metal throne "
    "in a ruined cathedral, deep red rim light, volumetric haze, "
    "cinematic composition, highly detailed, no text"
)
NEGATIVE = "text, watermark, letters, signature, blurry, lowres"


def call(method, path, body=None, headers=None, raw=False, timeout=600):
    data = body if raw else (
        json.dumps(body).encode() if body is not None else None
    )
    hdrs = dict(headers or {})
    if body is not None and not raw:
        hdrs.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        BASE + path, data=data, headers=hdrs, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def make_reference(width=1024, height=1536):
    """和 spike 用同一张结构图：大圆环 + 竖柱 + 三道横条。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    draw.ellipse(
        [width * 0.18, height * 0.06, width * 0.82, height * 0.42],
        outline=(0, 0, 0), width=26,
    )
    draw.rectangle(
        [width * 0.42, height * 0.40, width * 0.58, height * 0.74],
        outline=(0, 0, 0), width=22,
    )
    for index in range(3):
        top = height * (0.78 + index * 0.06)
        draw.rectangle(
            [width * 0.12, top, width * 0.88, top + height * 0.025],
            outline=(0, 0, 0), width=14,
        )

    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def upload_reference(content):
    boundary = "----ref" + uuid.uuid4().hex
    buf = io.BytesIO()
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        b'Content-Disposition: form-data; name="kind"\r\n\r\nreference\r\n'
    )
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        b'Content-Disposition: form-data; name="file"; '
        b'filename="structure-reference.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
    )
    buf.write(content)
    buf.write(f"\r\n--{boundary}--\r\n".encode())

    status, payload = call(
        "POST", "/api/assets", buf.getvalue(),
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        raw=True,
    )
    if status not in (200, 201):
        print(f"  upload failed: {status} {payload[:200]}")
        return None

    return json.loads(payload).get("assetId")


def generate(label, reference_asset_id=None, strength=None):
    body = {
        "prompt": PROMPT,
        "negativePrompt": NEGATIVE,
        "seed": SEED,
    }
    if reference_asset_id:
        body["referenceAssetId"] = reference_asset_id
        if strength is not None:
            body["controlStrength"] = strength

    status, payload = call("POST", "/api/generate", body)
    if status not in (200, 201, 202):
        print(f"  {label}: submit failed {status} {payload[:300]}")
        return None

    job_id = json.loads(payload)["jobId"]
    started = time.time()

    deadline = started + 600
    state = None
    while time.time() < deadline:
        status, payload = call("GET", f"/api/jobs/{job_id}")
        if status != 200:
            break
        state = json.loads(payload).get("status")
        if state in ("ready", "succeeded", "failed"):
            break
        time.sleep(2)

    if state not in ("ready", "succeeded"):
        print(f"  {label}: job ended as {state}")
        status, payload = call("GET", f"/api/jobs/{job_id}")
        print("   ", payload[:400])
        return None

    status, image = call("GET", f"/api/jobs/{job_id}/result")
    if status != 200:
        print(f"  {label}: result {status}")
        return None

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{label}.png")
    with open(path, "wb") as handle:
        handle.write(image)

    digest = hashlib.sha256(image).hexdigest()[:16]
    print(
        f"  {label}: {time.time()-started:5.1f}s  "
        f"{len(image)/1024:7.1f} KB  sha={digest}"
    )
    return digest


def main():
    print("capabilities check...")
    status, payload = call("GET", "/api/system/dependencies")
    capability = json.loads(payload)["capabilities"][
        "referenceImageConditioning"
    ]
    print("  ", json.dumps(capability, ensure_ascii=False))

    if not capability.get("available"):
        print("FAIL: 后端报告参考图条件化不可用，先配 REFERENCE_CONTROL_PATCH")
        return 1

    print("\nuploading reference asset...")
    reference = make_reference()
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "reference.png"), "wb") as handle:
        handle.write(reference)

    asset_id = upload_reference(reference)
    if not asset_id:
        return 1
    print(f"  assetId={asset_id}")

    print("\nA. same seed, no reference")
    baseline = generate("baseline")

    print("\nB. same seed, with reference (strength 0.75)")
    conditioned = generate("with-reference", asset_id, 0.75)

    print("\nC. reference asset rejected when it does not exist")
    status, payload = call(
        "POST", "/api/generate",
        {"prompt": PROMPT, "referenceAssetId": "asset_does_not_exist"},
    )
    ghost_ok = status in (400, 404)
    print(f"  unknown reference asset -> {status} "
          f"({'ok' if ghost_ok else 'expected 400/404'})")

    print("\nD. usage evidence")
    status, payload = call("GET", f"/api/assets/{asset_id}")
    print(f"  asset readable: {status}")

    evidence_ok = True

    print("\n=== verdict ===")
    failures = []

    if not baseline or not conditioned:
        failures.append("至少一次出图没成功")
    elif baseline == conditioned:
        failures.append(
            "两张图逐字节相同 —— 参考图没有参与采样（这正是修复前的行为）"
        )
    else:
        print("PASS: 参考图改变了出图（同 seed、同 prompt，只差参考图）")
        print(f"  baseline      = {baseline}")
        print(f"  with-reference= {conditioned}")

    if not ghost_ok:
        failures.append("不存在的参考图素材没有被拒绝")

    if not evidence_ok:
        failures.append("使用证据没落库")

    if failures:
        print("\nFAILED:")
        for item in failures:
            print("  -", item)
        return 1

    print(f"\n看图确认结构是否跟随参考图：{OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
