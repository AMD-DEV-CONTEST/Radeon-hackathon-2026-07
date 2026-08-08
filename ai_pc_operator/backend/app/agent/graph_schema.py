"""Execution-graph schema for the planning-engine layer.

This module mirrors the Node.js planning-engine schema in
``pipeline/operations.js`` so the Python backend can produce and consume
the same execution-graph format.

Node types:
    observe, decide, parallel, act, verify, retry, rollback,
    checkpoint, approval, wait, replan, finish

Risk levels (0-4):
    0 = read-only
    1 = safe local
    2 = local destructive
    3 = external communication
    4 = financial / credentials / security / irreversible
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ─── Constants ───────────────────────────────────────────────────────────────

NODE_TYPES = frozenset({
    "observe",
    "decide",
    "parallel",
    "act",
    "verify",
    "retry",
    "rollback",
    "checkpoint",
    "approval",
    "wait",
    "replan",
    "finish",
})

RISK_LEVELS = {
    "READ_ONLY": 0,
    "SAFE_LOCAL": 1,
    "LOCAL_DESTRUCTIVE": 2,
    "EXTERNAL": 3,
    "CRITICAL": 4,
}

# Risk threshold above which an approval node must be inserted upstream.
APPROVAL_REQUIRED_RISK = 3

# Tool-prefix -> pipeline domain (Phase 3: pipeline orchestration).
TOOL_PIPELINE = {
    "system.": "application",
    "app.": "application",
    "file.": "filesystem",
    "browser.": "browser",
    "screen.": "screen",
    "window.": "window",
    "auth.": "authentication",
    "terminal.": "terminal",
    "dev.": "developer",
    "ocr.": "ocr",
    "vision.": "vision",
    "clipboard.": "clipboard",
    "email.": "email",
    "network.": "network",
    "media.": "media",
    "doc.": "document",
    "memory.": "memory",
    "task.": "task",
    "research.": "research",
    "approval.": "approval",
}


def tool_pipeline(tool: str) -> str:
    """Return the pipeline domain for a tool name (tool-prefix based)."""
    for prefix, domain in TOOL_PIPELINE.items():
        if tool.startswith(prefix):
            return domain
    return "system"


def _models_for_tool(tool: str) -> List[str]:
    """Return the model lanes a tool needs (Phase 4: model orchestration).

    Lazily imports from the planner to avoid an import cycle (planner does
    not import graph_schema at module load).
    """
    try:
        from app.agent.planner import MODEL_REQUIREMENTS
    except Exception:  # pragma: no cover - defensive
        return []
    # Best-effort: match the tool name to an intent in MODEL_REQUIREMENTS by
    # stripping the category prefix (file.list -> file_list, etc.).
    tool_key = tool.replace(".", "_")
    if tool_key in MODEL_REQUIREMENTS:
        return list(MODEL_REQUIREMENTS[tool_key])
    # Fall back to a per-pipeline default
    return {"application": ["app_detector"],
            "filesystem": ["filesystem"],
            "browser": ["browser_automation"],
            "screen": ["ocr", "vision", "ui_detector"],
            "ocr": ["ocr"],
            "vision": ["vision", "ui_detector"],
            "system": ["system_control"],
            "authentication": ["vault", "ocr", "vision"],
            }.get(tool_pipeline(tool), [])


# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass
class VerificationSpec:
    method: str
    success: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"method": self.method, "success": self.success}


@dataclass
class ExecutionNode:
    id: str
    type: str
    objective: str
    reason: str = ""
    preferred_skill: Optional[str] = None
    alternative_skills: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_result: str = ""
    verification: VerificationSpec = field(default_factory=lambda: VerificationSpec(method="always", success="true"))
    failure_conditions: List[str] = field(default_factory=list)
    recovery: List[str] = field(default_factory=list)
    risk: int = 1
    estimated_duration: int = 5
    confidence: float = 0.8

    def __post_init__(self) -> None:
        if self.type not in NODE_TYPES:
            raise ValueError(f"Invalid node type: {self.type}")
        if not self.id:
            raise ValueError("Node must have an id")
        if not self.objective:
            raise ValueError(f"Node {self.id} must have an objective")
        if not self.verification.method:
            raise ValueError(f"Node {self.id} must have verification.method")
        if not self.recovery:
            raise ValueError(f"Node {self.id} must have at least one recovery option")
        if self.risk < 0 or self.risk > 4:
            raise ValueError(f"Node {self.id}: risk must be 0-4")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["verification"] = self.verification.to_dict()
        return d


# ─── Builder helpers ─────────────────────────────────────────────────────────

def build_node(spec: Dict[str, Any]) -> ExecutionNode:
    """Build an ExecutionNode from a dict spec."""
    verification = spec.get("verification") or {}
    if isinstance(verification, dict):
        verification = VerificationSpec(
            method=verification.get("method", "always"),
            success=verification.get("success", ""),
        )
    return ExecutionNode(
        id=spec["id"],
        type=spec["type"],
        objective=spec["objective"],
        reason=spec.get("reason", ""),
        preferred_skill=spec.get("preferred_skill"),
        alternative_skills=list(spec.get("alternative_skills", [])),
        dependencies=list(spec.get("dependencies", [])),
        parameters=dict(spec.get("parameters", {})),
        expected_result=spec.get("expected_result", ""),
        verification=verification,
        failure_conditions=list(spec.get("failure_conditions", [])),
        recovery=list(spec.get("recovery", [])),
        risk=int(spec.get("risk", 1)),
        estimated_duration=int(spec.get("estimated_duration", 5)),
        confidence=float(spec.get("confidence", 0.8)),
    )


def validate_node(node_or_graph) -> Dict[str, Any]:
    """Validate a single node or a list of nodes.

    Returns ``{"ok": bool, "errors": [str, ...]}``.
    """
    errors: List[str] = []
    nodes = node_or_graph if isinstance(node_or_graph, list) else [node_or_graph]

    for node in nodes:
        if not isinstance(node, dict):
            errors.append("node is not a dict")
            continue
        if node.get("type") not in NODE_TYPES:
            errors.append(f"node {node.get('id', '?')}: invalid type {node.get('type')}")
        if not node.get("id"):
            errors.append("node missing id")
        if not node.get("objective"):
            errors.append(f"node {node.get('id', '?')}: missing objective")
        v = node.get("verification") or {}
        if not v.get("method"):
            errors.append(f"node {node.get('id', '?')}: missing verification.method")
        if not node.get("recovery"):
            errors.append(f"node {node.get('id', '?')}: missing recovery[]")
        risk = node.get("risk", 0)
        if isinstance(risk, int) and (risk < 0 or risk > 4):
            errors.append(f"node {node.get('id', '?')}: risk must be 0-4")

    if isinstance(node_or_graph, list) and len(node_or_graph) > 1:
        ids = set()
        for n in node_or_graph:
            if n.get("id") in ids:
                errors.append(f"duplicate node id: {n.get('id')}")
            ids.add(n.get("id"))
        for n in node_or_graph:
            for dep in n.get("dependencies", []) or []:
                if dep not in ids:
                    errors.append(f"node {n.get('id')}: unknown dependency {dep}")
        # High-risk nodes must have an upstream approval node
        for n in node_or_graph:
            if (n.get("risk") or 0) >= APPROVAL_REQUIRED_RISK:
                deps = n.get("dependencies", []) or []
                has_approval_dep = any(
                    (m.get("id") in deps and m.get("type") == "approval")
                    for m in node_or_graph
                )
                if not has_approval_dep:
                    errors.append(
                        f"node {n.get('id')}: risk {n.get('risk')} requires an upstream approval node"
                    )

    return {"ok": not errors, "errors": errors}


def insert_approval_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Auto-insert approval nodes before any high-risk action."""
    out: List[Dict[str, Any]] = []
    # Find the highest numeric suffix in existing auto_approval_/node_ IDs
    next_id = 0
    for n in nodes:
        nid = str(n.get("id", ""))
        for prefix in ("auto_approval_", "node_"):
            if nid.startswith(prefix):
                try:
                    next_id = max(next_id, int(nid[len(prefix):]))
                except ValueError:
                    pass
    next_id += 1

    for node in nodes:
        if (node.get("risk") or 0) >= APPROVAL_REQUIRED_RISK:
            approval_id = f"auto_approval_{next_id}"
            next_id += 1
            approval = {
                "id": approval_id,
                "type": "approval",
                "objective": f"Request mobile approval for {node.get('objective')}",
                "reason": f"Auto-inserted because node {node.get('id')} has risk {node.get('risk')} >= {APPROVAL_REQUIRED_RISK}",
                "preferred_skill": "approvals.manager.create_approval",
                "alternative_skills": ["approvals.manager.wait_for_approval"],
                "dependencies": list(node.get("dependencies", []) or []),
                "parameters": {
                    "risk_level": node.get("risk"),
                    "action_type": node.get("objective"),
                },
                "expected_result": "User approves or rejects the action",
                "verification": {"method": "approval_resolved", "success": "approval status is approved"},
                "recovery": [
                    "If rejected, return rejected status to caller",
                    "If timeout, abort the downstream action",
                ],
                "risk": RISK_LEVELS["READ_ONLY"],
                "estimated_duration": 30,
                "confidence": 0.95,
            }
            out.append(approval)
            node["dependencies"] = list(node.get("dependencies", []) or []) + [approval_id]
        out.append(node)
    return out


# ─── Plan → graph conversion ─────────────────────────────────────────────────

def plan_to_graph(
    plan: Dict[str, Any],
    risk_level: int = 1,
    goal: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Convert a legacy plan (with ``steps``) into an execution graph.

    Each step becomes an ``act`` node with pipeline + model orchestration
    metadata (Phase 3/4). A ``verify_goal`` node checks the user's objective
    (Phase 10). If the plan's risk is >= 3, an approval node is auto-inserted
    upstream.
    """
    steps = plan.get("steps", []) or []
    nodes: List[Dict[str, Any]] = []

    # Observe node — captures the plan intent
    nodes.append({
        "id": "observe_plan",
        "type": "observe",
        "objective": f"Interpret plan: {plan.get('intent', 'unknown')}",
        "preferred_skill": "agent.planner",
        "parameters": {"plan": plan},
        "expected_result": "Plan interpretation",
        "verification": {"method": "returns_object", "success": "plan has steps"},
        "recovery": ["Use empty plan", "Ask user for clarification"],
        "risk": 0,
        "estimated_duration": 1,
        "confidence": 0.95,
    })

    # Act nodes — one per step (with pipeline + model orchestration metadata)
    for i, step in enumerate(steps):
        tool = step.get("tool", f"step_{i}")
        nodes.append({
            "id": f"act_{i}_{tool.replace('.', '_')}",
            "type": "act",
            "objective": f"Execute {tool}",
            "preferred_skill": tool,
            "dependencies": ["observe_plan"] if i == 0 else [f"act_{i - 1}_{steps[i - 1].get('tool', f'step_{i - 1}').replace('.', '_')}"],
            "parameters": step.get("args", {}),
            "expected_result": f"{tool} succeeded",
            "verification": {"method": "tool_success", "success": "result.status == success"},
            "recovery": [
                "Retry once",
                "Use alternative skill",
                "Report failure to user",
            ],
            "risk": int(step.get("risk", risk_level)),
            "estimated_duration": int(step.get("estimated_duration", 5)),
            "confidence": float(step.get("confidence", 0.85)),
            "pipeline": tool_pipeline(tool),
            "models": _models_for_tool(tool),
        })

    # Verify node — checks all steps succeeded
    if steps:
        last_id = f"act_{len(steps) - 1}_{steps[-1].get('tool', f'step_{len(steps) - 1}').replace('.', '_')}"
        nodes.append({
            "id": "verify_all",
            "type": "verify",
            "objective": "Verify all steps succeeded",
            "dependencies": [n["id"] for n in nodes if n["type"] == "act"],
            "verification": {"method": "all_success", "success": "every act node returned success"},
            "recovery": ["Re-run failed act node", "Report partial success"],
            "risk": 0,
            "estimated_duration": 1,
            "confidence": 0.95,
        })

    # Goal-verification node — Phase 10: task is complete only when the
    # user's objective is verified, not just when the tools ran.
    if steps:
        goal_text = goal or str(plan.get("intent") or "complete the request")
        nodes.append({
            "id": "verify_goal",
            "type": "verify",
            "objective": f"Verify goal achieved: {goal_text}",
            "dependencies": ["verify_all"],
            "verification": {
                "method": "goal_achieved",
                "success": "the user objective was completed",
            },
            "recovery": [
                "Report partial progress to user",
                "Re-run failed act node",
                "Ask user for clarification",
            ],
            "risk": 0,
            "estimated_duration": 1,
            "confidence": 0.9,
            "goal": goal_text,
        })

    # Finish node
    finish_deps = ["verify_goal"] if steps else ["observe_plan"]
    nodes.append({
        "id": "finish",
        "type": "finish",
        "objective": "Plan complete",
        "dependencies": finish_deps,
        "verification": {"method": "always", "success": "true"},
        "recovery": ["No-op"],
        "risk": 0,
        "estimated_duration": 0,
        "confidence": 1.0,
    })

    # Auto-insert approval nodes for high-risk actions
    nodes = insert_approval_nodes(nodes)
    return nodes


def graph_to_dict_list(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a JSON-serializable list of node dicts."""
    return [dict(n) for n in nodes]
