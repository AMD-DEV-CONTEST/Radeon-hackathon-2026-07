"""
本地工艺规则冲突检测器 — 完全离线。
硬规则库 + LLM 软规则兜底。
所有输入输出为标准 JSON。
"""
import json
import time
from typing import Dict, List, Optional, Any
from src.neuro_core.reasoning_chain import ReasoningChain, register_chain


class ConflictChecker:
    """
    离线工艺规则冲突检测。
    硬规则 → 快速精确匹配；软规则 → LLM 语义分析。
    """

    # ── 硬规则库（从46,103条RAG知识提炼） ──
    HARD_RULES: List[Dict] = [
        # 材料-表面处理禁忌
        {
            "id": "R001",
            "condition": {"material": "304", "surface_treatment": "阳极氧化"},
            "severity": "critical",
            "conflict": "304不锈钢无法阳极氧化。阳极氧化仅适用于铝合金。如需表面处理，建议钝化或电解抛光。"
        },
        {
            "id": "R002",
            "condition": {"material": "316L", "surface_treatment": "阳极氧化"},
            "severity": "critical",
            "conflict": "316L不锈钢不可阳极氧化。建议钝化处理或涂层。"
        },
        {
            "id": "R003",
            "condition": {"material": "不锈钢", "surface_treatment": "阳极氧化"},
            "severity": "critical",
            "conflict": "不锈钢无法阳极氧化。阳极氧化仅适用于铝、钛等有色金属。建议改用钝化或镀层。"
        },
        {
            "id": "R004",
            "condition": {"material": "钛合金", "surface_treatment": "镀锌"},
            "severity": "critical",
            "conflict": "钛合金不宜镀锌，氢脆风险高。建议阳极氧化或微弧氧化。"
        },
        {
            "id": "R005",
            "condition": {"material": "铜", "surface_treatment": "阳极氧化"},
            "severity": "critical",
            "conflict": "铜不可阳极氧化。建议电镀镍/铬或化学镀。"
        },
        # 通用电镀与材料冲突
        {
            "id": "R006",
            "condition": {"material": "6061", "surface_treatment": "电镀"},
            "severity": "warning",
            "conflict": "铝合金电镀需特殊前处理(锌酸盐处理)，成本较高。建议阳极氧化替代。"
        },
        # 不锈钢电镀
        {
            "id": "R007",
            "condition": {"material": "不锈钢", "surface_treatment": "电镀"},
            "severity": "info",
            "conflict": "不锈钢电镀可行，常见镀镍/镀铬。但需注意氢脆风险。"
        },
        # 公差-工艺不匹配
        {
            "id": "R010",
            "condition": {"tolerance": "IT4", "process": "车削"},
            "severity": "warning",
            "conflict": "IT4公差超出普通车削能力范围。需要精密磨削或超精密加工。"
        },
        {
            "id": "R011",
            "condition": {"tolerance": "IT5", "process": "普通铣削"},
            "severity": "warning",
            "conflict": "IT5公差需精密磨削，普通铣削难以保证。确认设备能力后再接单。"
        },
        # 材料-热处理
        {
            "id": "R020",
            "condition": {"material": "6061", "heat_treatment": "淬火"},
            "severity": "critical",
            "conflict": "6061铝合金不可淬火硬化。正确工艺：固溶处理(T4/T6)或时效硬化。"
        },
        {
            "id": "R021",
            "condition": {"material": "6061", "heat_treatment": "T6"},
            "severity": "info",
            "conflict": None,  # 正确匹配，不报冲突
            "note": "6061-T6为标准热处理状态，可用。"
        },
        # 薄壁件加工
        {
            "id": "R030",
            "condition": {"wall_thickness": "<0.5mm", "material": "铝合金"},
            "severity": "warning",
            "conflict": "壁厚<0.5mm的铝合金件极易变形。需要特殊装夹方案和多次精加工。"
        },
        {
            "id": "R031",
            "condition": {"wall_thickness": "<1mm", "material": "不锈钢"},
            "severity": "warning",
            "conflict": "不锈钢薄壁件(<1mm)加工难度极高，刀具磨损快且容易振刀。"
        },
    ]

    # 材料别名映射
    MATERIAL_ALIASES = {
        "304": ["304", "304ss", "304不锈钢", "sus304", "0cr18ni9"],
        "316L": ["316L", "316l", "316", "sus316l", "022cr17ni12mo2"],
        "6061": ["6061", "6061铝", "6061铝合金", "al6061"],
        "7075": ["7075", "7075铝", "7075铝合金"],
        "钛合金": ["钛合金", "钛", "titanium", "tc4", "ti6al4v", "tc11"],
        "不锈钢": ["不锈钢", "ss", "stainless", "sus"],
        "铜": ["铜", "黄铜", "紫铜", "copper", "brass", "bronze", "h62", "h59"],
        "45钢": ["45钢", "45#", "45号钢", "c45", "1045"],
    }

    def __init__(self, ai_engine=None):
        self.ai = ai_engine  # 可选：LLM 引擎用于软规则检查

    def check(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        检测工艺冲突。
        
        Args:
            params: 包含 material, surface_treatment, tolerance, process 等字段
        
        Returns:
            {"valid": bool, "conflicts": [...], "warnings": [...], "info": [...]}
        """
        conflicts = []
        warnings = []
        infos = []

        material = str(params.get("material", "")).lower()
        surface = str(params.get("surface_treatment", "")).lower()
        tolerance = str(params.get("tolerance", "")).upper()
        process = str(params.get("process", "")).lower()
        heat_treat = str(params.get("heat_treatment", "")).lower()
        wall = str(params.get("wall_thickness", ""))

        for rule in self.HARD_RULES:
            if not self._match(rule["condition"], material, surface, tolerance, process, heat_treat, wall):
                continue

            if rule.get("conflict") is None:
                infos.append({"id": rule["id"], "message": rule.get("note", ""), "severity": "info"})
                continue

            entry = {"id": rule["id"], "message": rule["conflict"], "severity": rule["severity"]}
            if rule["severity"] == "critical":
                conflicts.append(entry)
            else:
                warnings.append(entry)

        # 软规则：LLM 语义检查
        if not conflicts and not warnings and self.ai:
            soft = self._soft_check(params)
            if soft:
                warnings.extend(soft)

        return {
            "valid": len(conflicts) == 0,
            "conflicts": conflicts,
            "warnings": warnings,
            "info": infos,
            "total_issues": len(conflicts) + len(warnings),
        }

    def check_with_reasoning(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect process conflicts WITH full reasoning chain (XAI).
        Returns standard check result + reasoning_chain.
        """
        chain = ReasoningChain("conflict_check", "Process Conflict Detection")

        # Step 1: Record inputs
        for k, v in params.items():
            chain.add_input(k, v)

        material = str(params.get("material", "")).lower()
        surface = str(params.get("surface_treatment", "")).lower()
        tolerance = str(params.get("tolerance", "")).upper()
        process = str(params.get("process", "")).lower()

        # Step 2: Record feature extraction
        chain.add_feature("material_normalized", material, f"Material resolved to '{material}'")
        if surface:
            chain.add_feature("surface_normalized", surface, f"Surface treatment: '{surface}'")

        # Step 3: Check each rule with reasoning
        conflicts = []
        warnings = []
        infos = []
        matched_count = 0

        for rule in self.HARD_RULES:
            heat_treat = str(params.get("heat_treatment", "")).lower()
            wall = str(params.get("wall_thickness", ""))
            matched = self._match(rule["condition"], material, surface, tolerance, process, heat_treat, wall)

            if not matched:
                chain.add_rule_match(rule["id"], (rule.get("conflict") or rule.get("note", ""))[:80],
                                     matched=False, severity=rule["severity"],
                                     all_rules_checked=len(self.HARD_RULES))
                continue

            matched_count += 1
            conflict_msg = rule.get("conflict") or rule.get("note", "")
            severity = rule["severity"]

            chain.add_rule_match(rule["id"], conflict_msg[:80],
                                 matched=True, severity=severity,
                                 conflict_msg=conflict_msg,
                                 all_rules_checked=len(self.HARD_RULES))

            if rule.get("conflict") is None:
                infos.append({"id": rule["id"], "message": rule.get("note", ""), "severity": "info"})
            else:
                entry = {"id": rule["id"], "message": conflict_msg, "severity": severity}
                if severity == "critical":
                    conflicts.append(entry)
                    chain.add_warning(f"CRITICAL conflict: {conflict_msg}", "critical")
                else:
                    warnings.append(entry)

        # Step 4: Exclusion reasoning
        if not conflicts:
            common_issues = ["brittle_fracture", "hydrogen_embrittlement", "galvanic_corrosion"]
            for issue in common_issues:
                chain.add_exclusion(issue, f"No {issue} indicators found in material/surface combination")

        # Step 5: Soft rules (LLM)
        if not conflicts and not warnings and self.ai:
            chain.add_tool_call("llm_soft_check", params, "checking...", success=True)
            soft = self._soft_check(params)
            if soft:
                warnings.extend(soft)
                for s in soft:
                    chain.add_warning(f"LLM soft rule: {s.get('message', '')}", "warning")

        # Step 6: Conclusion
        valid = len(conflicts) == 0
        total = len(conflicts) + len(warnings)
        if valid and total == 0:
            conclusion = "No process conflicts detected"
            confidence = 0.95
        elif valid:
            conclusion = f"No critical conflicts, {len(warnings)} warning(s)"
            confidence = 0.8
        else:
            conclusion = f"{len(conflicts)} CRITICAL conflict(s) found - production blocked"
            confidence = 0.99

        chain.add_conclusion(conclusion, confidence, 
                           rationale=f"Checked {len(self.HARD_RULES)} hard rules, {matched_count} matched",
                           recommendations=["Proceed with production" if valid else "Fix conflicts before production"])

        result = {
            "valid": valid,
            "conflicts": conflicts,
            "warnings": warnings,
            "info": infos,
            "total_issues": total,
            "reasoning_chain": chain.finish().to_dict(),
            "reasoning_chain_id": register_chain(chain),
        }
        return result

    def _match(self, condition: Dict, material: str, surface: str,
               tolerance: str, process: str, heat_treat: str, wall: str) -> bool:
        """检查条件是否匹配。使用别名展开匹配。"""
        for key, expected in condition.items():
            actual = ""
            if key == "material":
                actual = material
                # 展开别名
                matched = False
                for canonical, aliases in self.MATERIAL_ALIASES.items():
                    if expected.lower() in [a.lower() for a in aliases]:
                        if any(a.lower() in actual for a in aliases):
                            matched = True
                            break
                if not matched:
                    return False
            elif key == "surface_treatment":
                actual = surface
                if expected.lower() not in actual:
                    return False
            elif key == "tolerance":
                actual = tolerance
                if expected.upper() not in actual.upper():
                    return False
            elif key == "process":
                actual = process
                if expected.lower() not in actual:
                    return False
            elif key == "heat_treatment":
                actual = heat_treat
                if expected.lower() not in actual:
                    return False
            elif key == "wall_thickness":
                # 特殊处理：支持 < 比较
                if expected.startswith("<"):
                    try:
                        threshold = float(expected[1:].replace("mm", "").strip())
                        # 尝试从参数中提取壁厚数值
                        actual_val = self._extract_number(wall or str(material))
                        if actual_val is None or actual_val >= threshold:
                            return False
                    except ValueError:
                        return False
            else:
                # 未知条件类型，跳过
                return False
        return True

    @staticmethod
    def _extract_number(s: str) -> Optional[float]:
        """从字符串提取第一个数字。"""
        import re
        match = re.search(r'(\d+\.?\d*)', s)
        return float(match.group(1)) if match else None

    def _soft_check(self, params: Dict) -> List[Dict]:
        """LLM 软规则语义检查。"""
        if not self.ai:
            return []
        prompt = f"""检查以下CNC加工参数是否存在工艺冲突（材料、表面处理、公差、热处理的禁忌组合）:

{json.dumps(params, ensure_ascii=False)}

只输出存在冲突的条目。如果没有冲突，输出空数组 []。
格式: [{{"message": "冲突描述", "severity": "warning"}}]"""

        result = self.ai.chat_json(prompt, system_prompt="你是CNC工艺专家。只报告真实存在的工艺冲突。")
        if result and "_error" not in result and isinstance(result, list):
            return result
        return []

    def get_report(self, params: Dict) -> str:
        """标准 JSON 检查报告。"""
        return json.dumps(self.check(params), ensure_ascii=False, indent=2)
