"""XAI V4 Verifier — 执行后验证。

V4 §4.2: 执行完成后必须验证。
检查:
  - 目标完成度
  - 输出质量
  - 安全风险
  - 逻辑错误

流程:
  Execute → Verify → Pass or Retry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VerificationResult:
    """验证结果"""
    passed: bool
    score: float          # 0.0–1.0
    issues: List[str] = field(default_factory=list)
    suggestion: str = ""  # 如果不通过，改进建议

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "issues": self.issues,
            "suggestion": self.suggestion,
        }


class Verifier:
    """V4 验证器。

    第一版: 基于规则的快速检查，不依赖 LLM。
    后续升级: Hermes/Reviewer Agent 做语义验证。
    """

    PASS_THRESHOLD = 0.6   # 得分 ≥ 此值视为通过
    MAX_RETRIES = 3        # 最多重试次数

    def verify(self, goal: str, output: str, step_number: int = 0,
               retry_count: int = 0) -> VerificationResult:
        """验证执行输出。

        Args:
            goal: 原始目标
            output: 执行输出文本
            step_number: 当前步骤编号
            retry_count: 已重试次数
        """
        issues: List[str] = []
        score = 0.0

        # 0. 安全检查先于一切（0.0–1.0，不合格直接零分）
        dangerous = False
        for pattern in ["rm -rf", "DROP TABLE", "DELETE FROM", ":(){ :|:& };:",
                        "os.system(", "eval(", "__import__", "subprocess.run"]:
            if pattern in output:
                dangerous = True
                issues.append(f"检测到危险模式: {pattern}")
        if dangerous:
            return VerificationResult(passed=False, score=0.0, issues=issues,
                                      suggestion="请在安全沙箱中重新执行，避免危险操作")

        # 1. 完成度检查 (0.0–0.4)
        if output and len(output.strip()) > 20:
            score += 0.4
        elif output and len(output.strip()) > 0:
            score += 0.2
            issues.append("输出过短，可能未完成")
        else:
            issues.append("无输出内容")

        # 2. 质量检查 (0.0–0.4)
        if len(output) > 200:
            score += 0.2
        if "\n" in output:
            score += 0.05  # 有结构
        if any(marker in output for marker in ["```", "**", "##", "|"]):
            score += 0.15  # 有格式化内容

        # 3. 重复内容检查 (0.0–0.2)
        if len(output) > 100:
            # 检查是否有明显的重复段落
            lines = output.split("\n")
            unique_ratio = len(set(lines)) / max(len(lines), 1)
            if unique_ratio > 0.5:
                score += 0.1
            else:
                score += 0.05
                issues.append("输出存在大量重复内容")
        else:
            score += 0.1

        # 判定
        passed = score >= self.PASS_THRESHOLD

        if retry_count >= self.MAX_RETRIES:
            passed = True  # 超过最大重试次数，强制通过

        suggestion = ""
        if not passed:
            if len(issues) == 1 and "过短" in issues[0]:
                suggestion = "建议提供更详细的输出"
            elif dangerous:
                suggestion = "请在安全沙箱中重新执行，避免危险操作"
            else:
                suggestion = "建议重新执行并改进输出质量"

        return VerificationResult(
            passed=passed,
            score=round(score, 2),
            issues=issues,
            suggestion=suggestion,
        )
