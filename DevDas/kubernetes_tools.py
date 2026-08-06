"""
kubernetes_tools.py

Generic kubectl tool library.

Every function uses subprocess.run() to execute real kubectl commands
against a real Kubernetes cluster. Nothing is mocked or simulated.

All functions are generic — no application names are hardcoded.
The LLM decides which pod / deployment / namespace to query.
"""

import subprocess
import json
import re


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _kubectl(*args, timeout: int = 30) -> str:
    """
    Run a kubectl command and return stdout as a string.
    On error, return the stderr output so the LLM can reason about it.
    """
    cmd = ["kubectl"] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if result.returncode != 0 and result.stderr.strip():
        return f"[kubectl error]\n{result.stderr.strip()}"
    return result.stdout.strip() if result.stdout.strip() else "[no output]"


def _kubectl_json(*args, timeout: int = 30):
    """
    Run a kubectl command with -o json and return parsed dict.
    Returns None on failure.
    """
    cmd = ["kubectl"] + list(args) + ["-o", "json"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if result.returncode != 0:
        print("COMMAND:", " ".join(cmd))
        print("STDERR:", result.stderr)
        print("STDOUT:", result.stdout)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

def resolve_deployment_name(pod_name: str, namespace: str) -> str | None:
    """Walk Pod -> ReplicaSet -> Deployment to find the real deployment name."""
    pod = _kubectl_json("get", "pod", pod_name, "-n", namespace)
    if not pod:
        return None

    for ref in pod.get("metadata", {}).get("ownerReferences", []):
        if ref.get("kind") == "ReplicaSet":
            rs = _kubectl_json("get", "replicaset", ref["name"], "-n", namespace)
            if rs:
                for rs_ref in rs.get("metadata", {}).get("ownerReferences", []):
                    if rs_ref.get("kind") == "Deployment":
                        return rs_ref["name"]

    return None


# ---------------------------------------------------------------------------
# Discovery (pure Python — no LLM involved)
# ---------------------------------------------------------------------------

# Statuses that are definitely unhealthy
UNHEALTHY_PHASES = {"Failed", "Unknown", "Pending"}

# Container-level waiting reasons that indicate a problem
UNHEALTHY_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "OOMKilled",
    "Error",
    "CreateContainerConfigError",
    "InvalidImageName",
    "RunContainerError",
    "ContainerCannotRun",
    "DeadlineExceeded",
}

# Namespaces to skip (system noise)
SKIP_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}

# Restart threshold — pod is flagged even if Running
HIGH_RESTART_THRESHOLD = 5


def discover_unhealthy_workloads(namespace: str = "--all-namespaces") -> list[dict]:
    """
    Discover all unhealthy pods in the cluster without LLM involvement.

    Returns a list of workload dicts:
    [
        {
            "pod_name": "payment-abc123",
            "namespace": "devdas",
            "status": "CrashLoopBackOff",
            "restart_count": 17,
            "node": "kind-worker",
            "owner_kind": "Deployment",
            "owner_name": "payment-service"
        },
        ...
    ]
    """
    args = ["get", "pods"]
    if namespace == "--all-namespaces":
        args.append("--all-namespaces")
    else:
        args += ["-n", namespace]

    data = _kubectl_json(*args)
    if data is None:
        print("[DevDas] WARNING: Could not retrieve pod list from cluster.")
        return ([],0)

    unhealthy = []
    total_pods = 0

    for pod in data.get("items", []):
        meta = pod.get("metadata", {})
        pod_name = meta.get("name", "unknown")
        pod_namespace = meta.get("namespace", "default")

        # Skip system namespaces
        if pod_namespace in SKIP_NAMESPACES:
            continue

        total_pods += 1
        spec = pod.get("spec", {})
        status = pod.get("status", {})
        phase = status.get("phase", "Unknown")

        # Determine owning controller
        owner_kind = "None"
        owner_name = "None"
        for ref in meta.get("ownerReferences", []):
            owner_kind = ref.get("kind", "None")
            owner_name = ref.get("name", "None")
            break

        # Check container statuses
        problem_reason = None
        restart_count = 0

        container_statuses = status.get("containerStatuses", []) + \
                             status.get("initContainerStatuses", [])

        for cs in container_statuses:
            restart_count = max(restart_count, cs.get("restartCount", 0))
            state = cs.get("state", {})

            waiting = state.get("waiting", {})
            if waiting:
                reason = waiting.get("reason", "")
                if reason in UNHEALTHY_REASONS:
                    problem_reason = reason
                    break

            terminated = state.get("terminated", {})
            if terminated:
                reason = terminated.get("reason", "")
                if reason in {"OOMKilled", "Error", "ContainerCannotRun"}:
                    problem_reason = reason
                    break

        # Flag pod as unhealthy
        is_unhealthy = False

        if problem_reason:
            is_unhealthy = True
            final_status = problem_reason
        elif phase in UNHEALTHY_PHASES:
            is_unhealthy = True
            final_status = f"Phase:{phase}"
        elif restart_count >= HIGH_RESTART_THRESHOLD:
            is_unhealthy = True
            final_status = f"HighRestarts({restart_count})"
        else:
            final_status = phase  # e.g. Running

        if is_unhealthy:
            node_name = spec.get("nodeName", "unknown")
            unhealthy.append({
                "pod_name": pod_name,
                "namespace": pod_namespace,
                "status": final_status,
                "restart_count": restart_count,
                "node": node_name,
                "owner_kind": owner_kind,
                "owner_name": owner_name,
            })

    return unhealthy, total_pods


def get_all_pods(namespace: str = "--all-namespaces") -> str:
    """Return a human-readable pod listing across the cluster."""
    args = ["get", "pods", "-o", "wide"]
    if namespace == "--all-namespaces":
        args.append("--all-namespaces")
    else:
        args += ["-n", namespace]
    return _kubectl(*args)


# ---------------------------------------------------------------------------
# Pod-level tools
# ---------------------------------------------------------------------------

def get_pod_logs(pod_name: str, namespace: str, tail: int = 100,
                 previous: bool = False) -> str:
    """
    Fetch logs from a pod.
    Use previous=True to get logs from the previously crashed container.
    """
    args = ["logs", pod_name, "-n", namespace, f"--tail={tail}"]
    if previous:
        args.append("--previous")
    output = _kubectl(*args)

    # Also try previous if current logs are empty
    if output in ("[no output]", "") and not previous:
        prev_output = _kubectl(*args + ["--previous"])
        if prev_output not in ("[no output]", ""):
            output = f"[Previous container logs]\n{prev_output}"

    return output


def get_pod_events(pod_name: str, namespace: str) -> str:
    """Fetch Kubernetes events for a specific pod."""
    return _kubectl(
        "get", "events",
        "-n", namespace,
        "--field-selector", f"involvedObject.name={pod_name}",
        "--sort-by=.lastTimestamp"
    )


def describe_pod(pod_name: str, namespace: str) -> dict:
    """Return a structured dict with key pod details.

    The raw ``kubectl describe pod`` output is noisy. We instead query the
    pod as JSON and extract the most relevant fields for SRE reasoning.
    The returned dict mirrors the example in the design spec.
    """
    data = _kubectl_json("get", "pod", pod_name, "-n", namespace)
    if data is None:
        return {"error": f"Pod {pod_name} not found in {namespace}"}

    status = data.get("status", {})
    spec = data.get("spec", {})
    container_statuses = status.get("containerStatuses", []) + status.get("initContainerStatuses", [])
    # Pick first container for simplicity – most pods have a single container.
    container_state = "Unknown"
    restart_count = 0
    if container_statuses:
        cs = container_statuses[0]
        restart_count = cs.get("restartCount", 0)
        state = cs.get("state", {})
        if "waiting" in state:
            container_state = state["waiting"].get("reason", "Waiting")
        elif "running" in state:
            container_state = "Running"
        elif "terminated" in state:
            container_state = state["terminated"].get("reason", "Terminated")

    return {
        "phase": status.get("phase", "Unknown"),
        "reason": status.get("reason", ""),
        "containerState": container_state,
        "restartCount": restart_count,
        "node": spec.get("nodeName", ""),
        "image": spec.get("containers", [{}])[0].get("image", ""),
        "imagePullPolicy": spec.get("containers", [{}])[0].get("imagePullPolicy", ""),
    }


# ---------------------------------------------------------------------------
# Deployment-level tools
# ---------------------------------------------------------------------------

def describe_deployment(deployment_name: str, namespace: str) -> dict:
    """Return a structured dict with deployment diagnostics.

    The function extracts the most relevant fields for SRE troubleshooting:
    - image and imagePullPolicy of the primary container
    - referenced ConfigMaps and Secrets (via envFrom / env)
    - associated Services (by selector match – simplified to same name prefix)
    - replica counts
    """
    data = _kubectl_json("get", "deployment", deployment_name, "-n", namespace)
    if data is None:
        return {"error": f"Deployment {deployment_name} not found in {namespace}"}

    spec = data.get("spec", {})
    template = spec.get("template", {})
    pod_spec = template.get("spec", {})
    containers = pod_spec.get("containers", [])
    primary = containers[0] if containers else {}

    # Extract envFrom ConfigMaps/Secrets and env references
    configmaps = set()
    secrets = set()
    for env_from in primary.get("envFrom", []):
        if "configMapRef" in env_from:
            configmaps.add(env_from["configMapRef"].get("name", ""))
        if "secretRef" in env_from:
            secrets.add(env_from["secretRef"].get("name", ""))
    for env in primary.get("env", []):
        if "valueFrom" in env:
            vf = env["valueFrom"]
            if "configMapKeyRef" in vf:
                configmaps.add(vf["configMapKeyRef"].get("name", ""))
            if "secretKeyRef" in vf:
                secrets.add(vf["secretKeyRef"].get("name", ""))

    # Simplified service discovery: list services in same namespace and include those whose selector matches labels
    services = []
    svc_json = _kubectl_json("get", "svc", "-n", namespace)
    if svc_json:
        for svc in svc_json.get("items", []):
            selector = svc.get("spec", {}).get("selector", {})
            # If selector is subset of pod labels, consider related
            pod_labels = template.get("metadata", {}).get("labels", {})
            if selector and all(pod_labels.get(k) == v for k, v in selector.items()):
                services.append(svc.get("metadata", {}).get("name", ""))

    return {
        "deployment": deployment_name,
        "image": primary.get("image", ""),
        "imagePullPolicy": primary.get("imagePullPolicy", ""),
        "configmaps": sorted(list(configmaps)),
        "secrets": sorted(list(secrets)),
        "services": sorted(services),
        "replicas": spec.get("replicas", 0),
        "readyReplicas": data.get("status", {}).get("readyReplicas", 0),
    }


def get_deployment_yaml(deployment_name: str, namespace: str) -> str:
    """Get the raw YAML spec of a deployment for deep inspection."""
    return _kubectl("get", "deployment", deployment_name, "-n", namespace, "-o", "yaml")


def get_replicaset_status(namespace: str) -> str:
    """List all ReplicaSets in a namespace to identify rollout issues."""
    return _kubectl("get", "replicasets", "-n", namespace, "-o", "wide")


# ---------------------------------------------------------------------------
# Service & networking tools
# ---------------------------------------------------------------------------

def describe_service(service_name: str, namespace: str) -> str:
    """Describe a Kubernetes service — endpoints, selector, ports."""
    return _kubectl("describe", "service", service_name, "-n", namespace)


def get_endpoints(service_name: str, namespace: str) -> str:
    """Get endpoints for a service — useful for diagnosing connectivity issues."""
    return _kubectl("get", "endpoints", service_name, "-n", namespace, "-o", "wide")


# ---------------------------------------------------------------------------
# Configuration tools
# ---------------------------------------------------------------------------

def get_configmap(configmap_name: str, namespace: str) -> str:
    """
    Fetch a ConfigMap's data.
    Missing or null values are preserved as-is so the LLM can identify them.
    """
    return _kubectl("get", "configmap", configmap_name, "-n", namespace, "-o", "yaml")


def get_secret(secret_name: str, namespace: str) -> str:
    """
    Fetch a Secret — shows key NAMES only, values are redacted.
    This prevents credential leakage in logs or LLM context.
    """
    data = _kubectl_json("get", "secret", secret_name, "-n", namespace)
    if data is None:
        return f"[kubectl error] Secret '{secret_name}' not found in namespace '{namespace}'"

    secret_data = data.get("data", {})
    redacted = {k: "***REDACTED***" for k in secret_data}

    return (
        f"Secret: {secret_name}\n"
        f"Namespace: {namespace}\n"
        f"Keys present: {list(redacted.keys())}\n"
        f"(Values redacted for security)"
    )


# ---------------------------------------------------------------------------
# Node tools
# ---------------------------------------------------------------------------

def get_nodes() -> str:
    """List all cluster nodes with their status and roles."""
    return _kubectl("get", "nodes", "-o", "wide")


def describe_node(node_name: str) -> str:
    """Describe a node — useful for resource pressure, taint, and condition issues."""
    return _kubectl("describe", "node", node_name)


# ---------------------------------------------------------------------------
# Namespace & cluster-wide tools
# ---------------------------------------------------------------------------

def get_namespace_resources(namespace: str) -> str:
    """List all resources in a namespace — deployments, services, configmaps, etc."""
    return _kubectl("get", "all", "-n", namespace)


def get_persistent_volume_claims(namespace: str) -> str:
    """List PVCs in a namespace — useful for storage-related failures."""
    return _kubectl("get", "pvc", "-n", namespace, "-o", "wide")


def get_resource_quota(namespace: str) -> str:
    """Check resource quotas and limits in a namespace."""
    return _kubectl("get", "resourcequota", "-n", namespace)


def get_horizontal_pod_autoscaler(namespace: str) -> str:
    """Check HPA status — useful for scaling-related investigations."""
    return _kubectl("get", "hpa", "-n", namespace)