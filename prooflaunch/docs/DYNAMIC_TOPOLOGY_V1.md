# Dynamic Topology V1

Dynamic Topology V1 replaces fixed persona group chat with a bounded capability graph. It does not claim that more agents are better, that an online model was called, or that the dynamic arm beat fixed or single-agent controls.

## Capability policy

The frozen catalog contains twelve capabilities: Evidence, Audience, Competition, Strategy, Creative, Copy, Art, Channel, Production, Compliance, Experiment, and Critic. Each defines typed inputs, typed outputs, permitted tools, least-privilege permissions, and a three-action ceiling. Capability workers cannot publish, send, or approve release.

One Supervisor owns authoritative state. A separate human node alone can approve or reject release. Workers are activated by required capability and task entropy. Risk adds Compliance and Critic. Conflicts add a bounded Arbiter. Non-mandatory workers with expected value below 0.10 are removed.

Research uses width search, production uses depth search, and repair uses feedback search. These are explicit controller modes, not conversational prompts.

## Shared state without shared thought

Workers exchange approved, source-hashed facts through a scoped blackboard. Each fact lists visible nodes. Unapproved facts stay isolated. `chain_of_thought`, `hidden_reasoning`, and `private_scratchpad` are invalid blackboard keys. Outputs contain typed payloads, evidence hashes, and uncertainty, never implicit reasoning.

Dependency, conflict, and failure-propagation edges are separate. Dependencies must remain acyclic. Topology mutation is revisioned and parent-hash-bound; rollback creates a new revision and preserves its event trail.

Hard ceilings are three parallel workers, eight interaction rounds, 16,000 tokens, and twenty tool calls. Confidence below 0.40 or action risk at least 0.80 triggers escalation. Duplicate opinions retain the higher-utility instance, while observations are ranked by relevance × freshness and admitted only when approved and inside the token budget. Structural entropy exposes collapsed versus balanced work allocation.

## Evaluation boundary

The matched evaluation has exactly three arms: dynamic topology, fixed six-agent, and single agent. All arms must contain the identical task set. It reports success, tokens, tool calls, latency, and communication events without a weighted composite. The bundled values are explicitly synthetic formula fixtures. Live Agent execution and any superiority claim remain null in the frozen contract.

## Artifacts

- `src/prooflaunch_remix/v10_dynamic_topology.py`
- `tests/test_v10_dynamic_topology.py`
- `config/cortex_x_v10_dynamic_topology_v1.json`
- `evidence/v10/dynamic-topology-v1-mechanical-fixture.json`
