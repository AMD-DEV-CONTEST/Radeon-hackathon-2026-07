"""
tools.py

Tool routing layer.

Responsibilities:
    1. Define AVAILABLE_TOOLS — a dict the LLM uses to understand
       what tools exist and what arguments they accept.
    2. Implement execute_tool() — routes LLM tool requests to real
       kubernetes_tools functions and stores results in the caller's
       per-workload evidence dict.

Architecture:
    LLM response → execute_tool(tool, args, evidence)
                        ↓
                   kubernetes_tools.*()
                        ↓
                   subprocess.run("kubectl ...")
                        ↓
                   evidence[key] = result
"""

from kubernetes_tools import (
    get_pod_logs,
    get_pod_events,
    describe_pod,
    describe_deployment,
    get_deployment_yaml,
    get_replicaset_status,
    describe_service,
    get_endpoints,
    get_configmap,
    get_secret,
    get_nodes,
    describe_node,
    resolve_deployment_name,
    get_namespace_resources,
    get_persistent_volume_claims,
    get_resource_quota,
    get_all_pods,
    get_horizontal_pod_autoscaler,

)


# ---------------------------------------------------------------------------
# AVAILABLE_TOOLS
# Description shown to LLM so it knows what parameters to pass.
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS = {
    "get_pod_logs": {
        "description": "Fetch recent stdout/stderr logs from a pod. "
                       "Use previous=true to get logs from a crashed container.",
        "arguments": {
            "pod_name": "string (required) — exact pod name",
            "namespace": "string (required) — Kubernetes namespace",
            "tail": "integer (optional, default 100) — number of log lines to fetch",
            "previous": "boolean (optional, default false) — fetch previous container logs"
        }
    },
    "get_pod_events": {
        "description": "Fetch Kubernetes events for a specific pod. "
                       "Reveals scheduling failures, image pull errors, OOMKilled, etc.",
        "arguments": {
            "pod_name": "string (required) — exact pod name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "describe_pod": {
        "description": "Return a structured JSON dict with key pod fields (phase, reason, image, imagePullPolicy, node, containerState, restartCount).",
        "arguments": {
            "pod_name": "string (required) — exact pod name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "describe_deployment": {
        "description": "Return a structured JSON dict with deployment diagnostics (image, imagePullPolicy, configmaps, secrets, services, replicas, readyReplicas).",
        "arguments": {
            "deployment_name": "string (required) — deployment name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_deployment_yaml": {
        "description": "Get the full YAML spec of a deployment. "
                       "Useful for inspecting resource limits, env vars, and volume mounts.",
        "arguments": {
            "deployment_name": "string (required) — deployment name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_replicaset_status": {
        "description": "List all ReplicaSets in a namespace. "
                       "Useful for identifying rollout or scaling issues.",
        "arguments": {
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "describe_service": {
        "description": "Describe a Kubernetes service — shows selector, ports, endpoints. "
                       "Use when investigating connectivity or traffic routing issues.",
        "arguments": {
            "service_name": "string (required) — service name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_endpoints": {
        "description": "Get endpoints for a service. "
                       "Use to verify whether pods are correctly registered as endpoints.",
        "arguments": {
            "service_name": "string (required) — service name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_configmap": {
        "description": "Fetch a ConfigMap's data. "
                       "Use when environment variable issues or missing config is suspected.",
        "arguments": {
            "configmap_name": "string (required) — ConfigMap name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_secret": {
        "description": "List a Secret's key names (values are redacted for security). "
                       "Use to verify whether expected secret keys exist.",
        "arguments": {
            "secret_name": "string (required) — Secret name",
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_nodes": {
        "description": "List all cluster nodes with status and roles. "
                       "Use when investigating node-level failures or scheduling issues.",
        "arguments": {}
    },
    "describe_node": {
        "description": "Describe a specific cluster node — taints, conditions, "
                       "resource pressure, and allocated resources.",
        "arguments": {
            "node_name": "string (required) — node name (from get_nodes output)"
        }
    },
    "get_namespace_resources": {
        "description": "List all resources (pods, services, deployments, etc.) "
                       "in a namespace. Use for a broad overview.",
        "arguments": {
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_persistent_volume_claims": {
        "description": "List PVCs in a namespace. "
                       "Use when storage-related failures are suspected.",
        "arguments": {
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_resource_quota": {
        "description": "Check resource quotas and usage in a namespace. "
                       "Use when pods fail to schedule due to resource limits.",
        "arguments": {
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
    "get_all_pods": {
        "description": "List all pods across the cluster (or a namespace) with wide output. "
                       "Use for a broad cluster-wide or namespace-wide pod overview.",
        "arguments": {
            "namespace": "string (optional, default '--all-namespaces') — Kubernetes namespace"
        }
    },
    "get_horizontal_pod_autoscaler": {
        "description": "Check HPA status — current vs desired replicas, metrics. "
                       "Use when autoscaling or replica count anomalies are suspected.",
        "arguments": {
            "namespace": "string (required) — Kubernetes namespace"
        }
    },
}


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, args: dict, evidence: dict) -> str:
    result = _dispatch(tool_name, args)
    evidence[tool_name] = result
    return result


def _dispatch(tool_name: str, args: dict) -> str:
    """Route tool_name to the correct kubernetes_tools function."""

    # ── Pod tools ──────────────────────────────────────────────────────────
    if tool_name == "get_pod_logs":
        return get_pod_logs(
            pod_name=args.get("pod_name", ""),
            namespace=args.get("namespace", "default"),
            tail=int(args.get("tail", 100)),
            previous=bool(args.get("previous", False)),
        )

    elif tool_name == "get_pod_events":
        return get_pod_events(
            pod_name=args.get("pod_name", ""),
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "describe_pod":
        return describe_pod(
            pod_name=args.get("pod_name", ""),
            namespace=args.get("namespace", "default"),
        )

    # ── Deployment tools ───────────────────────────────────────────────────
    elif tool_name == "describe_deployment":
        return describe_deployment(
            deployment_name=(
                args.get("deployment_name")
                or args.get("name")
                or ""
            ),
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_deployment_yaml":
        return get_deployment_yaml(
            deployment_name=(
                args.get("deployment_name")
                or args.get("name")
                or ""
            ),
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_replicaset_status":
        return get_replicaset_status(
            namespace=args.get("namespace", "default"),
        )


    # ── Service tools ──────────────────────────────────────────────────────
    elif tool_name == "describe_service":
        return describe_service(
            service_name=(
                args.get("service_name")
                or args.get("name")
                or ""
            ),
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_endpoints":
        return get_endpoints(
            service_name=(
                args.get("service_name")
                or args.get("name")
                or ""
            ),
            namespace=args.get("namespace", "default"),
        )


    # ── Config tools ───────────────────────────────────────────────────────
    elif tool_name == "get_configmap":
        return get_configmap(
            configmap_name=(
                args.get("configmap_name")
                or args.get("name")
                or ""
            ),
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_secret":
        return get_secret(
            secret_name=(
                args.get("secret_name")
                or args.get("name")
                or ""
            ),
            namespace=args.get("namespace", "default"),
        )


    # ── Node tools ─────────────────────────────────────────────────────────
    elif tool_name == "get_nodes":
        return get_nodes()

    elif tool_name == "describe_node":
        return describe_node(
            node_name=(
                args.get("node_name")
                or args.get("name")
                or ""
            ),
        )

    # ── Namespace / cluster tools ──────────────────────────────────────────
    elif tool_name == "get_namespace_resources":
        return get_namespace_resources(
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_persistent_volume_claims":
        return get_persistent_volume_claims(
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_resource_quota":
        return get_resource_quota(
            namespace=args.get("namespace", "default"),
        )

    elif tool_name == "get_all_pods":
        return get_all_pods(
            namespace=args.get("namespace", "--all-namespaces"),
        )

    elif tool_name == "get_horizontal_pod_autoscaler":
        return get_horizontal_pod_autoscaler(
            namespace=args.get("namespace", "default"),
        )

    else:
        return f"[DevDas error] Unknown tool: '{tool_name}'"