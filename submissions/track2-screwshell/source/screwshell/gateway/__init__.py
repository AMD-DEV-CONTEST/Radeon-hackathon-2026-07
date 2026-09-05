"""ScrewShell relay layer (Layer 2 / Phase 0).

The relay is the single OpenAI-compatible entry point in front of one
llama.cpp server. It decides the LoRA expert per request and hands off to
``core.inference_coordinator.InferenceCoordinator``, which serializes the
global LoRA switch so several frontends can share one server without
corrupting each other's expert state.
"""
