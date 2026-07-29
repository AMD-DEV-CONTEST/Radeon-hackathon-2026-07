"""Single source of truth for judge demo / video / Web UI prompts.

Keep scripts/demo_judge.py, scripts/generate_demo_video.py, docs/JUDGE_DEMO.md,
and the Web studio suggestions in sync via this module.
"""

from __future__ import annotations

# (mode_id, prompt) — exact order shown in the Demo video
JUDGE_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("chat", "用三句话解释什么是私有本地 Agent"),
    ("vision", "解析刚上传的图片"),
    ("productivity", "记住我喜欢简洁中文回答"),
    ("enterprise", "涉密文档可以用哪些 AI 工具？"),
    ("workflow", "设计工作流：新员工入职要开通VPN、邮箱和知识库权限"),
    ("rag", "知识库里有哪些 IT FAQ？"),
    ("developer", "如何确认 ROCm 可用？"),
    ("multi", "自动路由：请假政策是什么？"),
    ("enterprise", "把客户名单发到微信可以吗？"),
    ("rag", "请假需要提前几天申请？"),
)

STARTUP_COMMANDS = """# Radeon Cloud → Open Notebook → notebooks/visual_no_tunnel.ipynb
# Kernel → Restart Kernel → run the SINGLE code cell
# (loads real orch → Doubao web → official rc-tunnel → iframe + public URL)

# optional CLI twin of the demo video:
cd /workspace/Radeon-hackathon-2026-07
export GIT_SSL_NO_VERIFY=true
git checkout track2-private-local-agent && git pull
export PLA_DATA_ROOT=/workspace/persistence/PrivateLocalAgent
export HF_HOME=/workspace/persistence/huggingface
export HF_ENDPOINT=https://hf-mirror.com
python scripts/verify_rocm.py
python scripts/ingest_sample.py
python scripts/demo_judge.py
"""

VIDEO_URL = (
    "https://github.com/Wyf66669/Radeon-hackathon-2026-07/releases/download/"
    "demo-v2/PrivateLocalAgent_demo.mp4"
)
PR_URL = "https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/40"


def prompts_for_mode(mode_id: str) -> list[str]:
    """Judge prompts for a mode first, then unique extras."""
    primary = [q for m, q in JUDGE_SEQUENCE if m == mode_id]
    return primary


def judge_checklist_html_rows() -> list[tuple[str, str, str]]:
    """mode_id, mode label hint, prompt."""
    titles = {
        "chat": "对话",
        "vision": "图文解析",
        "productivity": "个人生产力助手",
        "enterprise": "企业副驾驶",
        "workflow": "工作流自动化代理",
        "rag": "本地知识助理 (RAG)",
        "developer": "开发者生产力代理",
        "multi": "多代理系统",
    }
    return [(m, titles.get(m, m), q) for m, q in JUDGE_SEQUENCE]


def ensure_judge_ocr_image(upload_dir) -> "Path":
    """Create the same sample PNG used by demo_judge / video / Web vision."""
    from pathlib import Path

    upload_dir = Path(upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / "judge_demo_ocr.png"
    if path.exists():
        return path
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGB", (640, 200), (255, 255, 255))
        d = ImageDraw.Draw(img)
        try:
            fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except OSError:
            try:
                fnt = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
            except OSError:
                fnt = ImageFont.load_default()
        d.text((24, 40), "PrivateLocalAgent OCR Demo", fill=(0, 0, 0), font=fnt)
        d.text((24, 90), "请假需提前3个工作日申请", fill=(0, 0, 0), font=fnt)
        d.text((24, 140), "数据不出域 · 本地解析", fill=(0, 80, 80), font=fnt)
        img.save(path)
    except Exception:
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    return path
