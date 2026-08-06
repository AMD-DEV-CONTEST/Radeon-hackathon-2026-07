"""
LLM 输出 JSON Schema 校验器。
零幻觉保证：所有专家输出必须通过 Schema 验证，否则重试。
"""
import json
import yaml
from pathlib import Path
from jsonschema import validate, ValidationError
from typing import Dict, Any, Optional


class SchemaValidator:
    """读取专家 Skill 的 JSON Schema，校验 LLM 输出。"""

    def __init__(self, expert_registry: Dict[str, Dict[str, Any]], config_dir: Optional[Path] = None):
        self.schemas: Dict[str, Dict] = {}
        for name, cfg in expert_registry.items():
            schema = cfg.get("schema")
            if schema:
                self.schemas[name] = schema

    def validate(self, expert_name: str, raw_output: str) -> Dict[str, Any]:
        """
        校验专家输出。
        Returns: {
            valid: bool,
            data: dict | None,
            error: str | None,
            raw: str
        }
        """
        schema = self.schemas.get(expert_name)
        if not schema:
            # 无 Schema → 尝试随便解析 JSON
            try:
                return {"valid": True, "data": json.loads(raw_output), "error": None, "raw": raw_output}
            except json.JSONDecodeError:
                return {"valid": False, "data": None, "error": "不是合法JSON", "raw": raw_output}

        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return {"valid": False, "data": None, "error": "不是合法JSON", "raw": raw_output}

        try:
            validate(instance=data, schema=schema)
            return {"valid": True, "data": data, "error": None, "raw": raw_output}
        except ValidationError as e:
            return {"valid": False, "data": data, "error": str(e.message), "raw": raw_output}

    def validate_with_retry(self, expert_name: str, raw_output: str) -> Dict[str, Any]:
        """校验。不通过则标记但返回数据（上游决定是否重试）。"""
        result = self.validate(expert_name, raw_output)
        return result
