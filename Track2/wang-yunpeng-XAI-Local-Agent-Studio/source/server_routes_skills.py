"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_skill_learn(h):
    """POST /api/skill/learn — 一键学习：从 URL 获取 SKILL.md 内容并注册"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {url}"})
        return
    url = (data.get("url") or "").strip()
    if not url:
        h._json_response(400, {"error": "url 不能为空"})
        return
    try:
        import urllib.request as _ur
        raw_url = url
        skill_name = ""
        if "github.com" in url:
            # GitHub URL → 自动拼接 raw URL 读取 SKILL.md
            raw_base = url.replace("https://github.com", "https://raw.githubusercontent.com").rstrip("/")
            raw_url = f"{raw_base}/main/SKILL.md"
            # 从 GitHub URL 提取名称：取最后一段路径
            parts = [p for p in url.rstrip("/").split("/") if p]
            skill_name = parts[-1] if parts else ""
        # 获取内容
        req = _ur.Request(raw_url, headers={"User-Agent": "XAI-Skill-Learner/1.0"})
        with _ur.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        if not skill_name:
            # 尝试从 URL 最后一段提取名称
            parts = [p for p in url.rstrip("/").split("/") if p]
            skill_name = parts[-1] if parts else "learned-skill"
        # 去除 .md 后缀作为名称
        if skill_name.endswith(".md"):
            skill_name = skill_name[:-3]
        # 自动注册
        configs = h._skill_load()
        new_skill = {
            "id": h._skill_next_id(configs),
            "name": skill_name,
            "description": f"从 {url} 学习",
            "source_type": "github" if "github.com" in url else "url",
            "source_url": url,
            "content": content,
            "enabled": True,
        }
        configs.append(new_skill)
        h._skill_save(configs)
        h._json_response(200, {"ok": True, "skill": new_skill, "content_length": len(content)})
    except Exception as e:
        h._json_response(400, {"ok": False, "error": f"一键学习失败: {e}"})

def _handle_skills_create(h):
    """POST /api/skills/create → 创建技能"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, trigger, body, source}"})
        return
    name = (data.get("name") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    skill = {
        "name": name,
        "trigger": data.get("trigger", ""),
        "body": data.get("body", ""),
        "source": data.get("source", "manual"),
    }
    try:
        skills_dir = h._skills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        file_path = skills_dir / f"{safe_name}_skill.json"
        file_path.write_text(json.dumps(skill, ensure_ascii=False, indent=2), encoding="utf-8")
        h._json_response(200, {"ok": True, "skill": skill, "file": str(file_path)})
    except Exception as e:
        h._json_response(500, {"error": f"创建技能失败: {e}"})

def _handle_skills_delete(h):
    """POST /api/skills/delete → 删除技能"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name}"})
        return
    name = (data.get("name") or data.get("id") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    try:
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        file_path = h._skills_dir() / f"{safe_name}_skill.json"
        if not file_path.exists():
            h._json_response(404, {"ok": False, "error": f"技能 '{name}' 不存在"})
            return
        file_path.unlink()
        h._json_response(200, {"ok": True, "deleted": name})
    except Exception as e:
        h._json_response(500, {"error": f"删除技能失败: {e}"})

def _handle_skills_list(h):
    """GET /api/skills → 列出所有技能"""
    try:
        skills_dir = h._skills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        skills = []
        for f in sorted(skills_dir.glob("*_skill.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                skills.append({
                    "name": data.get("name", f.stem.replace("_skill", "")),
                    "trigger": data.get("trigger", ""),
                    "body": data.get("body", ""),
                    "source": data.get("source", ""),
                })
            except Exception:
                continue
        h._json_response(200, {"skills": skills})
    except Exception as e:
        h._json_response(500, {"error": f"读取技能列表失败: {e}"})

def _handle_skills_update(h):
    """POST /api/skills/update → 按 name 更新文件式技能"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, trigger, body, source}"})
        return
    name = (data.get("name") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    try:
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
        skills_dir = h._skills_dir()
        file_path = skills_dir / f"{safe_name}_skill.json"
        if not file_path.exists():
            h._json_response(404, {"ok": False, "error": f"技能 '{name}' 不存在"})
            return
        skill = {
            "name": name,
            "trigger": data.get("trigger", ""),
            "body": data.get("body", ""),
            "source": data.get("source", "manual"),
        }
        file_path.write_text(json.dumps(skill, ensure_ascii=False, indent=2), encoding="utf-8")
        h._json_response(200, {"ok": True, "skill": skill, "file": str(file_path)})
    except Exception as e:
        h._json_response(500, {"error": f"更新技能失败: {e}"})

def register(router) -> None:
    router.add("GET", "/api/skills", _handle_skills_list)
    router.add("POST", "/api/skills/create", _handle_skills_create)
    router.add("POST", "/api/skills/delete", _handle_skills_delete)
    router.add("POST", "/api/skills/update", _handle_skills_update)
    router.add("POST", "/api/skills/learn", _handle_skill_learn)
