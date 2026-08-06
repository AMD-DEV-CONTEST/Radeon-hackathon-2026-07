"""Pydantic schemas and FastAPI routes."""
import asyncio
import base64
import json
import time
import uuid
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

from inference.pipeline import AnalysisPipeline, combine_masks, encode_image_as_base64, get_pipeline
from models.classifier import FINDINGS

router = APIRouter()


class Finding(BaseModel):
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    region: Optional[list[int]] = None  # bounding box [x, y, w, h]
    heatmap_b64: Optional[str] = None


class StructuredFinding(BaseModel):
    name: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class StructuredFindings(BaseModel):
    modality: str = "Chest X-ray"
    findings: list[StructuredFinding]


class LocalizationMap(BaseModel):
    finding: str
    heatmap: str  # base64 PNG
    segmentation_mask: Optional[str] = None  # base64 RGBA PNG


class GradCAMResponse(BaseModel):
    finding: str
    heatmap: str  # base64 PNG

class ChatTurn(BaseModel):
    role: str
    content: str
    image_b64: Optional[str] = None

class AnalysisResponse(BaseModel):
    image_id: str
    findings: list[Finding]
    confidence_scores: dict[str, float]
    localization_maps: list[LocalizationMap]
    report: str
    report_source: str = "template"
    findings_section: str = ""
    impression_section: str = ""
    mask_b64: Optional[str] = None
    evidence_type: str = "attention"
    elapsed_seconds: float
    chat_seed: list[ChatTurn] = Field(default_factory=list)


class GenerateReportResponse(BaseModel):
    report: str
    report_source: str = "template"
    findings_section: str = ""
    impression_section: str = ""
    tokens_generated: int
    latency_seconds: float
    chat_seed: list[ChatTurn] = Field(default_factory=list)


class ChatRequest(BaseModel):
    report: str
    findings: list[Finding]
    question: str
    max_tokens: Optional[int] = None
    history: list[ChatTurn] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    referenced_finding: Optional[str] = None


class ChatStatusResponse(BaseModel):
    state: str  # idle | downloading | loading | ready | error
    progress: float
    message: str
    model_path: Optional[str] = None
    model_name: Optional[str] = None

@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(
    file: UploadFile = File(...),
    evidence_type: str = "attention",
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    return await _run_analysis(file, pipeline, evidence_type=evidence_type)


@router.post("/analyze-xray", response_model=AnalysisResponse)
async def analyze_xray(
    file: UploadFile = File(...),
    evidence_type: str = "attention",
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    return await _run_analysis(file, pipeline, evidence_type=evidence_type)


@router.post("/analyze-stream")
async def analyze_stream(
    file: UploadFile = File(...),
    evidence_type: str = "attention",
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    """Stream classifier output first, then report tokens as they arrive."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are accepted.")
    try:
        contents = await file.read()
        image = Image.open(BytesIO(contents)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid image: {exc}") from exc
    evidence_type = evidence_type.lower()
    if evidence_type not in ("attention", "gradcam"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid evidence_type.")

    async def events():
        findings = await asyncio.to_thread(pipeline.classifier.predict, image)
        localization_maps = await asyncio.to_thread(
            pipeline.localizer.localize, image, pipeline.classifier, findings, evidence_type
        )
        combined = await asyncio.to_thread(combine_masks, image.size, localization_maps)
        structured = pipeline._structured_findings(findings)
        maps = [
            {"finding": loc.label, "heatmap": encode_image_as_base64(loc.heatmap), "segmentation_mask": encode_image_as_base64(combine_masks(image.size, [loc]))}
            for loc in localization_maps if loc.heatmap is not None
        ]
        findings_json = [
            {"label": f.label, "confidence": f.confidence, "region": f.region,
             "heatmap_b64": next((m["heatmap"] for m in maps if m["finding"] == f.label), None)}
            for f in findings
        ]
        analysis = {
            "image_id": str(uuid.uuid4()), "findings": findings_json,
            "confidence_scores": {f.label: f.confidence for f in findings},
            "localization_maps": maps, "report": "", "report_source": "llm",
            "findings_section": "", "impression_section": "",
            "mask_b64": encode_image_as_base64(combined) if combined is not None else None,
            "evidence_type": evidence_type, "elapsed_seconds": 0.0, "chat_seed": [],
        }
        yield json.dumps({"type": "analysis", "data": analysis}) + "\n"
        from starlette.concurrency import iterate_in_threadpool
        report_parts = []
        stream = pipeline.radiology_llm.report_generator.stream(
            image=image, findings=findings, structured_findings=structured
        )
        async for token in iterate_in_threadpool(stream):
            report_parts.append(token)
            yield json.dumps({"type": "report_token", "token": token}) + "\n"
        report = pipeline.radiology_llm.report_generator._remove_no_finding("".join(report_parts))
        sections = pipeline.radiology_llm.report_generator._split_report_sections(report)
        yield json.dumps({"type": "complete", "data": {
            "report": report, "findings_section": sections.get("findings", ""),
            "impression_section": sections.get("impression", ""), "report_source": "llm"
        }}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


async def _run_analysis(
    file: UploadFile,
    pipeline: AnalysisPipeline,
    evidence_type: str = "attention",
) -> AnalysisResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are accepted.")

    try:
        contents = await file.read()
        image = Image.open(BytesIO(contents)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid image: {exc}") from exc

    evidence_type = evidence_type.lower()
    if evidence_type not in ("attention", "gradcam"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="evidence_type must be 'attention' or 'gradcam'.",
        )

    start = time.time()
    result = pipeline.analyze(image, evidence_type=evidence_type)
    elapsed = time.time() - start

    localization_maps: list[LocalizationMap] = []
    for loc in result.localization_maps:
        if loc.heatmap is not None:
            localization_maps.append(
                LocalizationMap(
                    finding=loc.label,
                    heatmap=encode_image_as_base64(loc.heatmap),
                    segmentation_mask=encode_image_as_base64(combine_masks(image.size, [loc])),
                )
            )

    mask_b64 = None
    if result.mask is not None:
        mask_b64 = encode_image_as_base64(result.mask)

    findings = [
        Finding(
            label=f.label,
            confidence=f.confidence,
            region=f.region,
            heatmap_b64=next(
                (lm.heatmap for lm in localization_maps if lm.finding == f.label),
                None,
            ),
        )
        for f in result.findings
    ]

    return AnalysisResponse(
        image_id=result.image_id,
        findings=findings,
        confidence_scores=result.confidence_scores,
        localization_maps=localization_maps,
        report=result.report,
        report_source=result.report_source,
        findings_section=result.report_sections.get("findings", ""),
        impression_section=result.report_sections.get("impression", ""),
        mask_b64=mask_b64,
        evidence_type=evidence_type,
        elapsed_seconds=elapsed,
        chat_seed=result.chat_seed,
    )


@router.post("/gradcam", response_model=GradCAMResponse)
async def gradcam(
    finding: str,
    file: UploadFile = File(...),
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image files are accepted.")

    try:
        contents = await file.read()
        image = Image.open(BytesIO(contents)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid image: {exc}") from exc

    try:
        heatmap = pipeline.classifier.get_gradcam_heatmap(image, finding)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Grad-CAM failed: {exc}") from exc

    return GradCAMResponse(
        finding=finding,
        heatmap=encode_image_as_base64(heatmap),
    )


@router.post("/generate-report", response_model=GenerateReportResponse)
async def generate_report(
    request: StructuredFindings,
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    structured = request.dict()
    report_result = pipeline.generate_report(structured)
    return GenerateReportResponse(
        report=report_result.report,
        report_source=report_result.source,
        findings_section=report_result.sections.get("findings", ""),
        impression_section=report_result.sections.get("impression", ""),
        tokens_generated=report_result.tokens_generated,
        latency_seconds=report_result.latency_seconds,
        chat_seed=report_result.chat_seed,
    )


@router.get("/chat-status", response_model=ChatStatusResponse)
async def chat_status():
    from models.chat_status import CHAT_STATUS

    return ChatStatusResponse(**CHAT_STATUS.get())


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    # Convert API Finding schema back to internal finding-like objects.
    findings = [
        type("F", (), {"label": f.label, "confidence": f.confidence, "region": f.region})()
        for f in request.findings
    ]
    history = [turn.dict() for turn in request.history]   # NEW
    answer = pipeline.chat(
        request.report, findings, request.question,
        max_tokens=request.max_tokens, history=history,   # NEW
    )
    referenced = _extract_referenced_finding(request.question, request.findings)
    return ChatResponse(answer=answer, referenced_finding=referenced)


@router.post("/chat-stream")
async def chat_stream(
    request: ChatRequest,
    pipeline: AnalysisPipeline = Depends(get_pipeline),
):
    from starlette.concurrency import iterate_in_threadpool

    findings = [
        type("F", (), {"label": f.label, "confidence": f.confidence, "region": f.region})()
        for f in request.findings
    ]
    history = [turn.dict() for turn in request.history]

    def token_generator():
        pipeline.radiology_llm.wait_for_chat_available(timeout=300.0)
        for token in pipeline.radiology_llm.stream_chat(
            request.report, findings, request.question, max_new_tokens=request.max_tokens, history=history
        ):
            yield token

    async def async_token_generator():
        async for token in iterate_in_threadpool(token_generator()):
            yield token

    return StreamingResponse(
        async_token_generator(),
        media_type="text/plain; charset=utf-8",
    )

@router.get("/health")
async def health(pipeline: AnalysisPipeline = Depends(get_pipeline)):
    return {"status": "ok", "device": pipeline.device, "rocm_available": pipeline.rocm_available}


def _extract_referenced_finding(question: str, findings: list[Finding]) -> Optional[str]:
    q = question.lower()
    for f in findings:
        if f.label.lower() in q:
            return f.label
    return None
