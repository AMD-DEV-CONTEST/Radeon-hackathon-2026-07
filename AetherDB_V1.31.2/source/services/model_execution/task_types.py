"""Canonical model task names with one-way legacy compatibility aliases."""

from __future__ import annotations

from dataclasses import dataclass


CANONICAL_TASK_TYPES = frozenset(
    {
        "text.polish",
        "text.expand",
        "text.continue",
        "text.assist",
        "text.rewrite",
        "text.translate",
        "text.summarize",
        "text.logic_check",
        "chapter.analyze",
        "chapter.extract",
        "context.reason",
        "world.consistency_check",
        "prompt.compose",
        "changeset.build",
        "changeset.review",
        "image.generate",
        "image.img2img",
        "image.enhance",
        "image.upscale",
        "image.analyze",
        "image.caption",
        "image.consistency_check",
        "image.embedding.generate",
        "image.search",
        "audio.tts.preview",
        "audio.tts.segment",
        "audio.tts.chapter",
        "audio.asr.transcribe",
        "audio.enhance",
        "audio.merge",
        "audio.normalize",
        "audio.export",
        "rag.text.query",
        "rag.text.index",
        "rag.visual.query",
        "rag.visual.index",
        "rag.hybrid.query",
    }
)

LEGACY_TASK_ALIASES = {
    "creative_continue": "text.continue",
    "creative_assist": "text.assist",
    "chapter_analysis": "chapter.analyze",
    "world_consistency": "world.consistency_check",
    "logic_check": "text.logic_check",
    "chapter_extract": "chapter.extract",
    "changeset_build": "changeset.build",
    "changeset_review": "changeset.review",
    "rag_answer": "rag.text.query",
    "translation.entity": "text.translate",
    "translation.chapter": "text.translate",
    "audio.preview": "audio.tts.preview",
}


@dataclass(frozen=True)
class TaskTypeResolution:
    source: str
    canonical: str
    legacy_source: str | None

    @property
    def binding_lookup_types(self) -> tuple[str, ...]:
        if self.legacy_source:
            return self.legacy_source, self.canonical
        return (self.canonical,)


def resolve_task_type(value: str) -> TaskTypeResolution:
    source = value.strip()
    if source in CANONICAL_TASK_TYPES:
        return TaskTypeResolution(source, source, None)
    canonical = LEGACY_TASK_ALIASES.get(source)
    if canonical:
        return TaskTypeResolution(source, canonical, source)
    raise ValueError("unsupported task type")


def accepted_task_types() -> frozenset[str]:
    return CANONICAL_TASK_TYPES | frozenset(LEGACY_TASK_ALIASES)


def task_type_catalog() -> list[dict[str, object]]:
    legacy_by_canonical: dict[str, list[str]] = {}
    for legacy, canonical in LEGACY_TASK_ALIASES.items():
        legacy_by_canonical.setdefault(canonical, []).append(legacy)
    return [
        {
            "task_type": task_type,
            "legacy_aliases": sorted(legacy_by_canonical.get(task_type, [])),
        }
        for task_type in sorted(CANONICAL_TASK_TYPES)
    ]
