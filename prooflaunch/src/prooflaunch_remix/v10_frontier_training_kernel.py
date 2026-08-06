from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .v10_contracts import V10ContractError, stable_digest
from .v10_frontier_landscape import ProductLane


class KernelLayer(str, Enum):
    TAXONOMY = "taxonomy"
    DATA = "data"
    PRETRAINING = "pretraining"
    POST_TRAINING = "post_training"
    AGENTIC_RL = "agentic_rl"
    RUNTIME = "runtime"
    EVALUATION = "evaluation"


class LifecycleStage(str, Enum):
    DISCOVER = "discover"
    STRATEGIZE = "strategize"
    CREATE = "create"
    ACTIVATE = "activate"
    MEASURE = "measure"
    LEARN = "learn"


@dataclass(frozen=True)
class ResearchMechanism:
    mechanism_id: str
    title: str
    url: str
    layer: KernelLayer
    observable_mechanism: str
    implementation_contract: str
    falsifier: str
    applies_to: frozenset[ProductLane]
    evidence_boundary: str = "method_reference_not_reproduction"

    def __post_init__(self) -> None:
        if not self.mechanism_id.strip() or not self.title.strip():
            raise V10ContractError("research mechanism needs an id and title")
        if not self.url.startswith("https://"):
            raise V10ContractError("research mechanism needs an HTTPS primary source")
        if not self.observable_mechanism.strip() or not self.implementation_contract.strip():
            raise V10ContractError("research mechanism needs observation and implementation")
        if not self.falsifier.strip():
            raise V10ContractError("research mechanism needs a falsifier")
        if not self.applies_to:
            raise V10ContractError("research mechanism must apply to at least one lane")


@dataclass(frozen=True)
class LaneTrainingObjective:
    lane: ProductLane
    lifecycle: tuple[LifecycleStage, ...]
    trainable_outcomes: tuple[str, ...]
    mechanical_gates: tuple[str, ...]
    human_gates: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.lifecycle != tuple(LifecycleStage):
            raise V10ContractError("every lane must cover the same six-stage lifecycle")
        if not self.trainable_outcomes or not self.mechanical_gates or not self.human_gates:
            raise V10ContractError("lane objectives require outcomes and both gate classes")


@dataclass(frozen=True)
class DurableExecutionContract:
    checkpoint_after_every_state_change: bool
    activity_idempotency_keys: bool
    exact_resume_without_success_replay: bool
    bounded_retry_classes: tuple[str, ...]
    no_retry_classes: tuple[str, ...]
    irreversible_action_requires_human: bool
    event_log_hash_chain: bool
    maximum_agent_steps: int

    def __post_init__(self) -> None:
        required = (
            self.checkpoint_after_every_state_change,
            self.activity_idempotency_keys,
            self.exact_resume_without_success_replay,
            self.irreversible_action_requires_human,
            self.event_log_hash_chain,
        )
        if not all(required):
            raise V10ContractError("durable execution safety controls are fail-closed")
        if not self.bounded_retry_classes or not self.no_retry_classes:
            raise V10ContractError("retry and no-retry classes must both be explicit")
        if not 4 <= self.maximum_agent_steps <= 64:
            raise V10ContractError("agent step budget must be bounded")


@dataclass(frozen=True)
class FrontierTrainingKernel:
    as_of: str
    mechanisms: tuple[ResearchMechanism, ...]
    lane_objectives: tuple[LaneTrainingObjective, ...]
    durable_execution: DurableExecutionContract
    failure_modes: tuple[str, ...]
    autonomy_policy: str
    data_policy: str

    def __post_init__(self) -> None:
        ids = [item.mechanism_id for item in self.mechanisms]
        if len(ids) != len(set(ids)):
            raise V10ContractError("research mechanism ids must be unique")
        if set(item.layer for item in self.mechanisms) != set(KernelLayer):
            raise V10ContractError("frontier research must cover every kernel layer")
        if set(item.lane for item in self.lane_objectives) != set(ProductLane):
            raise V10ContractError("training objectives must cover every product lane")
        if len(self.lane_objectives) != len(ProductLane):
            raise V10ContractError("lane training objectives contain duplicates")
        covered_lanes = set().union(*(item.applies_to for item in self.mechanisms))
        if covered_lanes != set(ProductLane):
            raise V10ContractError("research mechanisms must cover every product lane")
        if len(self.failure_modes) < 10 or len(self.failure_modes) != len(set(self.failure_modes)):
            raise V10ContractError("at least ten unique named failure modes are required")
        if "90%" not in self.autonomy_policy:
            raise V10ContractError("autonomy escalation must use an explicit eval threshold")
        if "licensed" not in self.data_policy.lower():
            raise V10ContractError("training data policy must be license-bound")

    def to_dict(self) -> dict:
        return {
            "schema": "ProofLaunchFrontierTrainingKernelV2",
            "as_of": self.as_of,
            "autonomy_policy": self.autonomy_policy,
            "data_policy": self.data_policy,
            "mechanisms": [
                {
                    **asdict(item),
                    "layer": item.layer.value,
                    "applies_to": sorted(lane.value for lane in item.applies_to),
                }
                for item in self.mechanisms
            ],
            "lane_objectives": [
                {
                    "lane": item.lane.value,
                    "lifecycle": [stage.value for stage in item.lifecycle],
                    "trainable_outcomes": list(item.trainable_outcomes),
                    "mechanical_gates": list(item.mechanical_gates),
                    "human_gates": list(item.human_gates),
                }
                for item in self.lane_objectives
            ],
            "durable_execution": asdict(self.durable_execution),
            "failure_modes": list(self.failure_modes),
        }

    @property
    def digest(self) -> str:
        return stable_digest(self.to_dict())


ALL_LANES = frozenset(ProductLane)
CREATIVE_LANES = frozenset(
    {ProductLane.VIDEO, ProductLane.AUDIO, ProductLane.TEXT, ProductLane.AD_ACTIVATION}
)
ANALYTIC_LANES = frozenset(
    {ProductLane.DATA, ProductLane.GEO, ProductLane.SEO, ProductLane.AD_ACTIVATION}
)


def _mechanism(
    mechanism_id: str,
    title: str,
    url: str,
    layer: KernelLayer,
    observation: str,
    contract: str,
    falsifier: str,
    lanes: frozenset[ProductLane] = ALL_LANES,
) -> ResearchMechanism:
    return ResearchMechanism(
        mechanism_id=mechanism_id,
        title=title,
        url=url,
        layer=layer,
        observable_mechanism=observation,
        implementation_contract=contract,
        falsifier=falsifier,
        applies_to=lanes,
    )


def default_frontier_training_kernel() -> FrontierTrainingKernel:
    mechanisms = (
        _mechanism(
            "agentomnia-coordinate",
            "AgentOmnia: Scaling Agentic Models for Full-Scenario Applications",
            "https://arxiv.org/abs/2607.23124",
            KernelLayer.TAXONOMY,
            "one domain-capability-difficulty coordinate spans synthesis, training, evaluation and diagnosis",
            "bind every environment, task, trajectory, verifier, reward and failure to one immutable coordinate",
            "a task, reward or failure record lacks the same coordinate key",
        ),
        _mechanism(
            "toolverse-graph-curriculum",
            "ToolVerse: Unlocking Massive Environments and Long-Horizon Tasks for Agentic Reinforcement Learning",
            "https://arxiv.org/abs/2607.15660",
            KernelLayer.DATA,
            "sanitized tool-dependency graphs unlock executable long-horizon tasks",
            "generate tasks from acyclic executable tool graphs and cap repeated tasks per environment",
            "a generated dependency is cyclic, unavailable, non-replayable or evaluation-contaminated",
        ),
        _mechanism(
            "bagel-interleaved-pretraining",
            "Emerging Properties in Unified Multimodal Pretraining",
            "https://arxiv.org/abs/2505.14683",
            KernelLayer.PRETRAINING,
            "interleaved multimodal understanding and generation share a decoder-only learning substrate",
            "train owned/licensed text-image-video interleaves with understanding, state prediction and generation objectives",
            "generation improves while understanding, evidence grounding or retained modality performance regresses",
            CREATIVE_LANES | ANALYTIC_LANES,
        ),
        _mechanism(
            "seedance-progressive-video-posttrain",
            "Seedance 1.0: Exploring the Boundaries of Video Generation Models",
            "https://arxiv.org/abs/2506.09113",
            KernelLayer.POST_TRAINING,
            "precision captioning, joint text/image-to-video learning and multidimensional video preference optimization",
            "use licensed multi-shot captions, identity-motion-prompt rubrics and staged quality/efficiency distillation",
            "preference improves only one visual metric or breaks identity, motion, editability or narrative continuity",
            frozenset({ProductLane.VIDEO, ProductLane.AD_ACTIVATION}),
        ),
        _mechanism(
            "jova-joint-av",
            "JoVA: Unified Multimodal Learning for Joint Video-Audio Generation",
            "https://arxiv.org/abs/2512.13677",
            KernelLayer.PRETRAINING,
            "joint video-audio attention plus region-focused synchronization supervision",
            "align video/audio tokens on a shared timeline and weight event, mouth and product-reveal regions",
            "audio semantics, event timing, speech synchronization or visual fidelity regresses on held-out clips",
            frozenset({ProductLane.VIDEO, ProductLane.AUDIO, ProductLane.AD_ACTIVATION}),
        ),
        _mechanism(
            "tracer1-anticipatory-planning",
            "Anticipatory Planning for Multimodal AI Agents",
            "https://arxiv.org/abs/2603.16777",
            KernelLayer.AGENTIC_RL,
            "short-horizon trajectory forecasts precede grounded execution refinement",
            "train plan prefixes against future-state consistency, then refine actions with frozen tool feedback",
            "forecasting adds latency without improving executable success, recovery or plan stability",
        ),
        _mechanism(
            "toolverse-turn-aware-credit",
            "ToolVerse Turn-Aware Relative Advantage",
            "https://arxiv.org/abs/2607.15660",
            KernelLayer.AGENTIC_RL,
            "turn-local credit is combined with moderated future-credit propagation",
            "assign reward at action/observation turns and audit false-positive credit against final-only and GRPO baselines",
            "turn credit cannot beat final-only credit on held-out long-horizon tasks or destabilizes optimization",
        ),
        _mechanism(
            "scale-conditioned-agent-rl",
            "Demystifying Reinforcement Learning for Long-Horizon Tool-Using Agents",
            "https://arxiv.org/abs/2603.21972",
            KernelLayer.AGENTIC_RL,
            "reward design, exploration and difficulty mixture depend on model scale and environment stability",
            "run model-size-specific reward ablations, balanced difficulty sweeps and environment-noise controls",
            "the selected recipe does not outperform scale-matched SFT and static-data controls out of domain",
        ),
        _mechanism(
            "event-triggered-specialist-tools",
            "Towards Long-horizon Embodied Agents with Tool-Aligned Vision-Language-Action Models",
            "https://arxiv.org/abs/2605.13119",
            KernelLayer.RUNTIME,
            "bounded specialists expose progress feedback so the supervisor replans on events rather than polling",
            "use typed invocation units, progress events, bounded residual specialists and supervisor-owned state",
            "specialists silently diverge, supervisor state forks or event-driven recovery underperforms bounded polling",
        ),
        _mechanism(
            "agent-trace-evaluation",
            "Demystifying evals for AI agents",
            "https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents",
            KernelLayer.EVALUATION,
            "multi-turn agents require outcome, transcript, tool and environment-state evaluation",
            "combine deterministic assertions, calibrated binary judges and blind human review on sealed traces",
            "judge TPR or TNR is at most 0.80, traces are missing, or eval cases do not reproduce production failures",
        ),
    )

    outcomes = {
        ProductLane.VIDEO: (
            ("brief_to_multishot_storyboard", "identity_locked_editable_4k_master", "semantic_audio_video_sync"),
            ("prompt_and_claim_grounding", "identity_motion_temporal_metrics", "decoded_master_integrity"),
            ("blind_4a_craft_preference", "narrative_coherence", "brand_distinctiveness"),
        ),
        ProductLane.AUDIO: (
            ("sonic_strategy_to_timeline", "voice_music_sfx_consistency", "rights_bound_master"),
            ("loudness_and_clipping", "speaker_and_timbre_consistency", "event_alignment"),
            ("emotion_fit", "memorability", "brand_appropriateness"),
        ),
        ProductLane.TEXT: (
            ("evidence_to_message_system", "brand_voice_transfer", "channel_safe_variants"),
            ("claim_locator_coverage", "schema_and_length_constraints", "citation_resolution"),
            ("strategic_sharpness", "originality", "persuasion_without_overclaim"),
        ),
        ProductLane.DATA: (
            ("question_to_reproducible_analysis", "analysis_to_decision", "artifact_to_audit_trail"),
            ("query_and_code_replay", "numeric_reconciliation", "source_lineage"),
            ("decision_usefulness", "uncertainty_calibration", "executive_clarity"),
        ),
        ProductLane.GEO: (
            ("prompt_universe_to_visibility_map", "citation_gap_to_action", "visibility_to_measured_lift"),
            ("geo_model_region_role_coverage", "citation_verification", "pre_post_holdout_integrity"),
            ("answer_inclusion_quality", "brand_accuracy", "recommendation_utility"),
        ),
        ProductLane.SEO: (
            ("crawl_to_intent_map", "content_gap_to_publish_plan", "organic_lift_to_learning"),
            ("crawl_replay", "canonical_and_schema_validation", "rank_conversion_attribution"),
            ("searcher_value", "topic_authority", "editorial_quality"),
        ),
        ProductLane.EMPLOYEE_AGENT: (
            ("goal_to_durable_workflow", "multi_tool_recovery", "approval_bound_delivery"),
            ("state_transition_replay", "idempotency_and_permission_checks", "stop_retry_handoff_correctness"),
            ("manager_trust", "work_product_quality", "handoff_completeness"),
        ),
        ProductLane.AD_ACTIVATION: (
            ("strategy_to_campaign_build", "creative_to_budgeted_activation", "experiment_to_incrementality"),
            ("platform_schema_validation", "budget_frequency_guardrails", "randomization_and_srm_checks"),
            ("creative_fit", "media_plan_coherence", "incremental_business_value"),
        ),
    }
    lane_objectives = tuple(
        LaneTrainingObjective(
            lane=lane,
            lifecycle=tuple(LifecycleStage),
            trainable_outcomes=outcomes[lane][0],
            mechanical_gates=outcomes[lane][1],
            human_gates=outcomes[lane][2],
        )
        for lane in ProductLane
    )
    return FrontierTrainingKernel(
        as_of="2026-07-31",
        mechanisms=mechanisms,
        lane_objectives=lane_objectives,
        durable_execution=DurableExecutionContract(
            checkpoint_after_every_state_change=True,
            activity_idempotency_keys=True,
            exact_resume_without_success_replay=True,
            bounded_retry_classes=("rate_limit", "provider_5xx", "tool_timeout"),
            no_retry_classes=("permission_denied", "schema_error", "rights_failure"),
            irreversible_action_requires_human=True,
            event_log_hash_chain=True,
            maximum_agent_steps=32,
        ),
        failure_modes=(
            "unsupported_claim",
            "stale_or_unresolvable_source",
            "brand_or_product_identity_drift",
            "audio_video_semantic_or_timing_desynchronization",
            "invalid_tool_selection_or_arguments",
            "hidden_manual_repair",
            "non_terminating_or_overthinking_loop",
            "duplicate_non_idempotent_side_effect",
            "benchmark_or_temporal_contamination",
            "unlicensed_or_opted_out_training_source",
            "irreversible_action_without_approval",
            "observational_metric_presented_as_causal_lift",
        ),
        autonomy_policy=(
            "default to deterministic L2 workflows; escalate a bounded phase to L3 only "
            "after the lower level reaches at least 90% on a sealed representative eval set"
        ),
        data_policy=(
            "derive rubrics and mechanisms from public observations, but train only on owned, "
            "public-domain, permissive, or expressly licensed bytes and visible trajectories"
        ),
    )
