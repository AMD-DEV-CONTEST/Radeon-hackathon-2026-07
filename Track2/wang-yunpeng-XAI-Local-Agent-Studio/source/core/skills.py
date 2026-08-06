"""XAI 技能注册 `xai-grok-skills`（吸收 OpenClaw SKILL.md + Hermes 渐进式披露）。

- SKILL.md 风格：YAML frontmatter（name / user-invocable / disable-model-invocation）+ 正文。
- 优先级：workspace > managed > bundled（OpenClaw 规则）。
- 渐进式披露（Hermes Level0/1/2）：先给摘要做匹配，命中再展开，省 token。
- 遵循 agentskills.io 开放标准（name/trigger/body 三段）。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str
    user_invocable: bool = True
    model_invocation: bool = True   # disable-model-invocation 的反义
    level0: str = ""                 # 摘要（匹配用）
    level1: str = ""                 # 完整步骤
    level2: str = ""                 # 参考/边界/踩坑
    source: str = "bundled"          # workspace | managed | bundled
    raw: str = ""

    def disclosure(self, level: int = 0) -> str:
        if level <= 0:
            return self.level0 or self.level1
        if level == 1:
            return self.level1 or self.level0
        return self.level2 or self.level1 or self.level0


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text.strip())
    if not m:
        return {}, text.strip()
    fm_raw, body = m.group(1), m.group(2)
    fm: dict = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v.lower() in ("true", "false"):
                v = v.lower() == "true"
            fm[k] = v
    return fm, body


class SkillRegistry:
    """三层优先级 + 渐进披露。"""

    PRIORITY = ("workspace", "managed", "bundled")

    def __init__(self):
        self.layers: dict[str, dict[str, Skill]] = {k: {} for k in self.PRIORITY}

    # ---- 加载 ----
    def load_from_markdown(self, path: str, source: str = "workspace") -> Skill:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        fm, body = _parse_frontmatter(text)
        name = fm.get("name") or os.path.splitext(os.path.basename(path))[0]
        # 把正文按 Level 标记切分（可选 <!-- L1 --> / <!-- L2 -->）
        parts = re.split(r"<!--\s*L(\d)\s*-->", body)
        level0, level1, level2 = body, body, ""
        if len(parts) > 1:
            # parts: [pre, '1', seg1, '2', seg2, ...]
            level0 = parts[0].strip()
            for i in range(1, len(parts) - 1, 2):
                tag = parts[i]
                seg = parts[i + 1].strip()
                if tag == "1":
                    level1 = seg
                elif tag == "2":
                    level2 = seg
        sk = Skill(
            name=name,
            user_invocable=str(fm.get("user-invocable", "true")).lower() == "true",
            model_invocation=not (str(fm.get("disable-model-invocation", "false")).lower() == "true"),
            level0=level0, level1=level1 or level0, level2=level2,
            source=source, raw=text,
        )
        self.layers[source][name] = sk
        return sk

    def register_skill(self, skill: Skill, source: str = "managed") -> None:
        skill.source = source
        self.layers[source][skill.name] = skill

    # ---- 解析（优先级） ----
    def resolve(self, name: str) -> Skill | None:
        for layer in self.PRIORITY:
            if name in self.layers[layer]:
                return self.layers[layer][name]
        return None

    def all(self) -> list[Skill]:
        out: list[Skill] = []
        for layer in self.PRIORITY:
            out.extend(self.layers[layer].values())
        return out

    # ---- 渐进披露匹配 ----
    def match_level0(self, query: str, k: int = 5) -> list[Skill]:
        """用 level0 摘要做关键词召回（轻量，省 token）。

        混合分词（拉丁词 + 中文单字 + 二元组），避免中英文连写匹配失效。
        """
        words = re.findall(r"[a-zA-Z0-9_]+", query.lower())
        cjk_runs = re.findall(r"[\u4e00-\u9fff]+", query)
        q: set[str] = set(words)
        for run in cjk_runs:
            q.update(run)
            for i in range(len(run) - 1):
                q.add(run[i:i + 2])
        scored: list[tuple[int, Skill]] = []
        for sk in self.all():
            text = (sk.level0 or sk.name).lower()
            hits = sum(1 for t in q if t in text)
            if hits:
                scored.append((hits, sk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:k]]
