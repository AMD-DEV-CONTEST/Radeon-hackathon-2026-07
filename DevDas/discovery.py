"""
discovery.py

Pure Python cluster discovery — no LLM involved.

Responsibility:
    Scan the cluster, detect unhealthy workloads, return them
    as structured dicts so the investigation phase knows what to investigate.
"""

from kubernetes_tools import discover_unhealthy_workloads


def run_discovery(namespace: str = "--all-namespaces") -> tuple[list[dict], int]:
    """
    Scan the cluster and return (unhealthy_workloads, total_pod_count).

    unhealthy_workloads is a list of dicts:
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
    print("\n" + "=" * 60)
    print("  DevDas — Discovery Phase")
    print("=" * 60)
    print(f"  Scanning namespace(s): {namespace}")

    unhealthy, total_pods = discover_unhealthy_workloads(namespace)

    healthy_count = total_pods - len(unhealthy)

    print(f"\n  Total pods scanned  : {total_pods}")
    print(f"  Healthy pods        : {healthy_count}")
    print(f"  Unhealthy pods      : {len(unhealthy)}")

    if unhealthy:
        print("\n  Unhealthy workloads detected:")
        for w in unhealthy:
            print(f"    • [{w['namespace']}] {w['pod_name']}  →  {w['status']}")
    else:
        print("\n  ✅ All pods appear healthy. Nothing to investigate.")

    print("=" * 60)

    return unhealthy, total_pods
