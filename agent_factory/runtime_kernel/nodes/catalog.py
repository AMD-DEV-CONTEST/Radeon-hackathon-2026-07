from __future__ import annotations

NODE_TYPES = {
    "reserved",
    "cognitive",
    "operational",
    "terminal",
    "sub_graph",
}

KERNEL_RESERVED_NODES = {"ingress", "finalize"}

NODE_IMPLEMENTATION_IDS = {
    "ingress",
    "finalize",
    "cognitive.clarify",
    "cognitive.plan",
    "cognitive.route",
    "cognitive.structured",
    "cognitive.intent_gate",
    "cognitive.answer",
    "cognitive.review",
    "operational.tool_call",
    "operational.resource_probe",
    "terminal.commit",
    "terminal.close",
}

INTERRUPT_CAPABLE_IMPLS = {
    "operational.tool_call",
}

SUBGRAPH_SLOT_IMPLS = {
    "cognitive.clarify",
    "cognitive.plan",
    "cognitive.route",
    "cognitive.intent_gate",
    "cognitive.answer",
    "cognitive.review",
    "operational.tool_call",
    "operational.resource_probe",
}
