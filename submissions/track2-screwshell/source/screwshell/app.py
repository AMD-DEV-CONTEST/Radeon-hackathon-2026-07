"""Composition root: wire MoL engine + router + RAG + tools + memory + safety."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from screwshell.core.orchestrator import Orchestrator
from screwshell.core.router import SkillRouter
from screwshell.core.lora_scan import discover_adapters
from screwshell.memory.stores import ArtifactStore, EvidenceStore, SessionMemory
from screwshell.safety.permissions import AuditLog, PermissionGate
from screwshell.tools.toolkit import Toolkit

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


@dataclass
class AppContext:
    engine: object  # MoLEngine (peft) or MoLLlamaCpp (llamacpp); both share the 5-method contract
    router: SkillRouter
    toolkit: Toolkit
    orchestrator: Orchestrator
    gate: PermissionGate
    evidence: EvidenceStore
    memory: SessionMemory
    rag: object | None = None


def build_app(workspace: str, base: str = "/models/unsloth/Qwen3.5-9B",
              lora_dir: str = "/persistent/loras", build_rag: bool = True,
              adapters: dict[str, str] | None = None,
              mol_backend: str | None = None,
              l3_mode: str | None = None,
              launch_cmd: str | None = None,
              takeover: bool = False) -> AppContext:
    os.makedirs(workspace, exist_ok=True)
    state_dir = os.path.join(workspace, ".screwshell")
    os.makedirs(state_dir, exist_ok=True)

    # --- safety first ---
    audit = AuditLog(os.path.join(state_dir, "audit.jsonl"))
    gate = PermissionGate(workspace, Toolkit.CORE_TOOLS, audit)

    # --- MoL inference core (backend switch: peft default, llamacpp opt-in) ---
    # MOL_BACKEND=llamacpp selects the llama.cpp server backend (path D).
    # Anything else (or unset) keeps the existing peft backend -> zero-risk fallback.
    backend = mol_backend or os.getenv("MOL_BACKEND", "peft")
    if backend == "llamacpp":
        from screwshell.core.mol_engine_llamacpp import MoLLlamaCpp
        server_url = os.getenv("MOL_LLAMACPP_URL", "http://127.0.0.1:8080")
        relay_mode = os.getenv("MOL_RELAY_MODE", "").lower() in (
            "1", "true", "yes", "on")
        engine = MoLLlamaCpp(base, server_url=server_url,
                             relay_mode=relay_mode).load_base()
        logging.info("MoL backend=llamacpp (server=%s, relay_mode=%s)",
                     server_url, relay_mode)
    else:
        # peft backend (default): lazy import keeps torch out of the process for
        # the llamacpp/HTTP backend, so a local UI box can run torch-free.
        from screwshell.core.mol_engine import MoLEngine
        engine = MoLEngine(base).load_base()

    # Adapter discovery (shared by both backends).
    # - peft backend       : register every adapter FOLDER under lora_dir (peft
    #   loads the folder directly).
    # - llama.cpp backend  (tight mode): the orchestrator restarts the server
    #   with ONE --lora at a time, so it needs the LOCAL .gguf path per adapter
    #   NAME to substitute into the launch template. The server's /lora-adapters
    #   ids are therefore NOT used; we resolve the gguf ourselves and skip
    #   non-gguf adapters (e.g. peft-format safetensors loras). Forbidden experts
    #   (hermes_s2/fable5, TRUTH §6) are skipped inside discover_adapters via an
    #   ANCHORED match (router.is_forbidden) — a stale on-disk copy can never load
    #   even though DEFAULT_SKILL_MAP also excludes them. On-disk folders are
    #   registered under their logical name (router.EXPERT_NAME_ALIASES) so a
    #   renamed expert keeps working without touching the remote directory.
    #   See screwshell.core.lora_scan.discover_adapters.
    if adapters is None:
        adapters = discover_adapters(lora_dir, backend)
    for name, path in adapters.items():
        try:
            engine.load_adapter(name, path)
        except Exception as e:
            logging.warning("adapter %s failed to load: %s", name, e)
    router = SkillRouter()
    # keep only adapters that actually loaded
    for skill, ad in list(router.skill_map.items()):
        if ad is not None and ad not in engine.adapters:
            router.skill_map[skill] = None  # graceful degrade to base

    # --- RAG (local embeddings) ---
    rag_index = None
    rag_fn = None
    if build_rag:
        try:
            from screwshell.rag.pipeline import LocalEmbedder, RagIndex
            embedder = LocalEmbedder()
            rag_index = RagIndex(workspace, embedder=embedder)
            if rag_index.vecs is None:
                stats = rag_index.ingest()
                logging.info("RAG ingest: %s", stats)
            # hybrid recall (dense ∪ BM25) + RRF fusion is now the default
            # (docs/OPENSOURCE_COMPARISON.md §4.1); a cross-encoder reranker
            # can be injected later via `reranker=` — interface ready, no
            # model download required today.
            rag_fn = rag_index.search
            # semantic fallback for the router reuses the SAME embedder
            # (semantic-router pattern; pure-regex behaviour when unset).
            router.set_embedder(embedder.encode)
        except Exception as e:
            logging.warning("RAG unavailable: %s", e)

    # --- L3 runtime governance (opt-in) ---
    # A governor is only constructed when the caller opts into runtime control.
    # * mode "tight" requires a launch_cmd so the orchestrator can restart the
    #   llama-server to swap experts; without it we fall back to "roomy"
    #   (hot-swap), which is also the safe default for the peft backend.
    governor = None
    lifecycle = None
    if l3_mode or launch_cmd:
        from screwshell.autotune.governor import Governor, LlamaServerLifecycle
        mode = l3_mode or ("tight" if launch_cmd else "roomy")
        governor = Governor(mode=mode)
        if launch_cmd:
            port = int(os.getenv("MOL_LLAMACPP_PORT", "8080"))
            lifecycle = LlamaServerLifecycle(launch_cmd, port=port)

    # --- tools / memory / orchestrator ---
    toolkit = Toolkit(gate, workspace, rag_search_fn=rag_fn)
    memory = SessionMemory(state_dir)
    evidence = EvidenceStore(state_dir)
    artifacts = ArtifactStore(state_dir)
    orch = Orchestrator(engine, router, toolkit, memory, evidence, artifacts,
                        governor=governor, lifecycle=lifecycle,
                        launch_cmd=launch_cmd, takeover=takeover,
                        l3_mode=l3_mode)

    audit.record("app_start", workspace=workspace, base=base,
                 adapters=list(engine.adapters), rag=bool(rag_fn))
    return AppContext(engine, router, toolkit, orch, gate, evidence, memory,
                      rag_index)
