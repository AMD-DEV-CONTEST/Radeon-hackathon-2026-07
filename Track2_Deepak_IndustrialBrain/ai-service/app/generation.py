from __future__ import annotations
import json
import urllib.error
import urllib.parse
import urllib.request
from .config import settings
from .local_llm import local_llm_instance


FORMAT_INSTRUCTIONS = {
    "work_order": "Structure your answer as a maintenance work order with fields: "
                  "Asset, Reported Problem, Recommended Action, Parts/Tools Required, "
                  "Safety Precautions, Priority.",
    "checklist":  "Return a numbered checklist of concrete inspection/action steps.",
    "table":      "Return the key facts as a markdown table (Field | Value).",
    "report":     "Write a formal RCA-style report with headed sections.",
    "quick_answer": "Answer concisely in 1-2 sentences using only the supplied evidence."
}


def generate_answer(question: str, evidence: list[dict], desired_format: str = "quick_answer") -> tuple[str, str]:
    mode_label = "local-model" if settings.local_llm_enabled else "offline-evidence"
    answer = _offline_answer(question, evidence, desired_format)
    return answer, mode_label


def _local_llm(question: str, evidence: list[dict], desired_format: str = "quick_answer") -> str:
    context = "\n\n".join(
        f"[Source {index}: {item['metadata']['source']}, page {item['metadata']['page']}]\n{item['text']}"
        for index, item in enumerate(evidence, start=1)
    )
    fmt = FORMAT_INSTRUCTIONS.get(desired_format, FORMAT_INSTRUCTIONS["quick_answer"])
    prompt = f"""You are an industrial knowledge copilot. {fmt}

### Question:
{question}

### Evidence:
{context}

### Answer:
"""
    base_answer = local_llm_instance.generate(prompt)
    if not base_answer:
        return ""
    if desired_format == "quick_answer":
        return base_answer
    return _format_structured(base_answer, evidence, desired_format)


def _format_structured(base_answer: str, evidence: list[dict], desired_format: str) -> str:
    failures, actions, measurements = set(), set(), set()
    source_ref = evidence[0]["metadata"]["source"] if evidence else "Industrial KB"
    for item in evidence:
        meta = item["metadata"]
        failures.update(filter(None, meta.get("failures", "").split(",")))
        actions.update(filter(None, meta.get("actions", "").split(",")))
        measurements.update(filter(None, meta.get("measurements", "").split(",")))

    failure_str = ", ".join(sorted(failures)) or "None explicitly flagged in metadata"
    action_str = ", ".join(sorted(actions)) or "Refer to maintenance procedure SOP"
    meas_str = ", ".join(sorted(measurements)[:5]) or "Standard operating baselines"

    if desired_format == "table":
        return (
            "| Field | AI Synthesis & Extracted Evidence |\n"
            "| --- | --- |\n"
            f"| **AI Assessment** | {base_answer} |\n"
            f"| **Extracted Failures** | {failure_str} |\n"
            f"| **Recommended Actions** | {action_str} |\n"
            f"| **Specifications** | {meas_str} |\n"
            f"| **Primary Reference** | {source_ref} |"
        )
    elif desired_format == "checklist":
        return (
            f"### [CHECKLIST] Operational & Maintenance Verification\n\n"
            f"1. **Verify Core Assessment**\n"
            f"   - [ ] {base_answer}\n\n"
            f"2. **Inspect for Failure Modes**\n"
            f"   - [ ] Check for: {failure_str}\n\n"
            f"3. **Execute Maintenance Steps**\n"
            f"   - [ ] Action items: {action_str}\n\n"
            f"4. **Validate Operating Specifications**\n"
            f"   - [ ] Verify against: {meas_str}\n\n"
            f"5. **Confirm Document Reference**\n"
            f"   - [ ] Source document: {source_ref}"
        )
    elif desired_format == "work_order":
        return (
            f"### [WORK ORDER] Maintenance Task Order\n\n"
            f"- **Priority**: `HIGH`\n"
            f"- **Primary Reference**: `{source_ref}`\n"
            f"- **Reported Problem / AI Synthesis**:\n"
            f"  {base_answer}\n"
            f"- **Identified Failure Modes**:\n"
            f"  {failure_str}\n"
            f"- **Recommended Corrective Actions**:\n"
            f"  {action_str}\n"
            f"- **Required Readings / Specs**:\n"
            f"  {meas_str}"
        )
    elif desired_format == "report":
        return (
            f"### [REPORT] Technical Root Cause & Evidence Report\n\n"
            f"#### 1. Executive Summary\n"
            f"{base_answer}\n\n"
            f"#### 2. Identified Failure Modes\n"
            f"- {failure_str}\n\n"
            f"#### 3. Corrective & Preventative Actions\n"
            f"- {action_str}\n\n"
            f"#### 4. Measurements & Operating Parameters\n"
            f"- {meas_str}\n\n"
            f"#### 5. Primary Source Documentation\n"
            f"- Document: `{source_ref}`"
        )
    return base_answer


def _gemini(question: str, evidence: list[dict], desired_format: str = "quick_answer") -> str:
    context = "\n\n".join(
        f"[Source {index}: {item['metadata']['source']}, page {item['metadata']['page']}]\n{item['text']}"
        for index, item in enumerate(evidence, start=1)
    )
    fmt = FORMAT_INSTRUCTIONS.get(desired_format, FORMAT_INSTRUCTIONS["quick_answer"])
    prompt = f"""You are an industrial knowledge copilot. Answer only from the supplied evidence.
If the evidence is insufficient, say that clearly. Do not invent measurements, causes, or dates.
{fmt} Citations are shown separately by the UI.

Question: {question}

Evidence:
{context}
"""
    model = urllib.parse.quote(settings.gemini_model, safe="")
    key = urllib.parse.quote(settings.gemini_api_key, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.15, "maxOutputTokens": 700}
    }).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (urllib.error.URLError, KeyError, IndexError, TimeoutError):
        return ""


def _offline_answer(question: str, evidence: list[dict], desired_format: str = "quick_answer") -> str:
    if not evidence or evidence[0]["score"] < 0.01:
        return "I could not find sufficient evidence in the indexed industrial documents to answer this question."
    failures, actions, measurements = set(), set(), set()
    sources = set()
    for item in evidence:
        meta = item["metadata"]
        failures.update(filter(None, meta.get("failures", "").split(",")))
        actions.update(filter(None, meta.get("actions", "").split(",")))
        measurements.update(filter(None, meta.get("measurements", "").split(",")))
        sources.add(meta.get("source", ""))

    # ── "Tell me about <document>" style queries ────────────────────
    q_lower = question.lower()
    is_about_query = any(w in q_lower for w in ["tell me about", "what is in", "summarize", "summary of", "describe", "contents of"])
    if is_about_query or (not failures and not actions and not measurements):
        # Build a document summary from the raw evidence text
        source_label = ", ".join(sorted(sources)) if sources else "the uploaded document"
        snippets = []
        for item in evidence[:3]:
            snippet = item["text"][:400].strip()
            if snippet:
                snippets.append(snippet)
        if snippets:
            intro = f"Here is a summary of the contents from **{source_label}**:\n\n"
            body = "\n\n".join(f"> {s}" for s in snippets)
            if failures or actions:
                extras = []
                if failures:
                    extras.append(f"**Detected failure patterns**: {', '.join(sorted(failures))}")
                if actions:
                    extras.append(f"**Recorded actions**: {', '.join(sorted(actions))}")
                body += "\n\n" + " | ".join(extras)
            return intro + body
        # If still nothing, fall through to generic response

    if desired_format == "table":
        table_rows = [
            "| Field | Extracted Evidence |",
            "| --- | --- |",
            f"| Failures | {', '.join(sorted(failures)) or 'None detected'} |",
            f"| Actions | {', '.join(sorted(actions)) or 'None detected'} |",
            f"| Measurements | {', '.join(sorted(measurements)[:5]) or 'None detected'} |",
            f"| Top Evidence | {evidence[0]['text'][:200].strip()}... |"
        ]
        return "\n".join(table_rows)
    elif desired_format == "checklist":
        return f"1. Inspect asset for failures: {', '.join(sorted(failures)) or 'None observed'}\n2. Verify maintenance actions taken: {', '.join(sorted(actions)) or 'None recorded'}\n3. Check readings against baseline: {', '.join(sorted(measurements)[:5]) or 'N/A'}"
    elif desired_format == "work_order":
        return f"**Work Order**\n- **Problem**: {', '.join(sorted(failures)) or 'Reported issue'}\n- **Recommended Action**: {', '.join(sorted(actions)) or 'Inspect asset'}\n- **Priority**: High\n- **Evidence**: {evidence[0]['text'][:250].strip()}"
    elif desired_format == "report":
        return f"### Technical Root Cause & Evidence Report\n- **Identified Failure Modes**: {', '.join(sorted(failures)) or 'None detected'}\n- **Recommended Corrective Actions**: {', '.join(sorted(actions)) or 'Standard inspection'}\n- **Primary Evidence**: {evidence[0]['text'][:350].strip()}"


    if failures and any(w in q_lower for w in ["why", "fail", "cause"]):
        return f"Based on the indexed maintenance records, observed failure modes include: {', '.join(sorted(failures))}. Key corrective actions: {', '.join(sorted(actions)) or 'Standard inspection procedures'}."
    parts = []
    if failures:
        parts.append("Observed failure patterns include: " + ", ".join(sorted(failures)) + ".")
    if actions:
        parts.append("Recorded maintenance actions include: " + ", ".join(sorted(actions)) + ".")
    if measurements:
        parts.append("Relevant measurements include: " + ", ".join(sorted(measurements)[:8]) + ".")
    if not parts:
        parts.append(evidence[0]["text"][:450].strip())
    else:
        parts.append("Primary evidence: " + evidence[0]["text"][:350].strip())
    return " ".join(parts)


def generate_rca(tag: str, evidence: list[dict]) -> dict:
    failures, actions, dates, measurements = set(), set(), set(), set()
    for item in evidence:
        meta = item["metadata"]
        failures.update(filter(None, meta.get("failures", "").split(",")))
        actions.update(filter(None, meta.get("actions", "").split(",")))
        dates.update(filter(None, meta.get("dates", "").split(",")))
        measurements.update(filter(None, meta.get("measurements", "").split(",")))
    failure_text = ", ".join(sorted(failures)) or "No explicit failure category extracted"
    likely_causes = []
    if "bearing wear" in failures or "bearing failure" in failures:
        likely_causes.extend(["Lubrication quality or interval", "Shaft alignment", "Excess vibration or load"])
    if "overheating" in failures:
        likely_causes.append("Cooling, lubrication, or operating-load condition")
    if "cavitation" in failures:
        likely_causes.append("Insufficient suction head or restricted inlet")
    if not likely_causes:
        likely_causes = ["Review operating conditions and the highest-ranked source passages"]
    confidence = min(0.94, 0.45 + len(evidence) * 0.06 + len(failures) * 0.05)
    return {
        "assetTag": tag.upper(),
        "observedProblem": failure_text,
        "probableCauses": list(dict.fromkeys(likely_causes)),
        "recordedActions": sorted(actions),
        "measurements": sorted(measurements),
        "eventDates": sorted(dates),
        "recommendedInvestigation": [
            "Validate the timeline against the cited maintenance and inspection records.",
            "Inspect lubrication condition, alignment, vibration trend, and operating envelope.",
            "Confirm corrective actions were closed and verify recurrence after each intervention.",
        ],
        "preventiveActions": [
            "Introduce condition-based vibration and temperature checks.",
            "Track recurring failure modes by asset and maintenance action.",
            "Require evidence-linked closure notes after corrective maintenance.",
        ],
        "confidence": round(confidence, 2),
        "disclaimer": "Decision-support analysis based on uploaded records; engineering verification is required.",
    }

