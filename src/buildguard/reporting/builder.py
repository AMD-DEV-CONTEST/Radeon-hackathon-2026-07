"""End-to-end report drafting, citation validation, and confirmed export."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from buildguard.config import ReportingConfig
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.rag.schemas import DocumentChunk
from buildguard.reporting.citation_validator import (
    CitationStatement,
    CitationValidation,
    CitationValidator,
)
from buildguard.reporting.html_exporter import HtmlExporter
from buildguard.reporting.optional_pdf_exporter import (
    OptionalPdfExporter,
    PdfExportResult,
)
from buildguard.reporting.templates import render_markdown
from buildguard.schemas.common import BoundingBox, StrictSchema
from buildguard.schemas.vision import RiskAssessment
from buildguard.utils.time import utc_now


class ReportEvidence(StrictSchema):
    source_path: Path
    visualization_path: Path | None = None
    label: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    bounding_box: BoundingBox
    source_model: str = Field(min_length=1, max_length=256)
    mask_path: Path | None = None
    clip_path: Path | None = None


class ReportInput(StrictSchema):
    task_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=500)
    report_type: str = Field(default="inspection", min_length=1, max_length=128)
    sources: list[str] = Field(default_factory=list, max_length=1000)
    findings: list[str] = Field(default_factory=list, max_length=5000)
    risks: list[RiskAssessment] = Field(default_factory=list, max_length=1000)
    retrieved_chunks: list[DocumentChunk] = Field(default_factory=list, max_length=1000)
    citation_statements: list[CitationStatement] = Field(default_factory=list, max_length=1000)
    recommendations: list[str] = Field(default_factory=list, max_length=1000)
    visual_evidence: list[ReportEvidence] = Field(default_factory=list, max_length=5000)
    human_review: str = Field(
        default="待现场授权人员复核并签字。",
        min_length=1,
        max_length=4000,
    )
    tool_chain: list[str] = Field(default_factory=list, max_length=1000)
    performance: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class ReportDraft(StrictSchema):
    request: ReportInput
    summary: str
    markdown: str
    citations: list[CitationValidation] = Field(default_factory=list)
    generated_at: datetime

    @property
    def verified_citation_count(self) -> int:
        return sum(item.valid for item in self.citations)


class ReportArtifact(StrictSchema):
    markdown_path: Path
    html_path: Path
    pdf: PdfExportResult
    verified_citation_count: int = Field(ge=0)


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    return stem[:120] or "report"


class ReportBuilder:
    """Build drafts freely, but require an explicit confirmation before writes."""

    def __init__(
        self,
        config: ReportingConfig,
        backend: LocalLLMBackend,
        *,
        validator: CitationValidator | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.validator = validator or CitationValidator()
        self.output_dir = config.output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _summary(self, request: ReportInput) -> str:
        severity_map = {"critical": "严重", "high": "高", "normal": "中等", "low": "低"}
        risk_lines = "\n".join(
            f"- 风险类型：{r.severity.value}（{severity_map.get(r.severity.value, r.severity.value)}）"
            f"，评分 {r.score:.2f}"
            for r in request.risks
        )
        findings_text = "\n".join(f"- {f}" for f in request.findings) or "- 无"
        user_content = (
            f"检测来源：{'、'.join(request.sources) or '未知'}\n"
            f"发现的问题：\n{findings_text}\n"
            f"风险评估：\n{risk_lines or '- 暂无'}"
        )
        response = self.backend.chat(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "你是一名专业的建筑施工安全检查员，正在为现场负责人撰写巡检摘要。\n"
                        "根据下方结构化检测结果，用简洁、专业的中文写一段 3-5 句话的操作性摘要。\n"
                        "要求：\n"
                        "1. 明确说明发现了什么问题、问题的严重程度；\n"
                        "2. 给出 1-2 条具体的现场处置建议；\n"
                        "3. 不得捏造规范条款、标准编号或检测数据；\n"
                        "4. 不得输出任何 Markdown 标题或列表符号，只输出纯段落文字。"
                    ),
                ),
                ChatMessage(role="user", content=user_content),
            ],
            thinking=False,
        )
        content = response.content.strip()
        return content[: self.config.max_summary_chars] or "未生成摘要。"

    def build(self, request: ReportInput) -> ReportDraft:
        generated_at = utc_now()
        validation = self.validator.validate(
            request.citation_statements,
            request.retrieved_chunks,
        )
        verified = [item for item in validation if item.valid]
        summary = self._summary(request)
        markdown_text = render_markdown(
            {
                **request.model_dump(mode="python"),
                "summary": summary,
                "citations": verified,
                "generated_at": generated_at.isoformat(),
            }
        )
        return ReportDraft(
            request=request,
            summary=summary,
            markdown=markdown_text,
            citations=validation,
            generated_at=generated_at,
        )

    def export(
        self,
        draft: ReportDraft,
        *,
        confirmed: bool,
        filename: str | None = None,
    ) -> ReportArtifact:
        if not confirmed:
            raise PermissionError("Report export requires explicit user confirmation")
        stem = _safe_stem(filename or f"{draft.request.task_id}-{draft.request.report_type}")
        markdown_path = (self.output_dir / f"{stem}.md").resolve()
        html_path = (self.output_dir / f"{stem}.html").resolve()
        for target in (markdown_path, html_path):
            try:
                target.relative_to(self.output_dir)
            except ValueError as exc:
                raise PermissionError(
                    "Report path escaped the configured output directory"
                ) from exc
        temporary = markdown_path.with_name(f".{markdown_path.name}.tmp")
        temporary.write_text(draft.markdown, encoding="utf-8")
        temporary.replace(markdown_path)
        HtmlExporter().export(draft.markdown, html_path)
        pdf = PdfExportResult(
            available=False,
            reason="PDF export is disabled by configuration.",
        )
        if self.config.enable_pdf:
            pdf = OptionalPdfExporter().export(html_path, self.output_dir / f"{stem}.pdf")
        return ReportArtifact(
            markdown_path=markdown_path,
            html_path=html_path,
            pdf=pdf,
            verified_citation_count=draft.verified_citation_count,
        )
