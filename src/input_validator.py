"""
Input Validator — 输入数据契约校验。
检查输入目录的必需文件是否存在，防止缺文件即跑工作流。
"""

from pathlib import Path


def load_contracts(contract_path: str = "config/data_contracts.yaml") -> dict:
    """加载数据契约配置。"""
    import yaml
    contract_file = Path(contract_path)
    if not contract_file.exists():
        return {"required_files": []}
    with open(contract_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"required_files": []}


class InputValidator:
    """输入文件完整性校验。"""

    def __init__(self, contract_path: str = "config/data_contracts.yaml"):
        contracts = load_contracts(contract_path)
        self.required_files = contracts.get("required_files", [])

    def validate(self, input_dir: str) -> dict:
        """验证输入目录文件完整性。
        
        Returns:
            dict with: passed, missing_required, missing_optional,
                       matched_files, unexpected_files, summary
        """
        input_path = Path(input_dir)
        if not input_path.exists():
            return {
                "passed": False,
                "missing_required": [c["id"] for c in self.required_files if c.get("required")],
                "missing_optional": [],
                "matched_files": [],
                "unexpected_files": [],
                "summary": f"输入目录不存在: {input_dir}",
            }

        if not self.required_files:
            return {
                "passed": True,
                "missing_required": [],
                "missing_optional": [],
                "matched_files": [],
                "unexpected_files": [],
                "summary": "未启用数据契约（contract_path 不存在或无契约项）",
            }

        existing_files = {f.name for f in input_path.iterdir() if f.is_file()}

        required_missing = []
        optional_missing = []
        matched = []
        unexpected = list(existing_files)

        for contract in self.required_files:
            pattern = contract.get("pattern", "")
            is_required = contract.get("required", False)
            cid = contract.get("id", pattern)

            found = False
            for ef in existing_files:
                if pattern in ef:
                    found = True
                    matched.append({"id": cid, "file": ef, "pattern": pattern, "required": is_required})
                    if ef in unexpected:
                        unexpected.remove(ef)
                    break

            if not found:
                if is_required:
                    required_missing.append(cid)
                else:
                    optional_missing.append(cid)

        passed = len(required_missing) == 0
        parts = []
        if passed:
            parts.append(f"必需文件齐全（{len(matched)} 个）")
        else:
            parts.append(f"缺失 {len(required_missing)} 个必需文件")
        if optional_missing:
            parts.append(f"可选文件缺失 {len(optional_missing)} 个")
        if unexpected:
            parts.append(f"未识别的文件 {len(unexpected)} 个")

        return {
            "passed": passed,
            "missing_required": required_missing,
            "missing_optional": optional_missing,
            "matched_files": matched,
            "unexpected_files": sorted(unexpected),
            "summary": "；".join(parts),
        }
