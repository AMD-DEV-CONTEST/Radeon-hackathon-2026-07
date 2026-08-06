"""
investigate.py

Per-workload investigation orchestrator.

Responsibilities:
    - Accept a single unhealthy workload dict from the discovery phase.
    - Create an isolated per-workload evidence dict.
    - Run the LLM reasoning loop (preserved from original architecture).
    - Return a structured investigation result.

The reasoning loop:
    1. Build a prompt with workload context + collected evidence.
    2. Ask the LLM: "what tool next, or are you done?"
    3. If "need_more_evidence" → execute the requested tool → add to evidence → repeat.
    4. If "complete" → return the final diagnosis.
    5. Safeguards: repeated tool requests, invalid tool names, max iterations.
"""

import json
import time

from evidence import new_evidence
from tools import AVAILABLE_TOOLS, execute_tool
from ask_llm import ask_llm
import re
from kubernetes_tools import resolve_deployment_name



# Maximum iterations before forcing a final answer
MAX_ITERATIONS = 20
DEFINITIVE_PATTERNS = [
    (r'configmap\s+"([^"]+)"\s+not found', "Missing ConfigMap: '{0}' does not exist."),
    (r'secret\s+"([^"]+)"\s+not found', "Missing Secret: '{0}' does not exist."),
    (r'ErrImageNeverPull', "Image pull policy misconfiguration (ErrImageNeverPull)."),
    (r'ImagePullBackOff', "Image cannot be pulled — check image name/tag/registry access."),
    (r'ErrImagePull', "Image pull failure — check image name/tag/registry access."),
    (r'FailedScheduling.*Insufficient (cpu|memory)', "Pod unschedulable — insufficient {0} on cluster nodes."),
    (r'FailedScheduling.*node\(s\) had taint', "Pod unschedulable — no node tolerates required taints."),
]

def _recovery_plan_for(root_cause: str) -> list[str]:
    """Map a definitive root cause to a concrete recovery plan."""
    rc = root_cause.lower()

    if "missing configmap" in rc:
        return [
            "Identify the correct ConfigMap manifest for this workload (check git history or Helm chart).",
            "Recreate the ConfigMap in the correct namespace: kubectl apply -f <configmap.yaml>",
            "Verify the pod restarts and reaches Running state.",
        ]
    if "missing secret" in rc:
        return [
            "Identify the correct Secret source (vault, sealed-secret, or CI/CD pipeline).",
            "Recreate the Secret in the correct namespace.",
            "Verify the pod restarts and reaches Running state.",
        ]
    if "errimageneverpull" in rc or "image pull policy" in rc:
        return [
            "Confirm the image exists locally on the node, or",
            "Set imagePullPolicy to IfNotPresent/Always and ensure registry access is configured.",
        ]
    if "image cannot be pulled" in rc or "image pull failure" in rc:
        return [
            "Verify the image name/tag is correct in the deployment spec.",
            "Confirm registry credentials (imagePullSecrets) are valid.",
            "Manually pull the image to confirm registry accessibility.",
        ]
    if "unschedulable" in rc and "cpu" in rc.lower():
        return [
            "Check node resource availability (kubectl describe nodes).",
            "Reduce pod resource requests, or scale/add cluster nodes.",
        ]
    if "unschedulable" in rc and "taint" in rc.lower():
        return [
            "Add matching tolerations to the pod spec, or",
            "Schedule on nodes without the conflicting taint.",
        ]

    return ["Manual investigation required — no standard recovery plan matched."]

def detect_definitive_cause(evidence: dict):
    for tool_name, result in evidence.items():
        if not isinstance(result, str):
            continue
        for pattern, template in DEFINITIVE_PATTERNS:
            m = re.search(pattern, result, re.IGNORECASE)
            if m:
                return template.format(*m.groups())
    return None

def investigate(workload: dict, system_prompt: str) -> dict:
    """
    Investigate a single unhealthy Kubernetes workload.

    Args:
        workload:      Dict with keys: pod_name, namespace, status,
                       restart_count, node, owner_kind, owner_name
        system_prompt: The DevDas SRE system prompt string

    Returns:
        A result dict containing:
            workload, root_cause, recovery_plan, reasoning,
            tools_used (list), iterations, duration_seconds, status
    """
    pod_name      = workload["pod_name"]
    namespace     = workload["namespace"]
    status        = workload["status"]
    owner_kind    = workload["owner_kind"]
    owner_name    = workload["owner_name"]
    restart_count = workload["restart_count"]

    # ── Build the workload incident description ────────────────────────────
    incident_description = (
        f"Pod Name      : {pod_name}\n"
        f"Namespace     : {namespace}\n"
        f"Status        : {status}\n"
        f"Restart Count : {restart_count}\n"
        f"Owner         : {owner_kind}/{owner_name}\n"
    )
    evidence: dict = new_evidence()
    deployment_name = resolve_deployment_name(pod_name, namespace) if owner_kind == "ReplicaSet" else owner_name
    evidence["_resolved_deployment_name"] = deployment_name  # add this
    incident_description += f"Deployment    : {deployment_name}\n"

    # ── Per-workload isolated state ────────────────────────────────────────
    used_tools: set = set()

    iteration: int = 0
    repeated_requests: int = 0
    start_time = time.time()    
    repeated_requests: int = 0
    start_time = time.time()


    print(f"\n{'─' * 60}")
    print(f"  Investigating: {pod_name}  [{namespace}]")
    print(f"  Status       : {status}")
    print(f"{'─' * 60}")

    # ── Reasoning loop ─────────────────────────────────────────────────────
    while iteration < MAX_ITERATIONS:
        iteration += 1
        print(f"\n  ── Iteration {iteration} ──")

        # Summary of current investigation state
        investigation_summary = {
            "tools_used": sorted(list(used_tools)),
            "evidence_keys_collected": sorted([
                k for k, v in evidence.items() if v is not None
            ])
        }

        # Build the available tools description (exclude already-used tools)
        remaining_tools = {
            name: meta
            for name, meta in AVAILABLE_TOOLS.items()
            if name not in used_tools
        }
        tools_description = json.dumps(
            {name: meta["description"] for name, meta in remaining_tools.items()},
            indent=2
        )

        # Build the full prompt for this iteration
        prompt = f"""
Workload Under Investigation:

{incident_description}

Collected Evidence:

{json.dumps(evidence, indent=2)}

Investigation Summary:

{json.dumps(investigation_summary, indent=2)}

Remaining Available Tools (unused):

{tools_description}

Based ONLY on the workload description and collected evidence,
decide whether you can reach a confident conclusion.

If yes  → return status: "complete" with root_cause and recovery_plan.
If no   → request EXACTLY ONE tool from the remaining available tools list.
         Include ALL required arguments for that tool.
"""

        # ── Ask the LLM ───────────────────────────────────────────────────
        response_raw = ask_llm(system_prompt, prompt)

        print(f"\n  LLM Response:")
        print("  " + response_raw.replace("\n", "\n  "))

        # ── Parse JSON ────────────────────────────────────────────────────
        try:
            data = json.loads(response_raw)
        except json.JSONDecodeError as e:
            print(f"\n  [WARNING] JSON parse error: {e}. Retrying...")
            evidence["SYSTEM_PARSE_ERROR"] = f"LLM returned invalid JSON: {response_raw[:200]}"
            continue

        # ── Check if investigation is complete ────────────────────────────
        if data.get("status") == "complete":
            duration = round(time.time() - start_time, 1)
            print(f"\n  ✅ Investigation complete in {iteration} iteration(s), {duration}s")

            return {
                "workload": workload,
                "status": "complete",
                "root_cause": data.get("root_cause", "Unknown"),
                "recovery_plan": data.get("recovery_plan", []),
                "reasoning": data.get("reasoning", ""),
                "current_hypotheses": data.get("current_hypotheses", []),
                "tools_used": sorted(list(used_tools)),
                "iterations": iteration,
                "repeated_requests": repeated_requests,
                "duration_seconds": duration,
            }

        # ── Validate next_action ──────────────────────────────────────────
        next_action = data.get("next_action")
        if not next_action:
            evidence["SYSTEM_WARNING"] = "LLM returned need_more_evidence but no next_action."
            continue

        tool = next_action.get("tool", "")
        args = next_action.get("arguments", {})

        # ── Invalid tool name ──────────────────────────────────────────────
        if tool not in AVAILABLE_TOOLS:
            evidence["SYSTEM_ERROR"] = {
                "error": f"'{tool}' is not a valid tool.",
                "valid_tools": list(AVAILABLE_TOOLS.keys())
            }
            print(f"  [WARNING] LLM requested invalid tool: '{tool}'")
            continue

        # ── Tool already used ──────────────────────────────────────────────
        if tool in used_tools:
            repeated_requests += 1
            remaining = [t for t in AVAILABLE_TOOLS if t not in used_tools]

            if not remaining:
                # All tools exhausted — force a final answer
                print("\n  [INFO] All tools exhausted. Requesting forced final diagnosis.")
                return _force_final_diagnosis(
                    system_prompt, incident_description, evidence,
                    used_tools, iteration, repeated_requests, start_time, workload
                )

            evidence["SYSTEM_WARNING"] = {
                "warning": f"Tool '{tool}' was already used. Please pick a different tool.",
                "remaining_tools": remaining
            }
            print(f"  [WARNING] Tool '{tool}' already used. Nudging LLM.")
            continue
        # ---------------------------------------------------------------
        # Execute the selected tool
        # ---------------------------------------------------------------

        print(f"\n  Running Tool -> {tool}")

        try:
            result = execute_tool(tool, args, evidence)

        except Exception as e:
            evidence["SYSTEM_ERROR"] = {
                "error": str(e),
                "tool": tool,
            }
            print(f"\n  [ERROR] Tool execution failed: {e}")
            continue

        used_tools.add(tool)

        preview = result

        if isinstance(preview, str) and len(preview) > 1200:
            preview = preview[:1200] + "\n\n... (truncated)"

        print("\n  Tool Result:")
        print("  " + str(preview).replace("\n", "\n  "))

        evidence[tool] = result

        definitive = detect_definitive_cause(evidence)
        if definitive:
            duration = round(time.time() - start_time, 1)
            return {
                "workload": workload,
                "status": "complete",
                "root_cause": definitive,
                "recovery_plan": _recovery_plan_for(definitive),  # small lookup table, see below
                "reasoning": "Definitive Kubernetes evidence matched a known failure signature; no further investigation needed.",
                "current_hypotheses": [definitive],
                "tools_used": sorted(list(used_tools)),
                "iterations": iteration,
                "repeated_requests": repeated_requests,
                "duration_seconds": duration,
            }



def _force_final_diagnosis(
    system_prompt, incident_description, evidence,
    used_tools, iteration, repeated_requests, start_time, workload
) -> dict:
    """
    Force the LLM to produce a final diagnosis when tools are exhausted
    or max iterations are reached.
    """
    final_prompt = f"""
Workload Under Investigation:

{incident_description}

Collected Evidence:

{json.dumps(evidence, indent=2)}

All available tools have been exhausted or max iterations reached.
You MUST return status: "complete" now.
Produce the best possible diagnosis from the evidence you have.
Do not request any more tools.
"""
    response_raw = ask_llm(system_prompt, final_prompt)

    try:
        data = json.loads(response_raw)
    except json.JSONDecodeError:
        data = {
            "root_cause": "Unable to determine — LLM returned invalid JSON.",
            "recovery_plan": ["Manual investigation required."],
            "reasoning": response_raw[:500],
        }

    duration = round(time.time() - start_time, 1)

    return {
        "workload": workload,
        "status": "complete_forced",
        "root_cause": data.get("root_cause", "Unknown"),
        "recovery_plan": data.get("recovery_plan", []),
        "reasoning": data.get("reasoning", ""),
        "current_hypotheses": data.get("current_hypotheses", []),
        "tools_used": sorted(list(used_tools)),
        "iterations": iteration,
        "repeated_requests": repeated_requests,
        "duration_seconds": duration,
    }