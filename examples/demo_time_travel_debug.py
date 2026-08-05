"""
Demo: Time Travel Debugging with NEXUS
Shows how NEXUS can trace backward through causality to find root causes
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from nexus.core.orchestrator import Orchestrator
from nexus.core.config import NexusConfig
from nexus.graph import NodeType, EdgeType


async def simulate_development_timeline():
    """
    Simulate a realistic development timeline with a bug introduced
    """
    # Initialize NEXUS
    config = NexusConfig(project_root=Path.cwd())
    orchestrator = Orchestrator(config)
    await orchestrator.initialize()

    print("=" * 70)
    print("DEMO: Time Travel Debugging")
    print("=" * 70)
    print("\nSimulating development timeline...\n")

    # Create a timeline of events
    base_time = datetime.now() - timedelta(hours=3)

    # Event 1: Developer updates config (3 hours ago)
    print(f"[{base_time.strftime('%H:%M:%S')}] Developer updates API timeout config")
    config_change_id = await orchestrator.record_event(
        NodeType.CONFIG_CHANGE,
        "Updated API timeout from 30s to 5s",
        data={
            "file": "config/api.yaml",
            "old_value": "30s",
            "new_value": "5s",
        },
    )

    # Event 2: Code commit (2.5 hours ago)
    commit_time = base_time + timedelta(minutes=30)
    print(f"[{commit_time.strftime('%H:%M:%S')}] Git commit with config changes")
    commit_id = await orchestrator.record_event(
        NodeType.GIT_COMMIT,
        "feat: reduce API timeout for faster responses",
        data={
            "commit_hash": "abc123",
            "files_changed": ["config/api.yaml"],
        },
    )
    await orchestrator.link_events(config_change_id, commit_id, EdgeType.TRIGGERS)

    # Event 3: Deployment (2 hours ago)
    deploy_time = base_time + timedelta(hours=1)
    print(f"[{deploy_time.strftime('%H:%M:%S')}] Deploy to production")
    deploy_id = await orchestrator.record_event(
        NodeType.BUILD_EVENT,
        "Production deployment",
        data={"environment": "production"},
    )
    await orchestrator.link_events(commit_id, deploy_id, EdgeType.TRIGGERS)

    # Event 4: Tests start failing (1.5 hours ago)
    test_fail_time = base_time + timedelta(hours=1, minutes=30)
    print(f"[{test_fail_time.strftime('%H:%M:%S')}] Tests start failing")
    test_fail_id = await orchestrator.record_event(
        NodeType.TEST_FAILURE,
        "Integration tests timing out",
        data={
            "test_suite": "integration",
            "failures": 12,
            "error": "TimeoutError: Request exceeded 5s",
        },
    )
    await orchestrator.link_events(deploy_id, test_fail_id, EdgeType.CAUSES)

    # Event 5: User reports issue (now)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] User reports: API requests failing\n")

    # Now use NEXUS to debug
    print("\n" + "=" * 70)
    print("Running NEXUS Time Travel Debug...")
    print("=" * 70 + "\n")

    result = await orchestrator.debug_problem(
        "API integration tests are timing out with 'Request exceeded 5s' errors"
    )

    # Display the causal chain
    print("\n🕐 CAUSAL CHAIN DISCOVERED:")
    print("-" * 70)

    if result.get("temporal_analysis"):
        ta = result["temporal_analysis"]
        print(f"\nRoot causes found: {ta.get('root_causes_found', 0)}")

        if ta.get("root_cause_nodes"):
            print("\n🎯 ROOT CAUSE:")
            for rc in ta["root_cause_nodes"]:
                print(f"  - {rc['type']}: {rc['data'].get('description')}")
                print(f"    Time: {rc['timestamp']}")
                if rc['data'].get('old_value'):
                    print(f"    Changed from: {rc['data']['old_value']} → {rc['data']['new_value']}")

        print(f"\n📊 LLM Analysis:")
        print(ta.get("llm_analysis", "N/A"))

    if result.get("fix_simulations"):
        print("\n\n🔧 SIMULATED FIX STRATEGIES:")
        print("-" * 70)
        for i, sim in enumerate(result["fix_simulations"]["simulations"][:3], 1):
            print(f"\n{i}. {sim['fix_description']}")
            print(f"   Confidence: {sim['confidence_score']:.0%}")
            print(f"   Risk: {sim['risk_level']}")
            print(f"   Blast radius: {sim['blast_radius']} components")

    print("\n\n" + "=" * 70)
    print("Demo complete!")
    print("=" * 70)

    # Performance metrics
    perf = result.get("performance", {})
    print(f"\n⚡ Performance:")
    print(f"  Temporal Analysis: {perf.get('temporal_latency_ms', 0):.0f}ms")
    print(f"  Code Analysis: {perf.get('code_latency_ms', 0):.0f}ms")
    print(f"  Fix Simulation: {perf.get('simulation_latency_ms', 0):.0f}ms")
    print(f"  Total: {perf.get('total_latency_ms', 0):.0f}ms")

    # Graph stats
    print(f"\n📈 Causal Graph Stats:")
    stats = orchestrator.get_graph_stats()
    print(f"  Total nodes: {stats['total_nodes']}")
    print(f"  Total edges: {stats['total_edges']}")

    await orchestrator.shutdown()


if __name__ == "__main__":
    print("\n🚀 NEXUS - Causal Reality Agent Swarm")
    print("Demo: Time Travel Debugging\n")

    asyncio.run(simulate_development_timeline())
