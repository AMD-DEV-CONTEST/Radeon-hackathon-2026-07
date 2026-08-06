"""
Skill/Expert 自动注册器 — 扫描配置目录，动态注册所有 Skill 和 Expert。
零硬编码，全部通过 YAML 配置发现。
输出为标准 JSON。
"""
import yaml
import json
from pathlib import Path
from typing import Dict, Any


class SkillAutoLoader:
    """自动扫描并注册所有 Skill 和 Expert。"""

    def __init__(self, environment: Dict[str, Any]):
        self.env = environment
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.experts: Dict[str, Dict[str, Any]] = {}

    def load_all(self) -> Dict[str, Any]:
        """加载全部 Skill + Expert，返回注册表。"""
        for s in self.env.get("skills", []):
            self._register_skill(s.get("path", ""))
        for e in self.env.get("experts", []):
            self._register_expert(e.get("path", ""))
        return {"skills": self.skills, "experts": self.experts}

    def _register_skill(self, yaml_path: str):
        if not yaml_path:
            return
        try:
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
            name = cfg.get("name")
            if not name:
                return
            self.skills[name] = {
                "schema": cfg.get("schema", {}),
                "executor": cfg.get("executor"),
                "timeout": cfg.get("timeout", 60),
                "category": cfg.get("category", "general"),
                "config_path": yaml_path,
            }
        except Exception:
            pass  # 损坏配置不崩溃

    def _register_expert(self, yaml_path: str):
        if not yaml_path:
            return
        try:
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
            name = cfg.get("name")
            if not name:
                return
            self.experts[name] = {
                "schema": cfg.get("schema", {}),
                "system_prompt": cfg.get("system_prompt", "").strip(),
                "has_veto": cfg.get("has_veto", False),
                "has_override": cfg.get("has_override", False),
                "config_path": yaml_path,
            }
        except Exception:
            pass

    def get_registry_report(self) -> str:
        """标准 JSON 注册表报告。"""
        return json.dumps({
            "skills": list(self.skills.keys()),
            "experts": list(self.experts.keys()),
            "skill_count": len(self.skills),
            "expert_count": len(self.experts),
        }, ensure_ascii=False, indent=2)

    def get_expert_names(self) -> list:
        """返回已注册专家名称列表。"""
        return list(self.experts.keys())
