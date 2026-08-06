"""Radeon Requirement Guardian - a compact, fully local agentic AI demo.

The language model is served by a local vLLM OpenAI-compatible endpoint on
AMD Radeon. Document tools, memory, report generation, and verification all
run locally as well.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
DB_PATH = DATA_DIR / "memory.db"
DEFAULT_ENDPOINT = os.getenv(
    "VLLM_ENDPOINT", "http://127.0.0.1:8000/v1/chat/completions"
)
DEFAULT_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen3-0.6B")


def tokenize(text: str) -> set[str]:
    """Tokenize English, numbers, and individual CJK characters."""
    return set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text.lower()))


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    if not chunks and text.strip():
        chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    return chunks


def search_chunks(chunks: list[str], query: str, top_k: int = 4) -> list[dict[str, Any]]:
    query_tokens = tokenize(query)
    scored: list[tuple[float, int, str]] = []
    for index, chunk in enumerate(chunks):
        chunk_tokens = tokenize(chunk)
        overlap = len(query_tokens & chunk_tokens)
        phrase_bonus = 2 if query.lower() in chunk.lower() else 0
        score = overlap + phrase_bonus
        if score > 0:
            scored.append((float(score), index, chunk))
    if not scored:
        scored = [(0.0, i, chunk) for i, chunk in enumerate(chunks[:top_k])]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"chunk_id": index + 1, "score": score, "text": chunk}
        for score, index, chunk in scored[:top_k]
    ]


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def read_document(path: str) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".log"}:
        return file_path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    raise ValueError("Supported files: PDF, TXT, MD, CSV, and LOG")


class LocalMemory:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                task TEXT NOT NULL,
                summary TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def recall(self, query: str, limit: int = 3) -> list[str]:
        terms = sorted(tokenize(query), key=len, reverse=True)[:5]
        if not terms:
            return []
        where = " OR ".join(["lower(task || ' ' || summary) LIKE ?"] * len(terms))
        params = [f"%{term.lower()}%" for term in terms]
        rows = self.connection.execute(
            f"SELECT task, summary FROM memories WHERE {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [f"Previous task: {task}\nMemory: {summary}" for task, summary in rows]

    def save(self, task: str, summary: str) -> None:
        self.connection.execute(
            "INSERT INTO memories(task, summary) VALUES (?, ?)", (task, summary[:4000])
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


@dataclass
class ModelResult:
    content: str
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int


class LocalVLLM:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, model: str = DEFAULT_MODEL) -> None:
        self.endpoint = endpoint
        self.model = model

    def chat(self, system: str, user: str, max_tokens: int = 700) -> ModelResult:
        import requests

        started = time.perf_counter()
        response = requests.post(
            self.endpoint,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        usage = payload.get("usage") or {}
        elapsed = time.perf_counter() - started
        return ModelResult(
            content=payload["choices"][0]["message"]["content"],
            elapsed_seconds=elapsed,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        )


class RequirementGuardian:
    """Plan, use local tools, write a report, verify it, and remember the result."""

    def __init__(self, llm: LocalVLLM | None = None, memory: LocalMemory | None = None):
        self.llm = llm or LocalVLLM()
        self.memory = memory or LocalMemory()

    def _make_plan(self, task: str, preview: str) -> tuple[dict[str, Any], ModelResult]:
        prompt = f"""Task: {task}

Document preview:
{preview[:5000]}

Return JSON only using this schema:
{{
  "goal": "one sentence",
  "steps": ["step 1", "step 2", "step 3"],
  "search_queries": ["query 1", "query 2", "query 3"]
}}
The plan must search for mandatory requirements, deliverables, deadlines, risks, and evidence.
"""
        result = self.llm.chat(
            "You are a local planning agent. Produce a short executable plan. /no_think",
            prompt,
            max_tokens=350,
        )
        plan = extract_json_object(result.content) or {
            "goal": task,
            "steps": [
                "Extract mandatory requirements and constraints",
                "Build an evidence-backed checklist",
                "Verify coverage and identify risks",
            ],
            "search_queries": [task, "mandatory requirements deliverables", "deadline risks evidence"],
        }
        plan["search_queries"] = list(plan.get("search_queries") or [])[:5]
        if not plan["search_queries"]:
            plan["search_queries"] = [task]
        return plan, result

    def run(self, document_path: str, task: str) -> dict[str, str]:
        total_started = time.perf_counter()
        trace: list[dict[str, Any]] = []
        model_calls: list[ModelResult] = []

        document = read_document(document_path)
        if not document.strip():
            raise ValueError("The uploaded document contains no extractable text.")
        chunks = chunk_text(document)
        trace.append({"tool": "read_document", "result": f"{len(document)} characters, {len(chunks)} chunks"})

        memories = self.memory.recall(task)
        trace.append({"tool": "recall_memory", "result": f"{len(memories)} relevant memories"})

        plan, plan_call = self._make_plan(task, document)
        model_calls.append(plan_call)
        trace.append({"agent": "planner", "result": plan})

        evidence: list[dict[str, Any]] = []
        for query in plan["search_queries"]:
            hits = search_chunks(chunks, str(query), top_k=3)
            evidence.extend({"query": query, **hit} for hit in hits)
            trace.append(
                {
                    "tool": "search_document",
                    "query": query,
                    "result": [hit["chunk_id"] for hit in hits],
                }
            )

        unique_evidence: dict[int, dict[str, Any]] = {}
        for item in evidence:
            unique_evidence.setdefault(int(item["chunk_id"]), item)
        evidence = list(unique_evidence.values())[:10]
        evidence_text = "\n\n".join(
            f"[Evidence {item['chunk_id']}] {item['text']}" for item in evidence
        )
        memory_text = "\n\n".join(memories) if memories else "No relevant prior memory."

        report_prompt = f"""User task:
{task}

Execution plan:
{json.dumps(plan, ensure_ascii=False, indent=2)}

Tool evidence:
{evidence_text[:12000]}

Relevant local memory:
{memory_text[:2500]}

Create an actionable Markdown report with these exact sections:
# Executive Summary
## Mandatory Requirements
## Deliverables Checklist
## Execution Plan
## Risks and Missing Information
## Evidence Used

Use checkboxes. Cite evidence as [Evidence N]. Never invent a requirement. Mark uncertain items clearly.
"""
        report_call = self.llm.chat(
            "You are an evidence-grounded execution agent running locally on AMD Radeon. /no_think",
            report_prompt,
            max_tokens=1100,
        )
        model_calls.append(report_call)
        report = re.sub(r"<think>.*?</think>", "", report_call.content, flags=re.DOTALL).strip()
        trace.append({"agent": "report_writer", "result": "Drafted evidence-backed checklist"})

        verify_prompt = f"""Task: {task}

Plan:
{json.dumps(plan, ensure_ascii=False)}

Report:
{report[:10000]}

Return JSON only:
{{"status":"PASS or NEEDS_REVIEW","coverage_score":0-100,"missing_items":["..."],"unsupported_claims":["..."]}}
Check that the report covers the plan and does not make claims without evidence.
"""
        verify_call = self.llm.chat(
            "You are the independent verification stage of a local agent. /no_think",
            verify_prompt,
            max_tokens=350,
        )
        model_calls.append(verify_call)
        verification = extract_json_object(verify_call.content) or {
            "status": "NEEDS_REVIEW",
            "coverage_score": 0,
            "missing_items": ["Verifier did not return valid JSON; manual review required."],
            "unsupported_claims": [],
        }
        trace.append({"agent": "verifier", "result": verification})

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = OUTPUT_DIR / "latest_report.md"
        report_path.write_text(
            report + "\n\n## Independent Verification\n\n```json\n"
            + json.dumps(verification, ensure_ascii=False, indent=2)
            + "\n```\n",
            encoding="utf-8",
        )
        trace.append({"tool": "write_report", "result": str(report_path)})

        memory_summary = (
            f"Goal: {plan.get('goal', task)}. Verification: "
            f"{verification.get('status')} ({verification.get('coverage_score')}/100)."
        )
        self.memory.save(task, memory_summary)
        trace.append({"tool": "save_memory", "result": memory_summary})

        elapsed = time.perf_counter() - total_started
        completion_tokens = sum(call.completion_tokens for call in model_calls)
        inference_seconds = sum(call.elapsed_seconds for call in model_calls)
        metrics = {
            "hardware_target": "AMD Radeon PRO W7900D (gfx1100)",
            "runtime": "ROCm 7.2.1 + vLLM",
            "model": self.llm.model,
            "model_calls": len(model_calls),
            "completion_tokens": completion_tokens,
            "inference_seconds": round(inference_seconds, 2),
            "end_to_end_seconds": round(elapsed, 2),
            "observed_decode_tokens_per_second": round(completion_tokens / inference_seconds, 2)
            if completion_tokens and inference_seconds
            else "not reported by server",
        }
        return {
            "report": report,
            "verification": json.dumps(verification, ensure_ascii=False, indent=2),
            "trace": json.dumps(trace, ensure_ascii=False, indent=2),
            "metrics": json.dumps(metrics, ensure_ascii=False, indent=2),
        }


def run_from_ui(file_path: str | None, task: str) -> tuple[str, str, str, str]:
    if not file_path:
        return "Please upload a document.", "", "", ""
    if not task.strip():
        task = "Extract all requirements and create a submission-ready checklist."
    try:
        result = RequirementGuardian().run(file_path, task)
        return result["report"], result["verification"], result["trace"], result["metrics"]
    except Exception as exc:
        message = f"Agent failed: {type(exc).__name__}: {exc}"
        return message, "", "", ""


def build_app():
    import gradio as gr

    with gr.Blocks(title="Radeon Requirement Guardian") as app:
        gr.Markdown(
            """# Radeon Requirement Guardian
An offline document-to-action agent with planning, tool use, SQLite memory, and independent verification. All LLM inference is served locally by vLLM on AMD Radeon.
"""
        )
        with gr.Row():
            document = gr.File(label="Requirement document", type="filepath")
            task = gr.Textbox(
                label="Task",
                value="Extract all mandatory requirements and create a submission-ready checklist.",
                lines=4,
            )
        run_button = gr.Button("Run Local Agent", variant="primary")
        report = gr.Markdown(label="Action Report")
        with gr.Tab("Independent Verification"):
            verification = gr.Code(language="json")
        with gr.Tab("Agent Trace"):
            trace = gr.Code(language="json")
        with gr.Tab("AMD Performance"):
            metrics = gr.Code(language="json")
        run_button.click(
            run_from_ui,
            inputs=[document, task],
            outputs=[report, verification, trace, metrics],
        )
    return app


if __name__ == "__main__":
    build_app().launch(server_name="0.0.0.0", server_port=7862)
