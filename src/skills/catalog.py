"""Concrete development skills that scaffold real projects on disk."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.skills.base import Skill, SkillResult, write_tree


def _slug(name: str) -> str:
    s = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip())
    return s.strip("-_") or "project"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class ScaffoldPrivateAgentMini(Skill):
    id = "scaffold_private_agent_mini"
    title = "脚手架：迷你私有 Agent 项目"
    description = "生成可运行的迷你 RAG Agent 工程（main.py / config / README / sample docs）"
    category = "developer"

    def run(self, root: Path, params: dict[str, Any] | None = None) -> SkillResult:
        params = params or {}
        name = _slug(str(params.get("name") or f"mini_agent_{_stamp()}"))
        base = root / name
        tree = {
            "README.md": f"""# {name}

迷你私有 Agent（由 PrivateLocalAgent 技能生成）

## Run

```bash
pip install pyyaml
python main.py
```

生成时间: {datetime.now().isoformat(timespec='seconds')}
""",
            "config.yaml": """app:
  name: MiniPrivateAgent
llm:
  backend: mock
rag:
  docs_dir: docs
""",
            "docs/faq.md": """# FAQ
## Q: 如何重置 VPN？
A: 打开内部门户完成 MFA 后重置。

## Q: 涉密文档能用公网 AI 吗？
A: 不可以，仅允许本地 Private Agent。
""",
            "main.py": '''#!/usr/bin/env python3
"""Mini private agent demo — keyword RAG over local docs."""
from pathlib import Path

DOCS = Path(__file__).parent / "docs"

def search(query: str) -> str:
    hits = []
    for p in DOCS.rglob("*.md"):
        text = p.read_text(encoding="utf-8")
        if any(tok in text for tok in query.replace("？","").split() if len(tok) > 1):
            hits.append(f"[{p.name}]\\n{text[:400]}")
    return "\\n\\n".join(hits) or "未命中本地文档。"

def main() -> None:
    q = "VPN"
    print("Q:", q)
    print("Evidence:\\n", search(q))
    print("A: 请根据证据在内部门户重置 VPN（需 MFA）。")

if __name__ == "__main__":
    main()
''',
            "requirements.txt": "pyyaml>=6.0\n",
        }
        files = write_tree(base, tree)
        return SkillResult(
            skill_id=self.id,
            title=self.title,
            project_dir=str(base),
            files_written=files,
            message="可用 `python main.py` 在项目目录试跑。",
        )


class ScaffoldFastAPIService(Skill):
    id = "scaffold_fastapi_service"
    title = "脚手架：FastAPI 办公 API"
    description = "生成 FastAPI 健康检查 + 知识问答占位接口项目"
    category = "developer"

    def run(self, root: Path, params: dict[str, Any] | None = None) -> SkillResult:
        params = params or {}
        name = _slug(str(params.get("name") or f"office_api_{_stamp()}"))
        base = root / name
        tree = {
            "README.md": f"""# {name}

FastAPI office API scaffold (skill-generated)

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```
""",
            "requirements.txt": "fastapi>=0.110\nuvicorn>=0.27\n",
            "app.py": '''from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Office Copilot API", version="0.1.0")

class AskReq(BaseModel):
    question: str

@app.get("/health")
def health():
    return {"status": "ok", "gpu": "configure local_transformers separately"}

@app.post("/ask")
def ask(req: AskReq):
    # Placeholder: wire to PrivateLocalAgent in production
    return {
        "question": req.question,
        "answer": "Connect this endpoint to PrivateLocalAgent RAG + tools.",
        "tools": ["kb_search"],
    }
''',
            "tests/test_health.py": '''def test_placeholder():
    assert True
''',
        }
        files = write_tree(base, tree)
        return SkillResult(
            skill_id=self.id,
            title=self.title,
            project_dir=str(base),
            files_written=files,
            message="启动: `uvicorn app:app --port 8080`",
        )


class ScaffoldDataPipeline(Skill):
    id = "scaffold_ingest_pipeline"
    title = "脚手架：文档入库流水线"
    description = "生成 ingest 脚本 + 样例文档 + Makefile，用于本地知识库构建"
    category = "workflow"

    def run(self, root: Path, params: dict[str, Any] | None = None) -> SkillResult:
        params = params or {}
        name = _slug(str(params.get("name") or f"ingest_pipeline_{_stamp()}"))
        base = root / name
        tree = {
            "README.md": f"# {name}\n\nLocal doc ingest pipeline scaffold.\n\n```bash\npython ingest.py\n```\n",
            "sample_docs/policy.md": "# Policy\nLeave requests need 3 working days notice.\n",
            "ingest.py": '''#!/usr/bin/env python3
from pathlib import Path
import json

ROOT = Path(__file__).parent
OUT = ROOT / "build" / "chunks.jsonl"

def chunk(text: str, size: int = 200):
    return [text[i:i+size] for i in range(0, len(text), size)] or [text]

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with OUT.open("w", encoding="utf-8") as f:
        for p in (ROOT / "sample_docs").rglob("*.md"):
            for i, c in enumerate(chunk(p.read_text(encoding="utf-8"))):
                f.write(json.dumps({"source": p.name, "i": i, "text": c}, ensure_ascii=False) + "\\n")
                n += 1
    print(f"wrote {n} chunks -> {OUT}")

if __name__ == "__main__":
    main()
''',
            "Makefile": "ingest:\n\tpython ingest.py\n",
        }
        files = write_tree(base, tree)
        return SkillResult(
            skill_id=self.id,
            title=self.title,
            project_dir=str(base),
            files_written=files,
            message="运行 `python ingest.py` 会生成 build/chunks.jsonl",
        )


class ScaffoldReactDashboard(Skill):
    id = "scaffold_static_dashboard"
    title = "脚手架：静态办公看板页面"
    description = "生成单页 HTML/CSS/JS 看板（无需构建工具），可直接浏览器打开"
    category = "developer"

    def run(self, root: Path, params: dict[str, Any] | None = None) -> SkillResult:
        params = params or {}
        name = _slug(str(params.get("name") or f"office_dashboard_{_stamp()}"))
        base = root / name
        tree = {
            "README.md": f"# {name}\n\nOpen `index.html` in a browser.\n",
            "index.html": """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>PrivateLocalAgent Dashboard</title>
  <link rel="stylesheet" href="styles.css"/>
</head>
<body>
  <header>
    <h1>PrivateLocalAgent</h1>
    <p>本地知识助理 · 工作流 · ROCm</p>
  </header>
  <main>
    <section class="card">
      <h2>快捷技能</h2>
      <ul id="skills"></ul>
    </section>
    <section class="card">
      <h2>状态</h2>
      <p id="status">就绪（静态演示页）</p>
    </section>
  </main>
  <script src="app.js"></script>
</body>
</html>
""",
            "styles.css": """:root { --bg:#0f172a; --card:#1f2937; --accent:#14b8a6; --text:#e5e7eb; }
*{box-sizing:border-box} body{margin:0;font-family:Segoe UI,PingFang SC,sans-serif;background:var(--bg);color:var(--text)}
header{padding:28px 20px} h1{margin:0 0 6px;font-size:28px}
main{display:grid;gap:16px;padding:0 20px 32px;max-width:900px}
.card{background:var(--card);border:1px solid #334155;border-radius:14px;padding:16px}
li{margin:8px 0}
""",
            "app.js": """const skills=["RAG 问答","入职IT工作流","开发脚手架","ROCm 检测"];
const ul=document.getElementById("skills");
skills.forEach(s=>{const li=document.createElement("li");li.textContent=s;ul.appendChild(li);});
""",
        }
        files = write_tree(base, tree)
        return SkillResult(
            skill_id=self.id,
            title=self.title,
            project_dir=str(base),
            files_written=files,
            message="用浏览器打开 index.html 即可查看。",
        )


class WriteProjectBrief(Skill):
    id = "write_project_brief"
    title = "生成：项目简报 Markdown"
    description = "在输出目录写入一份可提交的项目简报/演示提纲"
    category = "enterprise"

    def run(self, root: Path, params: dict[str, Any] | None = None) -> SkillResult:
        params = params or {}
        name = _slug(str(params.get("name") or f"brief_{_stamp()}"))
        base = root / name
        topic = str(params.get("topic") or "PrivateLocalAgent Track2")
        tree = {
            "PROJECT_BRIEF.md": f"""# {topic} · 项目简报

## 一句话
隐私优先的本地办公 Agent：RAG + 工具调用 + 工作流 + 多 Agent，运行于 AMD Radeon GPU / ROCm。

## 核心能力
- 本地知识库问答
- Tool calling / 记忆
- 办公工作流自动化
- 开发技能脚手架（真实生成项目文件）

## 演示步骤
1. verify_rocm.py
2. notebooks/private_agent_demo.ipynb
3. 选择开发技能生成项目并展示目录

生成时间: {datetime.now().isoformat(timespec='seconds')}
""",
            "DEMO_CHECKLIST.md": """# Demo Checklist
- [ ] GPU visible
- [ ] RAG question grounded
- [ ] Workflow executed
- [ ] Skill created real files
""",
        }
        files = write_tree(base, tree)
        return SkillResult(
            skill_id=self.id,
            title=self.title,
            project_dir=str(base),
            files_written=files,
            message="简报已写入，可用于答辩/PR 附件。",
        )


ALL_SKILLS: list[Skill] = [
    ScaffoldPrivateAgentMini(),
    ScaffoldFastAPIService(),
    ScaffoldDataPipeline(),
    ScaffoldReactDashboard(),
    WriteProjectBrief(),
]
