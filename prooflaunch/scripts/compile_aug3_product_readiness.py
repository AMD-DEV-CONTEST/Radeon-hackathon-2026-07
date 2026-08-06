#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
PROJECT_PYTHON = (
    PROJECT_ROOT / ".venv/bin/python"
    if (PROJECT_ROOT / ".venv/bin/python").is_file()
    else Path(sys.executable)
)
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from prooflaunch_remix.files import atomic_write_bytes
from prooflaunch_remix.gtm_blind_review_service import BlindReviewService
from prooflaunch_remix.gtm_portfolio_blind_review_service import (
    PortfolioBlindReviewService,
)
from prooflaunch_remix.gtm_human_capability_kernel import (
    verify_gtm_human_capability_kernel,
)
from prooflaunch_remix.gtm_platform_craft_review import (
    verify_platform_craft_review_bundle,
)
from prooflaunch_remix.gtm_platform_native_challenger import (
    verify_platform_native_challenger_plan,
    verify_platform_native_receipt,
)
from prooflaunch_remix.gtm_platform_native_publication_audit import (
    verify_platform_native_publication_audit,
)
from prooflaunch_remix.gtm_platform_generation_quality import (
    verify_platform_generation_quality_audit,
)
from prooflaunch_remix.gtm_codex_integrated_campaign import (
    verify_codex_integrated_campaign_portfolio,
)
from prooflaunch_remix.gtm_codex_campaign_work_order import (
    verify_codex_campaign_adaptation_matrix,
)
from prooflaunch_remix.gtm_codex_lighthouse_portfolio import (
    verify_lighthouse_portfolio,
    verify_lighthouse_quality_portfolio,
)
from prooflaunch_remix.campaign_pack_blind_review import (
    CampaignPackBlindReviewService,
)
from prooflaunch_remix.gtm_strategy import (
    BudgetTier,
    BusinessModel,
    Channel,
    IndustryRisk,
    LifecycleStage,
)
from prooflaunch_remix.gtm_strategy_challenger import (
    validate_strategy_challenger_receipt,
)
from prooflaunch_remix.gtm_strategy_portfolio import (
    validate_strategy_portfolio_quality_audit,
    validate_strategy_portfolio_receipt,
)
from prooflaunch_remix.social_collection import connector_registry
from prooflaunch_remix.tool_execution_sandbox import validate_tool_sandbox_receipt
from prooflaunch_remix.v10_submission_production_api import (
    _public_gtm_adaptive_capability_graph,
    _public_signal_pilot,
    load_verified_codex_campaign_adaptation_summary,
    load_verified_codex_lighthouse_portfolio,
    load_verified_synthetic_lifecycle_demo,
)


REQUIRED_PATHS = (
    "src/prooflaunch_remix/v10_submission_runtime.py",
    "src/prooflaunch_remix/v10_submission_production_api.py",
    "src/prooflaunch_remix/v10_submission_store.py",
    "src/prooflaunch_remix/graph_loop_harness.py",
    "src/prooflaunch_remix/comfyui_production.py",
    "src/prooflaunch_remix/comfyui_bindings.py",
    "src/prooflaunch_remix/generative_candidate_batch.py",
    "src/prooflaunch_remix/progressive_multimodal_production.py",
    "src/prooflaunch_remix/gtm_effect_packet.py",
    "src/prooflaunch_remix/gtm_effect_feedback.py",
    "src/prooflaunch_remix/gtm_production_observation_kit.py",
    "src/prooflaunch_remix/gtm_manual_publication_receipt.py",
    "src/prooflaunch_remix/gtm_learning_memory.py",
    "src/prooflaunch_remix/gtm_memory_capsule.py",
    "src/prooflaunch_remix/gtm_signal_intelligence.py",
    "src/prooflaunch_remix/gtm_creative_alpha.py",
    "src/prooflaunch_remix/gtm_market_language.py",
    "src/prooflaunch_remix/gtm_team_capability_os.py",
    "src/prooflaunch_remix/gtm_human_capability_kernel.py",
    "src/prooflaunch_remix/gtm_craft_handoff.py",
    "src/prooflaunch_remix/gtm_platform_native_challenger.py",
    "src/prooflaunch_remix/gtm_platform_generation_quality.py",
    "src/prooflaunch_remix/gtm_codex_integrated_campaign.py",
    "src/prooflaunch_remix/gtm_codex_campaign_work_order.py",
    "src/prooflaunch_remix/gtm_codex_candidate_quality.py",
    "src/prooflaunch_remix/gtm_codex_lighthouse_portfolio.py",
    "src/prooflaunch_remix/gtm_first50_output_review.py",
    "src/prooflaunch_remix/gtm_one_hour_final_plan.py",
    "src/prooflaunch_remix/gtm_platform_native_publication_audit.py",
    "src/prooflaunch_remix/gtm_platform_craft_review.py",
    "src/prooflaunch_remix/gtm_strategy.py",
    "src/prooflaunch_remix/gtm_channel_portfolio.py",
    "src/prooflaunch_remix/gtm_content_calendar.py",
    "src/prooflaunch_remix/gtm_breakout_loop.py",
    "src/prooflaunch_remix/gtm_text_challenger.py",
    "src/prooflaunch_remix/gtm_text_challenger_runner.py",
    "src/prooflaunch_remix/gtm_strategy_challenger.py",
    "src/prooflaunch_remix/gtm_strategy_portfolio.py",
    "src/prooflaunch_remix/gtm_blind_review_service.py",
    "src/prooflaunch_remix/gtm_portfolio_blind_review_service.py",
    "src/prooflaunch_remix/campaign_pack_blind_review.py",
    "src/prooflaunch_remix/gtm_judge_calibration.py",
    "src/prooflaunch_remix/gtm_local_judge_queue.py",
    "src/prooflaunch_remix/agentic_product_readiness.py",
    "src/prooflaunch_remix/gtm_context_quality.py",
    "src/prooflaunch_remix/gtm_last_mile_challenger.py",
    "src/prooflaunch_remix/gtm_last_mile_diagnostic.py",
    "src/prooflaunch_remix/gtm_named_product_baseline.py",
    "src/prooflaunch_remix/gtm_challenger_dossier.py",
    "src/prooflaunch_remix/gtm_named_product_pk.py",
    "src/prooflaunch_remix/gtm_hybrid_quality_control.py",
    "src/prooflaunch_remix/gtm_omnichannel_craft_os.py",
    "src/prooflaunch_remix/gtm_adaptive_capability_graph.py",
    "src/prooflaunch_remix/production_guardrails.py",
    "src/prooflaunch_remix/production_guardrail_eval.py",
    "src/prooflaunch_remix/production_trace_ledger.py",
    "src/prooflaunch_remix/launch_proof_control.py",
    "src/prooflaunch_remix/gtm_multimodal_seed_compiler.py",
    "src/prooflaunch_remix/gtm_production_quality_contract.py",
    "src/prooflaunch_remix/gtm_brief_intelligence.py",
    "src/prooflaunch_remix/gtm_organic_breakout_admission.py",
    "src/prooflaunch_remix/gtm_market_neighborhood.py",
    "src/prooflaunch_remix/gtm_creative_strategy_kernel.py",
    "src/prooflaunch_remix/gtm_editorial_quality.py",
    "src/prooflaunch_remix/gtm_multimodal_director.py",
    "src/prooflaunch_remix/gtm_distribution_operations.py",
    "src/prooflaunch_remix/gtm_revenue_journey.py",
    "src/prooflaunch_remix/gtm_mechanism_abstraction.py",
    "src/prooflaunch_remix/gtm_promotion_governance.py",
    "src/prooflaunch_remix/inference_gateway.py",
    "src/prooflaunch_remix/gtm_revenue_feedback.py",
    "src/prooflaunch_remix/social_collection.py",
    "src/prooflaunch_remix/social_collection_runner.py",
    "src/prooflaunch_remix/gtm_industry_profile.py",
    "src/prooflaunch_remix/local_campaign_pack.py",
    "src/prooflaunch_remix/gtm_lifecycle_closure.py",
    "src/prooflaunch_remix/gtm_omnichannel_activation.py",
    "src/prooflaunch_remix/gtm_unified_offline_review.py",
    "src/prooflaunch_remix/tool_execution_sandbox.py",
    "scripts/export_comfyui_workflow_api.mjs",
    "scripts/seal_official_comfyui_api_exports.py",
    "scripts/verify_comfyui_weight_supply_chain.py",
    "scripts/seal_comfyui_execution_wrappers.py",
    "scripts/validate_comfyui_execution_wrappers.py",
    "scripts/validate_comfyui_wrapper_prompts.py",
    "scripts/compile_comfyui_gpu_handoff.py",
    "scripts/compile_gtm_channel_portfolio_matrix.py",
    "scripts/compile_gtm_distribution_advantage_matrix.py",
    "scripts/compile_gtm_distribution_advantage_research.py",
    "scripts/compile_gtm_effect_alignment_benchmark.py",
    "scripts/compile_gtm_last_mile_quality_benchmark.py",
    "scripts/compile_gtm_production_quality_contract.py",
    "scripts/compile_gtm_first50_output_review.py",
    "scripts/compile_gtm_one_hour_final_plan.py",
    "scripts/compile_gtm_organic_breakout_admissions.py",
    "scripts/compile_gtm_concrete_product_effect_pk_ledger.py",
    "scripts/run_local_gemma3_last_mile_challenger.py",
    "scripts/repair_gtm_last_mile_challenger.py",
    "scripts/compile_gtm_last_mile_internal_review_packet.py",
    "scripts/generate_gtm_audio_pk_candidates.py",
    "scripts/render_gtm_three_beat_video_challenger.py",
    "scripts/compile_gtm_multimodal_review_packets.py",
    "scripts/export_gtm_unified_offline_review_kit.py",
    "scripts/import_gtm_unified_offline_reviews.py",
    "scripts/verify_apple_mlx_runtime.py",
    "scripts/compile_gtm_platform_native_challenger_plans.py",
    "scripts/run_local_gemma3_platform_native_challenger.py",
    "scripts/run_local_gemma3_platform_publication_repairs.py",
    "scripts/compile_gtm_platform_native_publication_audit.py",
    "scripts/compile_gtm_platform_generation_quality_audit.py",
    "scripts/compile_gtm_platform_generation_trace_audit.py",
    "scripts/probe_local_gemma3_platform_generation_quality.py",
    "scripts/compile_gtm_platform_gold_reference.py",
    "scripts/rebind_gtm_platform_receipt.py",
    "scripts/export_gtm_platform_craft_review_kit.py",
    "scripts/import_gtm_platform_craft_reviews.py",
    "scripts/export_gtm_named_product_baseline_capture_kit.py",
    "scripts/import_gtm_named_product_baseline.py",
    "scripts/compile_gtm_named_product_challenger_dossiers.py",
    "scripts/compile_gtm_blocked_challenger_repairs.py",
    "scripts/prepare_gtm_named_product_pk_pair.py",
    "scripts/compile_gtm_named_product_blind_pk.py",
    "scripts/import_gtm_named_product_blind_review.py",
    "scripts/compile_gtm_named_product_pk_portfolio.py",
    "scripts/compile_gtm_hybrid_quality_control.py",
    "scripts/compile_gtm_adaptive_capability_graph_matrix.py",
    "scripts/compile_gtm_industry_profile_matrix.py",
    "scripts/run_gtm_text_challenger.py",
    "scripts/run_gtm_text_challenger_local.py",
    "scripts/run_aug3_gtm_employee_mission.py",
    "scripts/aggregate_gtm_text_blind_reviews.py",
    "scripts/create_blind_review_invitations.py",
    "scripts/compile_gtm_multimodal_seed.py",
    "scripts/train_local_gtm_route_head.mjs",
    "scripts/run_local_gtm_route_head.mjs",
    "scripts/run_local_gtm_generative_baseline.mjs",
    "scripts/run_local_gtm_creative_benchmark.py",
    "scripts/run_local_gemma3_strategy_challenger.py",
    "scripts/run_local_gemma3_strategy_portfolio.py",
    "scripts/run_local_gemma3_text_craft_quality.py",
    "scripts/compile_local_gemma3_strategy_portfolio_quality.py",
    "scripts/compile_local_gtm_creative_effect_audit.py",
    "scripts/compile_local_gtm_portfolio_blind_review.py",
    "scripts/compile_campaign_pack_blind_review.py",
    "scripts/export_campaign_pack_offline_review_kits.py",
    "scripts/compile_gtm_judge_calibration.py",
    "scripts/build_local_gtm_judge_queue.py",
    "scripts/compile_agentic_product_readiness_audit.py",
    "scripts/run_tool_sandbox_proof.py",
    "scripts/tool_sandbox_probe.py",
    "scripts/compile_gtm_context_quality.py",
    "scripts/compile_production_guardrail_eval.py",
    "scripts/compile_production_trace_retention_contract.py",
    "scripts/run_local_agentic_api_soak.py",
    "scripts/serve_v10_submission_api.py",
    "scripts/discover_local_first_model_resources.py",
    "scripts/run_public_signal_gtm_pilot.py",
    "scripts/build_v10_frontier_api_panel.py",
    "scripts/run_v10_frontier_free_api_sprint.py",
    "scripts/compile_v10_free_cloud_execution_plan.py",
    "scripts/seal_local_multimodal_qualification.py",
    "scripts/run_gtm_revenue_memory_demo.py",
    "scripts/render_local_campaign_pack.py",
    "scripts/run_run_bound_multimodal_demo.py",
    "scripts/compile_gtm_lifecycle_closure_matrix.py",
    "config/local-gemma3-zero-budget-strategy-portfolio-v1.json",
    "evidence/v10/local-gemma3-12b-strategy-portfolio-v1.json",
    "evidence/v10/local-gemma3-12b-strategy-portfolio-quality-v1.json",
    "artifacts/aug3-local-first-gtm-employee-mission-v14/gemma3-12b-text-craft-quality.json",
    "web/index.html",
    "web/app.js",
    "web/styles.css",
    "docs/product/GTM_EFFECT_FIRST_EXECUTION_CONTRACT_V1.md",
    "docs/product/GTM_OPEN_SOURCE_CAPABILITY_RADAR_V1.md",
    "docs/product/GTM_CHANNEL_PORTFOLIO_V1.md",
    "docs/product/GTM_DISTRIBUTION_ADVANTAGE_V2.md",
    "docs/product/GTM_TEN_PEER_EFFECT_ALIGNMENT_BENCHMARK_V1.md",
    "docs/product/GTM_LAST_MILE_PRODUCTION_QUALITY_V1.md",
    "docs/product/GTM_CONTENT_CALENDAR_V1.md",
    "docs/product/GTM_BREAKOUT_GROWTH_LOOP_V1.md",
    "docs/product/GTM_TEXT_CREATIVE_CHALLENGER_V1.md",
    "docs/product/GTM_REVENUE_POSITIVE_FEEDBACK_V1.md",
    "docs/product/GTM_PRODUCTION_OBSERVATION_FIELD_KIT_V1.md",
    "docs/product/GTM_MANUAL_PUBLICATION_RECEIPT_V1.md",
    "docs/product/LOCAL_FIRST_TRAINING_AND_FREE_CLOUD_V1.md",
    "docs/product/GTM_INDUSTRY_PROFILE_V1.md",
    "docs/product/GTM_TENANT_ISOLATION_V1.md",
    "docs/product/GTM_TOOL_EXECUTION_SANDBOX_V1.md",
    "docs/product/GTM_CROSS_DEVICE_MEMORY_CAPSULE_V1.md",
    "docs/product/LOCAL_MULTIMODAL_QUALIFICATION_V1.md",
    "docs/product/LOCAL_CAMPAIGN_PACK_V1.md",
    "docs/product/RUN_BOUND_MULTIMODAL_DEMO_V1.md",
    "docs/product/CAMPAIGN_PACK_VISUAL_BLIND_REVIEW_V1.md",
    "docs/product/GTM_LIFECYCLE_CLOSURE_V1.md",
    "docs/product/GTM_CAMPAIGN_WORKSPACE_V1.md",
    "docs/product/GTM_EXECUTIVE_COCKPIT_V1.md",
    "docs/product/GTM_HUMAN_SELECTED_OMNICHANNEL_ACTIVATION_V1.md",
    "docs/product/AGENTIC_PRODUCT_READINESS_AUDIT_V1.md",
    "docs/product/GTM_HUMAN_JUDGE_CALIBRATION_V1.md",
    "docs/product/AUG3_DEMO_RUNBOOK.md",
    "docs/OPEN_SOURCE_SOCIAL_COLLECTION_V1.md",
    "config/comfyui_production_backends_v1.json",
    "config/comfyui_weight_supply_chain_v1.json",
    "config/comfyui_execution_bindings_v1.json",
    "config/gtm_open_source_capability_radar_v1.json",
    "config/gtm_adaptive_oss_skill_candidates_v1.json",
    "config/cortex_x_v10_frontier_api_panel.json",
    "scripts/compile_gtm_market_language_matrix.py",
    "evidence/v10/gtm-market-language-matrix-v1.json",
    "scripts/compile_gtm_team_capability_matrix.py",
    "evidence/v10/gtm-team-capability-matrix-v1.json",
    "scripts/compile_gtm_human_capability_kernel.py",
    "scripts/compile_gtm_codex_integrated_campaign.py",
    "config/codex-integrated-campaign-blueprints-v1.json",
    "evidence/v10/gtm-codex-integrated-campaign-portfolio-v1.json",
    "scripts/compile_gtm_codex_campaign_adaptation_matrix.py",
    "evidence/v10/gtm-codex-campaign-adaptation-matrix-v1.json",
    "scripts/compile_gtm_codex_lighthouse_portfolio.py",
    "config/codex-lighthouse-execution-candidates-v1.json",
    "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json",
    "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json",
    "evidence/v10/gtm-human-capability-kernel-v2.json",
    "docs/product/GTM_HUMAN_CAPABILITY_KERNEL_V2.md",
    "scripts/compile_gtm_craft_handoff_matrix.py",
    "evidence/v10/gtm-craft-handoff-matrix-v1.json",
    ".github/workflows/quality.yml",
    "artifacts/local-gtm-route-head-v1/embedding-cache.json",
    "artifacts/local-gtm-route-head-v3/model.json",
    "artifacts/local-gtm-route-head-v3/metrics.json",
    "artifacts/local-gtm-route-head-v3/split-manifest.json",
    "artifacts/local-gtm-route-head-v3/training-receipt.json",
    "artifacts/local-gtm-generative-baseline-v1/outputs.jsonl",
    "artifacts/local-gtm-generative-baseline-v1/receipt.json",
    "artifacts/local-gtm-creative-benchmark-v5/benchmark-receipt.json",
    "artifacts/local-gtm-creative-benchmark-v11/benchmark-receipt.json",
    "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2/portfolio-blind-review-public.json",
    "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2/portfolio-blind-review-private.json",
    "artifacts/aug3-gtm-employee-mission-v14/mission-receipt.json",
    "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-challenger-execution.json",
    "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-blind-review-public.json",
    "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger/text-creative-blind-review-private.json",
    "artifacts/campaign-pack-visual-blind-review-v1/campaign-pack-blind-review-public.json",
    "artifacts/campaign-pack-visual-blind-review-v1/campaign-pack-blind-review-private.json",
    "artifacts/run-bound-multimodal-demo-v1/demo-receipt.json",
    "artifacts/run-bound-multimodal-demo-v1/audio-execution-receipt.json",
    "artifacts/run-bound-multimodal-demo-v1/video-execution-receipt.json",
    "artifacts/run-bound-multimodal-demo-v1/gtm-cockpit.json",
    "evidence/v10/frontier-api-panel-preflight.json",
    "evidence/v10/frontier-free-api-sprint.json",
    "evidence/v10/local-first-model-resource-discovery.json",
    "evidence/v10/local-gemma3-12b-gtm-strategy-probe.json",
    "evidence/v10/local-gemma3-12b-strategy-challenger-v2.json",
    "evidence/v10/local-gemma3-12b-strategy-challenger-v2.json",
    "evidence/v10/free-cloud-execution-plan-v2.json",
    "evidence/v10/gtm-distribution-advantage-matrix-v2.json",
    "evidence/v10/gtm-distribution-advantage-research-2026-08-02.json",
    "evidence/v10/gtm-ten-peer-effect-alignment-benchmark-v1.json",
    "evidence/v10/gtm-last-mile-production-quality-v1.json",
    "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json",
    "evidence/v10/apple-mlx-runtime-preflight.json",
    "evidence/v10/gtm-platform-native-publication-audit-v2.json",
    "evidence/v10/gtm-platform-gold-reference-quality-audit-v1.json",
    "evidence/v10/gtm-platform-gold-reference-publication-audit-v1.json",
    "config/platform-native-b2b-codex-capability-overlay-v2.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v13/b2b-codex-capability-reference-v2-receipt.json",
    "evidence/v10/gtm-platform-codex-capability-reference-quality-audit-v2.json",
    "config/platform-native-b2c-codex-reference-v1.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json",
    "evidence/v10/gtm-platform-b2c-codex-reference-quality-audit-v1.json",
    "docs/product/GTM_CONCRETE_PRODUCT_EFFECT_PK_LEDGER_V1.md",
    "docs/product/GTM_NAMED_PRODUCT_BASELINE_CAPTURE_V1.md",
    "docs/product/GTM_NAMED_PRODUCT_BLIND_PK_V1.md",
    "docs/product/GTM_HYBRID_QUALITY_CONTROL_V1.md",
    "docs/product/GTM_ADAPTIVE_CAPABILITY_GRAPH_V1.md",
    "docs/product/GTM_UNIFIED_OFFLINE_HUMAN_REVIEW_V2.md",
    "docs/product/GTM_PLATFORM_CRAFT_BLIND_REVIEW_V1.md",
    "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger.json",
    "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger-repaired.json",
    "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3/scope.json",
    "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/audio-candidate-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-restraint-a-48k-stereo-24bit.wav",
    "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-documentary-b-48k-stereo-24bit.wav",
    "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-inquisitive-c-48k-stereo-24bit.wav",
    "artifacts/gtm-last-mile-pk-v1/video-challenger-v5/prooflaunch-three-beat-challenger-4k.mp4",
    "artifacts/gtm-last-mile-pk-v1/video-challenger-v5/video-challenger-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/unified-last-mile-review.json",
    "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/audio/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/audio/scope.json",
    "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/video/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/video/scope.json",
    "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2/export-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2/prooflaunch-unified-offline-review-kit-v2.zip",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2b-plan.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2c-plan.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2b-publication-repaired-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2c-local-gemma3-v1-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/public/platform-craft-review-public.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/public/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/private/platform-craft-review-private.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/export-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/prooflaunch-platform-craft-review-kit-v1.zip",
    "config/platform-native-b2b-gold-reference-v1.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-plan.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2c-plan.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-gold-reference-v1-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2c-rebound-v1-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-gold-v1/public/platform-craft-review-public.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-gold-v1/public/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-gold-v1/private/platform-craft-review-private.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-gold-v1/export-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-gold-v1/prooflaunch-platform-craft-review-kit-v1.zip",
    "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/export-receipt.json",
    "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/prooflaunch-named-product-baseline-capture-kit-v1.zip",
    "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json",
    "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/manifest.json",
    "evidence/v10/named-product-pk-portfolio-v1.json",
    "evidence/v10/gtm-hybrid-quality-control-v1.json",
    "evidence/v10/gtm-adaptive-capability-graph-matrix-v1.json",
    "artifacts/cross-platform-public-signal-pilot-v1/creative-signal-snapshot.json",
    "artifacts/cross-platform-public-signal-pilot-v1/collection-receipt.json",
    "artifacts/public-signal-gtm-pilot-v1/pilot-receipt.json",
    "evidence/v10/local-gtm-creative-benchmark-status.json",
    "evidence/v10/local-gtm-creative-effect-audit-v1.json",
    "evidence/v10/local-gtm-portfolio-blind-review-status.json",
    "evidence/v10/local-judge-calibration-queue-status.json",
    "evidence/v10/agentic-product-readiness-audit.json",
    "evidence/v10/gtm-context-quality-v1.json",
    "evidence/v10/production-guardrail-eval-v1.json",
    "evidence/v10/production-trace-retention-v1.json",
    "evidence/v10/local-agentic-api-soak-v1.json",
    "config/gtm_production_quality_contract_v1.json",
    "config/gtm_platform_copy_bible_v1.json",
    "evidence/v10/gtm-production-quality-current-v1.json",
    "evidence/v10/gtm-organic-breakout-admission-v1.json",
    "docs/product/GTM_PRODUCTION_QUALITY_OPERATING_CONTRACT_V1.md",
    "docs/product/GTM_ORGANIC_BREAKOUT_ADMISSION_V1.md",
    "artifacts/run-bound-multimodal-demo-v1/production-deliverables/brief-intelligence.json",
    "artifacts/run-bound-multimodal-demo-v1/production-deliverables/product-evidence-register.json",
    "evidence/v10/gtm-industry-profile-matrix-v1.json",
    "evidence/v10/local-multimodal-qualification.json",
    "evidence/v10/local-campaign-pack-v1/openai-imagegen-evidence-engine-challenger-v1.png",
    "evidence/v10/local-campaign-pack-v1/openai-imagegen-evidence-engine-challenger-v1.metadata.json",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-hero-4k.png",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-social-1080x1350.png",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-landing-1920x1080.png",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-audio-master-48k-stereo-24bit.wav",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-captions.vtt",
    "evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-campaign-film-4k.mp4",
    "evidence/v10/local-campaign-pack-v1/openai-imagegen-proof-observatory-challenger-v2.metadata.json",
    "evidence/v10/local-campaign-pack-v1/delivery-v8/campaign-pack-manifest.json",
    "artifacts/campaign-pack-visual-blind-review-v3/campaign-pack-blind-review-public.json",
    "artifacts/campaign-pack-visual-blind-review-v3/campaign-pack-blind-review-private.json",
    "evidence/v10/gtm-lifecycle-closure-matrix-v1.json",
    "evidence/v10/gtm-revenue-memory-demo.json",
    "artifacts/gtm-revenue-memory-demo-v1/synthetic-product.png",
    "artifacts/gtm-revenue-memory-demo-v1/approved-preview.png",
    "artifacts/gtm-revenue-memory-demo-v1/approved-campaign-bundle.zip",
    "artifacts/gtm-revenue-memory-demo-v1/gtm-strategy.json",
    "artifacts/gtm-revenue-memory-demo-v1/content-calendar.json",
    "artifacts/gtm-revenue-memory-demo-v1/portable-memory-capsule.json",
    "artifacts/gtm-revenue-memory-demo-v1/device-b-approved-learning-context.json",
    "artifacts/gtm-revenue-memory-demo-v1/device-a-final-gtm-cockpit.json",
    "artifacts/gtm-revenue-memory-demo-v1/device-b-next-cycle-gtm-cockpit.json",
    "artifacts/local-multimodal-qualification-v1/qwen3-tts/proof-before-promise.wav",
    "artifacts/local-multimodal-qualification-v1/qwen3-tts/proof-before-promise-master.wav",
    "artifacts/local-multimodal-qualification-v1/ltx23/proof-before-promise.mp4",
    "artifacts/local-multimodal-qualification-v1/ltx23/proof-before-promise-frame.png",
    "artifacts/local-multimodal-qualification-v1/ltx23/proof-before-promise-one-stage.mp4",
    "artifacts/local-multimodal-qualification-v1/ltx23/proof-before-promise-one-stage-frame.png",
    "workflows/comfyui-official-20260801/manifest.json",
    "workflows/comfyui-official-20260801/qwen-image-2512.api.json",
    "workflows/comfyui-official-20260801/qwen-image-2512.api-export-receipt.json",
    "workflows/comfyui-official-20260801/ltx-2.3-text-to-video.api.json",
    "workflows/comfyui-official-20260801/ltx-2.3-text-to-video.api-export-receipt.json",
    "workflows/comfyui-official-20260801/wan2.2-text-to-video.api.json",
    "workflows/comfyui-official-20260801/wan2.2-text-to-video.api-export-receipt.json",
    "workflows/comfyui-official-20260801/ace-step-1.5-text-to-audio.api.json",
    "workflows/comfyui-official-20260801/ace-step-1.5-text-to-audio.api-export-receipt.json",
    "workflows/comfyui-execution-wrappers-20260801/manifest.json",
    "workflows/comfyui-execution-wrappers-20260801/qwen-image-2512.execution-wrapper.json",
    "workflows/comfyui-execution-wrappers-20260801/ltx-2.3-text-to-video.execution-wrapper.json",
    "workflows/comfyui-execution-wrappers-20260801/wan2.2-text-to-video.execution-wrapper.json",
    "workflows/comfyui-execution-wrappers-20260801/ace-step-1.5-text-to-audio.execution-wrapper.json",
    "evidence/v10/comfyui-weight-supply-chain.json",
    "evidence/v10/comfyui-execution-wrapper-schema.json",
    "evidence/v10/comfyui-wrapper-prompt-validation.json",
    "evidence/v10/channel-portfolio-matrix.json",
    "artifacts/comfyui-gpu-handoff-20260801/handoff.json",
    "artifacts/comfyui-gpu-handoff-20260801/download-and-verify.sh",
    "evidence/v10/gold-five-human-review-gate.json",
    "evidence/v10/curated-1500-human-audit-gate.json",
    "evidence/v10/open-todo-official-deep-review-run.json",
    "evidence/v10/gtm-first-50-output-review-queue-v1.json",
    "evidence/v10/gtm-first-50-level1-seeds-v1.json",
    "evidence/v10/gtm-first-50-codex-prereview-v1.json",
    "artifacts/gtm-first-50-human-read-v1/index.html",
    "evidence/v10/gtm-one-hour-final-execution-contract-v1.json",
    "docs/product/GTM_ONE_HOUR_FINAL_EXECUTION_PLAN_2026-08-06.md",
    "artifacts/gtm-one-hour-final-war-room-v1/index.html",
    "evidence/v10/tokenfactory-product-closure-sprint.json",
    "tests/test_local_agentic_api_soak.py",
    "tests/test_public_signal_gtm_pilot.py",
    "tests/test_gtm_last_mile_quality_benchmark.py",
    "tests/test_gtm_production_quality_contract.py",
    "tests/test_gtm_last_mile_challenger.py",
    "tests/test_gtm_last_mile_diagnostic.py",
    "tests/test_gtm_concrete_product_effect_pk_ledger.py",
    "tests/test_repair_gtm_last_mile_challenger.py",
    "tests/test_generate_gtm_audio_pk_candidates.py",
    "tests/test_gtm_three_beat_video_challenger.py",
    "tests/test_compile_gtm_multimodal_review_packets.py",
    "tests/test_export_gtm_unified_offline_review_kit.py",
    "tests/test_gtm_unified_offline_review.py",
    "tests/test_apple_mlx_runtime_contract.py",
    "tests/test_gtm_platform_native_challenger.py",
    "tests/test_gtm_platform_native_publication_audit.py",
    "tests/test_gtm_platform_generation_quality.py",
    "tests/test_gtm_platform_gold_reference.py",
    "tests/test_gtm_codex_integrated_campaign.py",
    "tests/test_gtm_codex_campaign_work_order.py",
    "tests/test_gtm_codex_candidate_quality.py",
    "tests/test_gtm_codex_lighthouse_portfolio.py",
    "tests/test_gtm_first50_output_review.py",
    "tests/test_gtm_one_hour_final_plan.py",
    "tests/test_local_gemma3_platform_native_challenger_runner.py",
    "tests/test_platform_publication_repair_durability.py",
    "tests/test_gtm_platform_craft_review.py",
    "tests/test_export_gtm_platform_craft_review_kit.py",
    "tests/test_gtm_named_product_baseline.py",
    "tests/test_gtm_challenger_dossier.py",
    "tests/test_gtm_blocked_challenger_repairs.py",
    "tests/test_gtm_named_product_pk.py",
    "tests/test_gtm_hybrid_quality_control.py",
    "tests/test_gtm_omnichannel_craft_os.py",
    "tests/test_gtm_adaptive_capability_graph.py",
    "tests/test_gtm_creative_alpha.py",
    "tests/test_gtm_market_language.py",
    "tests/test_gtm_team_capability_os.py",
    "tests/test_gtm_human_capability_kernel.py",
    "tests/test_gtm_craft_handoff.py",
    "tests/test_gtm_craft_handoff_matrix.py",
    "tests/test_gtm_brief_intelligence.py",
    "tests/test_gtm_organic_breakout_admission.py",
    "tests/test_gtm_market_neighborhood.py",
    "tests/test_gtm_creative_strategy_kernel.py",
    "tests/test_gtm_editorial_quality.py",
    "tests/test_gtm_multimodal_director.py",
    "tests/test_gtm_distribution_operations.py",
    "tests/test_gtm_revenue_journey.py",
    "tests/test_gtm_mechanism_abstraction.py",
    "tests/test_gtm_promotion_governance.py",
    "tests/test_local_gemma3_text_craft_quality_runner.py",
    "docs/product/GTM_CREATIVE_ALPHA_V1.md",
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_content_seal(payload: dict[str, object], *, label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    observed = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if supplied != observed:
        raise SystemExit(f"{label} content seal is invalid")


def run_tests(timeout_seconds: int) -> dict[str, object]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SOURCE_ROOT)
    command = [
        str(PROJECT_PYTHON),
        "-m",
        "unittest",
        "tests.test_gtm_strategy_memory",
        "tests.test_gtm_industry_profile",
        "tests.test_gtm_industry_profile_matrix",
        "tests.test_gtm_production_pack",
        "tests.test_gtm_channel_portfolio_evidence",
        "tests.test_gtm_distribution_decision",
        "tests.test_gtm_distribution_advantage_evidence",
        "tests.test_gtm_distribution_advantage_research",
        "tests.test_gtm_effect_alignment_benchmark",
        "tests.test_gtm_last_mile_quality_benchmark",
        "tests.test_gtm_production_quality_contract",
        "tests.test_gtm_brief_intelligence",
        "tests.test_gtm_organic_breakout_admission",
        "tests.test_gtm_market_neighborhood",
        "tests.test_gtm_creative_strategy_kernel",
        "tests.test_gtm_editorial_quality",
        "tests.test_gtm_multimodal_director",
        "tests.test_gtm_distribution_operations",
        "tests.test_gtm_revenue_journey",
        "tests.test_gtm_mechanism_abstraction",
        "tests.test_gtm_promotion_governance",
        "tests.test_gtm_last_mile_challenger",
        "tests.test_gtm_last_mile_diagnostic",
        "tests.test_gtm_concrete_product_effect_pk_ledger",
        "tests.test_repair_gtm_last_mile_challenger",
        "tests.test_generate_gtm_audio_pk_candidates",
        "tests.test_gtm_three_beat_video_challenger",
        "tests.test_compile_gtm_multimodal_review_packets",
        "tests.test_export_gtm_unified_offline_review_kit",
        "tests.test_gtm_unified_offline_review",
        "tests.test_apple_mlx_runtime_contract",
        "tests.test_gtm_platform_native_challenger",
        "tests.test_gtm_platform_native_publication_audit",
        "tests.test_gtm_platform_generation_quality",
        "tests.test_gtm_platform_gold_reference",
        "tests.test_gtm_codex_integrated_campaign",
        "tests.test_gtm_codex_campaign_work_order",
        "tests.test_gtm_codex_candidate_quality",
        "tests.test_gtm_codex_lighthouse_portfolio",
        "tests.test_gtm_first50_output_review",
        "tests.test_gtm_one_hour_final_plan",
        "tests.test_local_gemma3_platform_native_challenger_runner",
        "tests.test_platform_publication_repair_durability",
        "tests.test_gtm_platform_craft_review",
        "tests.test_export_gtm_platform_craft_review_kit",
        "tests.test_gtm_named_product_baseline",
        "tests.test_gtm_challenger_dossier",
        "tests.test_gtm_blocked_challenger_repairs",
        "tests.test_gtm_named_product_pk",
        "tests.test_gtm_hybrid_quality_control",
        "tests.test_gtm_omnichannel_craft_os",
        "tests.test_gtm_adaptive_capability_graph",
        "tests.test_gtm_creative_alpha",
        "tests.test_gtm_market_language",
        "tests.test_gtm_team_capability_os",
        "tests.test_gtm_human_capability_kernel",
        "tests.test_gtm_craft_handoff",
        "tests.test_gtm_craft_handoff_matrix",
        "tests.test_gtm_content_calendar",
        "tests.test_gtm_breakout_loop",
        "tests.test_gtm_text_challenger",
        "tests.test_gtm_text_challenger_runner",
        "tests.test_gtm_strategy_challenger",
        "tests.test_local_gemma3_strategy_challenger_runner",
        "tests.test_gtm_strategy_portfolio",
        "tests.test_local_gemma3_strategy_portfolio_runner",
        "tests.test_local_gemma3_text_craft_quality_runner",
        "tests.test_gtm_blind_review_service",
        "tests.test_gtm_portfolio_blind_review_service",
        "tests.test_campaign_pack_blind_review",
        "tests.test_gtm_judge_calibration",
        "tests.test_gtm_local_judge_queue",
        "tests.test_agentic_product_readiness",
        "tests.test_gtm_context_quality",
        "tests.test_production_guardrails",
        "tests.test_production_guardrail_eval",
        "tests.test_production_trace_ledger",
        "tests.test_production_trace_retention_evidence",
        "tests.test_local_agentic_api_soak",
        "tests.test_launch_proof_control",
        "tests.test_gtm_multimodal_seed_compiler",
        "tests.test_gtm_omnichannel_activation",
        "tests.test_inference_gateway",
        "tests.test_graph_loop_harness",
        "tests.test_gtm_signal_intelligence",
        "tests.test_social_collection",
        "tests.test_social_collection_runner",
        "tests.test_gtm_effect_feedback",
        "tests.test_gtm_production_observation_kit",
        "tests.test_gtm_manual_publication_receipt",
        "tests.test_gtm_revenue_feedback",
        "tests.test_gtm_effect_packet",
        "tests.test_comfyui_backend_registry",
        "tests.test_comfyui_production",
        "tests.test_generative_candidate_batch",
        "tests.test_progressive_multimodal_production",
        "tests.test_official_comfyui_workflow_capture",
        "tests.test_gtm_open_source_capability_radar",
        "tests.test_comfyui_weight_supply_chain",
        "tests.test_comfyui_execution_wrappers",
        "tests.test_comfyui_gpu_handoff",
        "tests.test_comfyui_bindings",
        "tests.test_gtm_learning_memory",
        "tests.test_gtm_memory_capsule",
        "tests.test_accelerator_portability",
        "tests.test_local_multimodal_qualification",
        "tests.test_local_campaign_pack",
        "tests.test_gtm_lifecycle_closure",
        "tests.test_gtm_revenue_memory_demo",
        "tests.test_v10_submission_store",
        "tests.test_v10_submission_runtime",
        "tests.test_v10_submission_production_api",
        "tests.test_v10_submission_ui",
        "tests.test_run_bound_multimodal_demo",
        "tests.test_local_gtm_creative_benchmark",
        "tests.test_local_gtm_creative_effect_audit",
        "tests.test_gtm_text_challenger_scenario_lens",
        "tests.test_local_gtm_portfolio_blind_review",
        "tests.test_v10_frontier_api_panel",
        "tests.test_v10_free_cloud_router",
        "tests.test_v10_frontier_free_api_runner",
        "tests.test_public_signal_gtm_pilot",
        "tests.test_tool_execution_sandbox",
        "tests.test_ci_quality_gate",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )
    combined = completed.stdout + completed.stderr
    match = re.search(rb"Ran\s+(\d+)\s+tests?", combined)
    return {
        "command": command[1:],
        "return_code": completed.returncode,
        "passed": completed.returncode == 0,
        "test_count": int(match.group(1)) if match else None,
        "output_sha256": hashlib.sha256(combined).hexdigest(),
        "output_tail": combined[-20000:].decode("utf-8", errors="replace"),
    }


def run_local_route_node_tests(timeout_seconds: int) -> dict[str, object]:
    command = [
        "node",
        "--test",
        "tests/test_local_gtm_route_head.mjs",
        "tests/test_local_gtm_route_runtime.mjs",
        "tests/test_local_gtm_generative_baseline.mjs",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )
    combined = completed.stdout + completed.stderr
    match = re.search(rb"tests\s+(\d+)", combined)
    return {
        "command": command,
        "return_code": completed.returncode,
        "passed": completed.returncode == 0,
        "test_count": int(match.group(1)) if match else None,
        "output_sha256": hashlib.sha256(combined).hexdigest(),
        "output_tail": combined[-2000:].decode("utf-8", errors="replace"),
    }


def run_web_product_build(timeout_seconds: int) -> dict[str, object]:
    command = ["npm", "run", "build"]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT / "web",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )
    combined = completed.stdout + completed.stderr
    route_match = re.search(rb"Routes:\s+(\d+)", combined)
    api_match = re.search(rb"Same-origin API contracts:\s+(\d+)", combined)
    bytes_match = re.search(rb"Static resource bytes:\s+(\d+)", combined)
    return {
        "command": command,
        "return_code": completed.returncode,
        "passed": completed.returncode == 0,
        "route_count": int(route_match.group(1)) if route_match else None,
        "same_origin_api_contract_count": int(api_match.group(1))
        if api_match
        else None,
        "static_resource_bytes": int(bytes_match.group(1)) if bytes_match else None,
        "output_sha256": hashlib.sha256(combined).hexdigest(),
        "output_tail": combined[-2000:].decode("utf-8", errors="replace"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "evidence/v10/aug3-product-readiness.json"),
    )
    parser.add_argument("--test-timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    if not 30 <= args.test_timeout_seconds <= 900:
        raise SystemExit("--test-timeout-seconds must be in [30, 900]")

    missing = [relative for relative in REQUIRED_PATHS if not (PROJECT_ROOT / relative).is_file()]
    if missing:
        raise SystemExit(f"required product files are missing: {missing}")
    tests = run_tests(args.test_timeout_seconds)
    if not tests["passed"]:
        raise SystemExit(f"product-critical regression failed:\n{tests['output_tail']}")
    local_route_node_tests = run_local_route_node_tests(args.test_timeout_seconds)
    if not local_route_node_tests["passed"]:
        raise SystemExit(
            "local route-head regression failed:\n"
            f"{local_route_node_tests['output_tail']}"
        )
    web_product_build = run_web_product_build(args.test_timeout_seconds)
    if not web_product_build["passed"]:
        raise SystemExit(
            "web product build failed:\n" f"{web_product_build['output_tail']}"
        )

    connectors = connector_registry()
    gold_human_gate = json.loads(
        (PROJECT_ROOT / "evidence/v10/gold-five-human-review-gate.json").read_text(
            encoding="utf-8"
        )
    )
    curated_human_gate = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/curated-1500-human-audit-gate.json"
        ).read_text(encoding="utf-8")
    )
    official_advisory = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/open-todo-official-deep-review-run.json"
        ).read_text(encoding="utf-8")
    )
    product_closure_sprint = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/tokenfactory-product-closure-sprint.json"
        ).read_text(encoding="utf-8")
    )
    official_comfyui_manifest = json.loads(
        (
            PROJECT_ROOT / "workflows/comfyui-official-20260801/manifest.json"
        ).read_text(encoding="utf-8")
    )
    comfyui_backend_registry = json.loads(
        (PROJECT_ROOT / "config/comfyui_production_backends_v1.json").read_text(
            encoding="utf-8"
        )
    )
    open_source_capability_radar = json.loads(
        (PROJECT_ROOT / "config/gtm_open_source_capability_radar_v1.json").read_text(
            encoding="utf-8"
        )
    )
    comfyui_weight_supply_chain = json.loads(
        (PROJECT_ROOT / "evidence/v10/comfyui-weight-supply-chain.json").read_text(
            encoding="utf-8"
        )
    )
    comfyui_execution_wrappers = json.loads(
        (
            PROJECT_ROOT
            / "workflows/comfyui-execution-wrappers-20260801/manifest.json"
        ).read_text(encoding="utf-8")
    )
    comfyui_execution_wrapper_schema = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/comfyui-execution-wrapper-schema.json"
        ).read_text(encoding="utf-8")
    )
    comfyui_wrapper_prompt_validation = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/comfyui-wrapper-prompt-validation.json"
        ).read_text(encoding="utf-8")
    )
    comfyui_gpu_handoff = json.loads(
        (
            PROJECT_ROOT / "artifacts/comfyui-gpu-handoff-20260801/handoff.json"
        ).read_text(encoding="utf-8")
    )
    comfyui_execution_bindings = json.loads(
        (PROJECT_ROOT / "config/comfyui_execution_bindings_v1.json").read_text(
            encoding="utf-8"
        )
    )
    channel_portfolio_matrix = json.loads(
        (PROJECT_ROOT / "evidence/v10/channel-portfolio-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    distribution_advantage_matrix = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-distribution-advantage-matrix-v2.json"
        ).read_text(encoding="utf-8")
    )
    distribution_advantage_research = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-distribution-advantage-research-2026-08-02.json"
        ).read_text(encoding="utf-8")
    )
    effect_alignment_benchmark = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-ten-peer-effect-alignment-benchmark-v1.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_quality_benchmark = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-last-mile-production-quality-v1.json"
        ).read_text(encoding="utf-8")
    )
    concrete_product_effect_pk = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_challenger = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_challenger_repair = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger-repaired.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_internal_review = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3/scope.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_audio_candidates = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/audio-candidate-receipt.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_video_challenger = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/video-challenger-v5/video-challenger-receipt.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_unified_review = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/unified-last-mile-review.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_offline_review_kit = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2/export-receipt.json"
        ).read_text(encoding="utf-8")
    )
    last_mile_offline_review_manifest = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/unified-offline-review-kit-v2/manifest.json"
        ).read_text(encoding="utf-8")
    )
    apple_mlx_preflight = json.loads(
        (PROJECT_ROOT / "evidence/v10/apple-mlx-runtime-preflight.json").read_text(
            encoding="utf-8"
        )
    )
    verify_content_seal(apple_mlx_preflight, label="Apple MLX preflight")
    platform_b2b_plan = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2b-plan.json"
        ).read_text(encoding="utf-8")
    )
    platform_b2c_plan = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2c-plan.json"
        ).read_text(encoding="utf-8")
    )
    platform_b2b_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2b-publication-repaired-receipt.json"
        ).read_text(encoding="utf-8")
    )
    platform_b2c_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1/b2c-local-gemma3-v1-receipt.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_native_challenger_plan(platform_b2b_plan)
    verify_platform_native_challenger_plan(platform_b2c_plan)
    verify_platform_native_receipt(platform_b2b_receipt, plan=platform_b2b_plan)
    verify_platform_native_receipt(platform_b2c_receipt, plan=platform_b2c_plan)
    platform_publication_audit = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-platform-native-publication-audit-v2.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_native_publication_audit(platform_publication_audit)
    platform_craft_public = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/public/platform-craft-review-public.json"
        ).read_text(encoding="utf-8")
    )
    platform_craft_private = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/private/platform-craft-review-private.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_craft_review_bundle(platform_craft_public, platform_craft_private)
    platform_craft_manifest = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/public/manifest.json"
        ).read_text(encoding="utf-8")
    )
    platform_craft_export = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-v1/export-receipt.json"
        ).read_text(encoding="utf-8")
    )
    verify_content_seal(platform_craft_manifest, label="platform craft manifest")
    verify_content_seal(platform_craft_export, label="platform craft export")
    platform_craft_archive = PROJECT_ROOT / platform_craft_export["archive"]["path"]
    if (
        platform_craft_export["archive"]["sha256"]
        != sha256_path(platform_craft_archive)
        or platform_craft_manifest["public_packet_sha256"]
        != platform_craft_public["content_sha256"]
        or platform_craft_manifest["private_mapping_commitment"]
        != platform_craft_private["content_sha256"]
    ):
        raise SystemExit("platform craft review kit binding is invalid")
    platform_gold_reference = json.loads(
        (
            PROJECT_ROOT / "config/platform-native-b2b-gold-reference-v1.json"
        ).read_text(encoding="utf-8")
    )
    if (
        platform_gold_reference.get("schema")
        != "ProofLaunchPlatformNativeGoldReferenceV1"
        or len(platform_gold_reference.get("candidates", ())) != 13
        or platform_gold_reference.get("rights_status")
        != "original_clean_room_workspace_reference"
        or any(
            platform_gold_reference.get(field) is not False
            for field in (
                "named_product_baseline",
                "human_review_completed",
                "production_effect_observed",
            )
        )
    ):
        raise SystemExit("platform gold reference truth boundary is invalid")
    platform_gold_b2b_plan = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-plan.json"
        ).read_text(encoding="utf-8")
    )
    platform_gold_b2b_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-gold-reference-v1-receipt.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_native_challenger_plan(platform_gold_b2b_plan)
    verify_platform_native_receipt(
        platform_gold_b2b_receipt, plan=platform_gold_b2b_plan
    )
    platform_gold_quality_audit = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-platform-gold-reference-quality-audit-v1.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_generation_quality_audit(platform_gold_quality_audit)
    if (
        platform_gold_quality_audit["plan_sha256"]
        != platform_gold_b2b_plan["content_sha256"]
        or platform_gold_quality_audit["receipt_sha256"]
        != platform_gold_b2b_receipt["content_sha256"]
        or platform_gold_quality_audit["pre_human_quality_pass_count"] != 13
        or platform_gold_quality_audit["human_craft_review_completed_count"] != 0
        or platform_gold_quality_audit["production_effect_observed"] is not False
    ):
        raise SystemExit("platform gold quality audit binding is invalid")
    platform_codex_overlay_path = (
        PROJECT_ROOT / "config/platform-native-b2b-codex-capability-overlay-v2.json"
    )
    platform_codex_overlay = json.loads(
        platform_codex_overlay_path.read_text(encoding="utf-8")
    )
    platform_codex_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v13/b2b-codex-capability-reference-v2-receipt.json"
        ).read_text(encoding="utf-8")
    )
    platform_codex_quality_audit = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-platform-codex-capability-reference-quality-audit-v2.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_native_receipt(
        platform_codex_receipt, plan=platform_gold_b2b_plan
    )
    verify_platform_generation_quality_audit(platform_codex_quality_audit)
    platform_codex_overrides = platform_codex_overlay.get("overrides", ())
    platform_codex_explicit_synthetic_surface_count = sum(
        any(
            label in json.dumps(row, ensure_ascii=False).lower()
            for label in ("synthetic scenario", "hypothetical", "composite")
        )
        for row in platform_codex_overrides
        if isinstance(row, dict)
    )
    platform_codex_sources = [
        attempt.get("source")
        for result in platform_codex_receipt["results"]
        for attempt in result.get("attempts", ())
    ]
    if (
        platform_codex_overlay.get("schema")
        != "ProofLaunchPlatformNativeCodexOverlayV1"
        or platform_codex_overlay.get("base_reference_sha256")
        != sha256_path(
            PROJECT_ROOT / "config/platform-native-b2b-gold-reference-v1.json"
        )
        or platform_codex_overlay.get("brief_id")
        != platform_gold_b2b_plan["brief"]["brief_id"]
        or platform_codex_overlay.get("business_model") != "b2b"
        or len(platform_codex_overrides) != 3
        or {row.get("surface_id") for row in platform_codex_overrides}
        != {"linkedin", "tiktok", "google_search"}
        or platform_codex_explicit_synthetic_surface_count != 3
        or any(
            platform_codex_overlay.get(field) is not False
            for field in (
                "named_product_baseline",
                "human_review_completed",
                "production_effect_observed",
            )
        )
        or platform_codex_receipt["model"]["provider"]
        != "codex_workspace_clean_room_reference_authoring"
        or platform_codex_receipt["model"]["base_reference_sha256"]
        != platform_codex_overlay["base_reference_sha256"]
        or platform_codex_receipt["model"]["overlay_sha256"]
        != sha256_path(platform_codex_overlay_path)
        or platform_codex_receipt["model"]["overlay_surface_count"] != 3
        or platform_codex_receipt["model"]["local_inference_claimed"] is not False
        or platform_codex_receipt["model"]["training_observed"] is not False
        or platform_codex_receipt["accepted_surface_count"] != 13
        or platform_codex_sources.count("codex_clean_room_capability_overlay") != 3
        or platform_codex_quality_audit["plan_sha256"]
        != platform_gold_b2b_plan["content_sha256"]
        or platform_codex_quality_audit["receipt_sha256"]
        != platform_codex_receipt["content_sha256"]
        or platform_codex_quality_audit["pre_human_quality_pass_count"] != 13
        or platform_codex_quality_audit["blocked_count"] != 0
        or platform_codex_quality_audit["cross_surface_duplicate_pairs"]
        or platform_codex_quality_audit["human_craft_review_completed_count"] != 0
        or platform_codex_quality_audit["production_effect_observed"] is not False
        or platform_codex_quality_audit["four_a_claim_eligible"] is not False
        or platform_codex_quality_audit["top1_claim_eligible"] is not False
    ):
        raise SystemExit("Codex capability overlay truth or quality binding is invalid")
    platform_codex_b2c_reference_path = (
        PROJECT_ROOT / "config/platform-native-b2c-codex-reference-v1.json"
    )
    platform_codex_b2c_reference = json.loads(
        platform_codex_b2c_reference_path.read_text(encoding="utf-8")
    )
    platform_codex_b2c_plan = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2c-plan.json"
        ).read_text(encoding="utf-8")
    )
    platform_codex_b2c_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json"
        ).read_text(encoding="utf-8")
    )
    platform_codex_b2c_quality_audit = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-platform-b2c-codex-reference-quality-audit-v1.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_native_challenger_plan(platform_codex_b2c_plan)
    verify_platform_native_receipt(
        platform_codex_b2c_receipt, plan=platform_codex_b2c_plan
    )
    verify_platform_generation_quality_audit(platform_codex_b2c_quality_audit)
    if (
        platform_codex_b2c_reference.get("schema")
        != "ProofLaunchPlatformNativeGoldReferenceV1"
        or platform_codex_b2c_reference.get("brief_id")
        != platform_codex_b2c_plan["brief"]["brief_id"]
        or platform_codex_b2c_reference.get("business_model") != "b2c"
        or platform_codex_b2c_reference.get("rights_status")
        != "original_clean_room_workspace_reference"
        or len(platform_codex_b2c_reference.get("candidates", ())) != 13
        or any(
            platform_codex_b2c_reference.get(field) is not False
            for field in (
                "named_product_baseline",
                "human_review_completed",
                "production_effect_observed",
            )
        )
        or platform_codex_b2c_receipt["model"]["provider"]
        != "codex_workspace_clean_room_reference_authoring"
        or platform_codex_b2c_receipt["model"]["base_reference_sha256"]
        != sha256_path(platform_codex_b2c_reference_path)
        or platform_codex_b2c_receipt["model"]["capability_reference_only"]
        is not True
        or platform_codex_b2c_receipt["model"]["local_inference_claimed"]
        is not False
        or platform_codex_b2c_receipt["model"]["training_observed"] is not False
        or platform_codex_b2c_receipt["accepted_surface_count"] != 13
        or platform_codex_b2c_quality_audit["plan_sha256"]
        != platform_codex_b2c_plan["content_sha256"]
        or platform_codex_b2c_quality_audit["receipt_sha256"]
        != platform_codex_b2c_receipt["content_sha256"]
        or platform_codex_b2c_quality_audit["capability_reference_only"] is not True
        or platform_codex_b2c_quality_audit["pre_human_quality_pass_count"] != 13
        or platform_codex_b2c_quality_audit["blocked_count"] != 0
        or platform_codex_b2c_quality_audit["cross_surface_duplicate_pairs"]
        or platform_codex_b2c_quality_audit[
            "mechanically_publication_ready_count"
        ]
        != 0
        or platform_codex_b2c_quality_audit["publication_blocked_count"] != 13
        or any(
            row.get("publication_blockers")
            != ["synthetic_benchmark_is_not_publishable_product_content"]
            for row in platform_codex_b2c_quality_audit["rows"]
        )
        or platform_codex_b2c_quality_audit[
            "human_craft_review_completed_count"
        ]
        != 0
        or platform_codex_b2c_quality_audit["production_effect_observed"]
        is not False
        or platform_codex_b2c_quality_audit["four_a_claim_eligible"] is not False
        or platform_codex_b2c_quality_audit["top1_claim_eligible"] is not False
    ):
        raise SystemExit("Codex B2C capability-reference binding is invalid")
    codex_integrated_campaign_portfolio = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-codex-integrated-campaign-portfolio-v1.json"
        ).read_text(encoding="utf-8")
    )
    verify_codex_integrated_campaign_portfolio(
        codex_integrated_campaign_portfolio
    )
    if (
        codex_integrated_campaign_portfolio["pack_count"] != 2
        or codex_integrated_campaign_portfolio["platform_candidate_count"] != 26
        or codex_integrated_campaign_portfolio["email_count"] != 8
        or codex_integrated_campaign_portfolio["production_direction_count"] != 6
        or codex_integrated_campaign_portfolio["search_geo_node_count"] != 14
        or codex_integrated_campaign_portfolio["seven_day_flight_slot_count"] != 14
        or codex_integrated_campaign_portfolio["experiment_count"] != 8
        or codex_integrated_campaign_portfolio["release_eligible_count"] != 0
        or codex_integrated_campaign_portfolio["human_review_completed_count"] != 0
        or codex_integrated_campaign_portfolio["production_effect_observed"]
        is not False
        or codex_integrated_campaign_portfolio["causal_effect_claim_allowed"]
        is not False
        or codex_integrated_campaign_portfolio["named_product_pk_completed_count"]
        != 0
        or codex_integrated_campaign_portfolio["external_publish_executed"]
        is not False
        or codex_integrated_campaign_portfolio[
            "automatic_send_spend_or_strategy_mutation"
        ]
        is not False
        or codex_integrated_campaign_portfolio["paid_media_spend_usd"] != 0
        or codex_integrated_campaign_portfolio["packs"][1][
            "publication_policy_state"
        ]
        != "permanently_blocked_synthetic_benchmark"
    ):
        raise SystemExit("Codex integrated campaign portfolio truth boundary is invalid")
    codex_campaign_adaptation_matrix = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-codex-campaign-adaptation-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    verify_codex_campaign_adaptation_matrix(codex_campaign_adaptation_matrix)
    codex_campaign_adaptation_summary = (
        load_verified_codex_campaign_adaptation_summary(PROJECT_ROOT)
    )
    if (
        codex_campaign_adaptation_matrix["case_count"] != 456
        or codex_campaign_adaptation_matrix["work_order_count"] != 456
        or codex_campaign_adaptation_matrix["zero_budget_work_order_count"] != 152
        or codex_campaign_adaptation_matrix["regulated_work_order_count"] != 72
        or codex_campaign_adaptation_matrix["model_call_count"] != 0
        or codex_campaign_adaptation_matrix["candidate_output_count"] != 0
        or codex_campaign_adaptation_matrix["human_review_completed_count"] != 0
        or codex_campaign_adaptation_matrix["release_eligible_count"] != 0
        or codex_campaign_adaptation_matrix["external_publish_executed_count"] != 0
        or codex_campaign_adaptation_matrix["production_effect_observed_count"] != 0
        or codex_campaign_adaptation_matrix["causal_effect_claim_allowed_count"] != 0
        or codex_campaign_adaptation_summary["case_count"] != 456
        or len(codex_campaign_adaptation_summary["archetypes"]) != 20
        or "work_orders" in codex_campaign_adaptation_summary
    ):
        raise SystemExit("Codex campaign adaptation matrix truth boundary is invalid")
    codex_lighthouse_portfolio = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json"
        ).read_text(encoding="utf-8")
    )
    codex_lighthouse_quality = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json"
        ).read_text(encoding="utf-8")
    )
    verify_lighthouse_portfolio(codex_lighthouse_portfolio)
    verify_lighthouse_quality_portfolio(
        codex_lighthouse_quality,
        portfolio=codex_lighthouse_portfolio,
    )
    codex_lighthouse_public = load_verified_codex_lighthouse_portfolio(PROJECT_ROOT)
    if (
        codex_lighthouse_portfolio["candidate_count"] != 8
        or codex_lighthouse_portfolio["workspace_authored_candidate_count"] != 8
        or codex_lighthouse_portfolio["platform_asset_count"] != 16
        or codex_lighthouse_portfolio["regulated_candidate_count"] != 2
        or codex_lighthouse_quality["level_1_audit_count"] != 8
        or codex_lighthouse_quality["level_1_pass_count"] != 8
        or codex_lighthouse_quality["level_1_reject_count"] != 0
        or codex_lighthouse_quality["located_critical_failure_count"] != 0
        or codex_lighthouse_quality["calibrated_model_critic_pass_count"] != 0
        or codex_lighthouse_quality["qualified_human_review_count"] != 0
        or codex_lighthouse_quality["release_eligible_count"] != 0
        or codex_lighthouse_quality["external_publish_executed_count"] != 0
        or codex_lighthouse_quality["production_effect_observed_count"] != 0
        or codex_lighthouse_quality["causal_revenue_effect_proven_count"] != 0
        or codex_lighthouse_quality["four_a_quality_proven"] is not False
        or codex_lighthouse_quality["top1_claim_eligible"] is not False
        or codex_lighthouse_public["candidate_count"] != 8
        or codex_lighthouse_public["level_1_audit_pass_count"] != 8
        or len(codex_lighthouse_public["cases"]) != 8
    ):
        raise SystemExit("Codex lighthouse candidate truth boundary is invalid")
    platform_gold_publication_audit = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-platform-gold-reference-publication-audit-v1.json"
        ).read_text(encoding="utf-8")
    )
    verify_platform_native_publication_audit(platform_gold_publication_audit)
    platform_gold_craft_root = (
        PROJECT_ROOT
        / "artifacts/gtm-last-mile-pk-v1/platform-craft-review-kit-gold-v1"
    )
    platform_gold_craft_public = json.loads(
        (platform_gold_craft_root / "public/platform-craft-review-public.json").read_text(
            encoding="utf-8"
        )
    )
    platform_gold_craft_private = json.loads(
        (platform_gold_craft_root / "private/platform-craft-review-private.json").read_text(
            encoding="utf-8"
        )
    )
    verify_platform_craft_review_bundle(
        platform_gold_craft_public, platform_gold_craft_private
    )
    platform_gold_craft_manifest = json.loads(
        (platform_gold_craft_root / "public/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    platform_gold_craft_export = json.loads(
        (platform_gold_craft_root / "export-receipt.json").read_text(
            encoding="utf-8"
        )
    )
    verify_content_seal(
        platform_gold_craft_manifest, label="platform gold craft manifest"
    )
    verify_content_seal(
        platform_gold_craft_export, label="platform gold craft export"
    )
    platform_gold_craft_archive = (
        PROJECT_ROOT / platform_gold_craft_export["archive"]["path"]
    )
    if (
        platform_gold_craft_export["archive"]["sha256"]
        != sha256_path(platform_gold_craft_archive)
        or platform_gold_craft_manifest["public_packet_sha256"]
        != platform_gold_craft_public["content_sha256"]
        or platform_gold_craft_manifest["private_mapping_commitment"]
        != platform_gold_craft_private["content_sha256"]
        or platform_gold_craft_public["submitted_human_review_count"] != 0
        or platform_gold_craft_public["craft_review_completed"] is not False
    ):
        raise SystemExit("platform gold craft review kit binding is invalid")
    named_product_baseline_capture_manifest = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/manifest.json"
        ).read_text(encoding="utf-8")
    )
    named_product_baseline_capture_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-capture-kit-v1/export-receipt.json"
        ).read_text(encoding="utf-8")
    )
    named_product_pk_portfolio = json.loads(
        (PROJECT_ROOT / "evidence/v10/named-product-pk-portfolio-v1.json").read_text(
            encoding="utf-8"
        )
    )
    named_product_challenger_admission = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v1/manifest.json"
        ).read_text(encoding="utf-8")
    )
    named_product_challenger_repairs = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/manifest.json"
        ).read_text(encoding="utf-8")
    )
    industry_profile_matrix = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-industry-profile-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    market_language_matrix = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-market-language-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    team_capability_matrix = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-team-capability-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    craft_handoff_matrix = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-craft-handoff-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    local_route_model = json.loads(
        (PROJECT_ROOT / "artifacts/local-gtm-route-head-v3/model.json").read_text(
            encoding="utf-8"
        )
    )
    local_route_metrics = json.loads(
        (PROJECT_ROOT / "artifacts/local-gtm-route-head-v3/metrics.json").read_text(
            encoding="utf-8"
        )
    )
    local_route_receipt = json.loads(
        (
            PROJECT_ROOT / "artifacts/local-gtm-route-head-v3/training-receipt.json"
        ).read_text(encoding="utf-8")
    )
    frontier_panel = json.loads(
        (PROJECT_ROOT / "config/cortex_x_v10_frontier_api_panel.json").read_text(
            encoding="utf-8"
        )
    )
    frontier_free_sprint = json.loads(
        (PROJECT_ROOT / "evidence/v10/frontier-free-api-sprint.json").read_text(
            encoding="utf-8"
        )
    )
    local_cloud_resources = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/local-first-model-resource-discovery.json"
        ).read_text(encoding="utf-8")
    )
    free_cloud_execution_plan = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/free-cloud-execution-plan-v2.json"
        ).read_text(encoding="utf-8")
    )
    hybrid_quality_control = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-hybrid-quality-control-v1.json"
        ).read_text(encoding="utf-8")
    )
    adaptive_capability_graph = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/gtm-adaptive-capability-graph-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    adaptive_capability_graph_public = _public_gtm_adaptive_capability_graph(
        adaptive_capability_graph,
        {},
    )
    human_capability_kernel = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-human-capability-kernel-v2.json"
        ).read_text(encoding="utf-8")
    )
    verify_gtm_human_capability_kernel(
        human_capability_kernel,
        open_source_radar=open_source_capability_radar,
    )
    public_signal_collection_receipt = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/cross-platform-public-signal-pilot-v1/collection-receipt.json"
        ).read_text(encoding="utf-8")
    )
    public_signal_gtm_pilot = json.loads(
        (
            PROJECT_ROOT / "artifacts/public-signal-gtm-pilot-v1/pilot-receipt.json"
        ).read_text(encoding="utf-8")
    )
    unsigned_signal_collection = dict(public_signal_collection_receipt)
    supplied_signal_collection_sha256 = unsigned_signal_collection.pop(
        "receipt_sha256", None
    )
    computed_signal_collection_sha256 = hashlib.sha256(
        json.dumps(
            unsigned_signal_collection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    unsigned_signal_pilot = dict(public_signal_gtm_pilot)
    supplied_signal_pilot_sha256 = unsigned_signal_pilot.pop("content_sha256", None)
    computed_signal_pilot_sha256 = hashlib.sha256(
        json.dumps(
            unsigned_signal_pilot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    public_signal_pilot_projection = _public_signal_pilot(public_signal_gtm_pilot)
    local_creative_benchmark = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/local-gtm-creative-benchmark-status.json"
        ).read_text(encoding="utf-8")
    )
    local_creative_effect_audit = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-gtm-creative-effect-audit-v1.json"
        ).read_text(encoding="utf-8")
    )
    local_portfolio_blind_review = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-gtm-portfolio-blind-review-status.json"
        ).read_text(encoding="utf-8")
    )
    local_judge_calibration_queue = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-judge-calibration-queue-status.json"
        ).read_text(encoding="utf-8")
    )
    agentic_product_readiness = json.loads(
        (PROJECT_ROOT / "evidence/v10/agentic-product-readiness-audit.json").read_text(
            encoding="utf-8"
        )
    )
    tool_sandbox_receipt_path = (
        PROJECT_ROOT / "evidence/v10/tool-execution-sandbox-v1.json"
    )
    tool_sandbox_receipt = None
    if tool_sandbox_receipt_path.is_file():
        tool_sandbox_receipt = json.loads(
            tool_sandbox_receipt_path.read_text(encoding="utf-8")
        )
        validate_tool_sandbox_receipt(tool_sandbox_receipt)
    gtm_context_quality = json.loads(
        (PROJECT_ROOT / "evidence/v10/gtm-context-quality-v1.json").read_text(
            encoding="utf-8"
        )
    )
    production_guardrail_eval = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/production-guardrail-eval-v1.json"
        ).read_text(encoding="utf-8")
    )
    production_trace_retention = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/production-trace-retention-v1.json"
        ).read_text(encoding="utf-8")
    )
    local_agentic_api_soak = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/local-agentic-api-soak-v1.json"
        ).read_text(encoding="utf-8")
    )
    local_generative_baseline = json.loads(
        (
            PROJECT_ROOT / "artifacts/local-gtm-generative-baseline-v1/receipt.json"
        ).read_text(encoding="utf-8")
    )
    local_multimodal_qualification = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/local-multimodal-qualification.json"
        ).read_text(encoding="utf-8")
    )
    local_campaign_pack = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-campaign-pack-v1/delivery-v8/campaign-pack-manifest.json"
        ).read_text(encoding="utf-8")
    )
    run_bound_multimodal_demo = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/run-bound-multimodal-demo-v1/demo-receipt.json"
        ).read_text(encoding="utf-8")
    )
    unsigned_run_bound_multimodal_demo = dict(run_bound_multimodal_demo)
    supplied_run_bound_multimodal_demo_sha256 = (
        unsigned_run_bound_multimodal_demo.pop("content_sha256", None)
    )
    computed_run_bound_multimodal_demo_sha256 = hashlib.sha256(
        json.dumps(
            unsigned_run_bound_multimodal_demo,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        run_bound_multimodal_demo.get("schema")
        != "ProofLaunchRunBoundMultimodalDemoV1"
        or supplied_run_bound_multimodal_demo_sha256
        != computed_run_bound_multimodal_demo_sha256
        or run_bound_multimodal_demo.get("registered_multimodal_deliverable_count")
        != 2
        or run_bound_multimodal_demo.get("registered_capability_deliverable_count")
        != 8
        or run_bound_multimodal_demo.get("registered_run_bound_deliverable_count")
        != 10
        or run_bound_multimodal_demo.get("named_human_quality_count") != 0
        or run_bound_multimodal_demo.get("production_effect_attributed_count") != 0
    ):
        raise SystemExit("run-bound multimodal demo receipt is invalid")
    lifecycle_closure = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/gtm-lifecycle-closure-matrix-v1.json"
        ).read_text(encoding="utf-8")
    )
    revenue_memory_demo = json.loads(
        (PROJECT_ROOT / "evidence/v10/gtm-revenue-memory-demo.json").read_text(
            encoding="utf-8"
        )
    )
    synthetic_lifecycle_demo = load_verified_synthetic_lifecycle_demo(PROJECT_ROOT)
    local_gtm_mission = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/aug3-gtm-employee-mission-v14/mission-receipt.json"
        ).read_text(encoding="utf-8")
    )
    local_gemma_strategy_probe = json.loads(
        (
            PROJECT_ROOT / "evidence/v10/local-gemma3-12b-gtm-strategy-probe.json"
        ).read_text(encoding="utf-8")
    )
    local_gemma_strategy_challenger = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-gemma3-12b-strategy-challenger-v2.json"
        ).read_text(encoding="utf-8")
    )
    validate_strategy_challenger_receipt(local_gemma_strategy_challenger)
    local_gemma_strategy_portfolio = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-gemma3-12b-strategy-portfolio-v1.json"
        ).read_text(encoding="utf-8")
    )
    validate_strategy_portfolio_receipt(local_gemma_strategy_portfolio)
    local_gemma_strategy_portfolio_quality = json.loads(
        (
            PROJECT_ROOT
            / "evidence/v10/local-gemma3-12b-strategy-portfolio-quality-v1.json"
        ).read_text(encoding="utf-8")
    )
    validate_strategy_portfolio_quality_audit(
        local_gemma_strategy_portfolio_quality,
        local_gemma_strategy_portfolio,
    )
    local_gemma_text_craft_quality = json.loads(
        (
            PROJECT_ROOT
            / "artifacts/aug3-local-first-gtm-employee-mission-v14/gemma3-12b-text-craft-quality.json"
        ).read_text(encoding="utf-8")
    )
    local_gemma_text_craft_unsigned = dict(local_gemma_text_craft_quality)
    local_gemma_text_craft_sha256 = local_gemma_text_craft_unsigned.pop(
        "content_sha256", None
    )
    if (
        local_gemma_text_craft_quality.get("schema")
        != "ProofLaunchLocalGemma3TextCraftQualityReceiptV1"
        or local_gemma_text_craft_sha256
        != hashlib.sha256(
            json.dumps(
                local_gemma_text_craft_unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        or local_gemma_text_craft_quality.get("network_download_performed") is not False
        or local_gemma_text_craft_quality.get("cloud_api_calls") != 0
        or local_gemma_text_craft_quality.get("automatic_release_authority") is not False
        or local_gemma_text_craft_quality.get("blind_human_review_completed") is not False
        or local_gemma_text_craft_quality.get("production_effect_observed") is not False
    ):
        raise SystemExit("local Gemma 3 text craft quality receipt is invalid")
    runtime_source = (
        PROJECT_ROOT / "src/prooflaunch_remix/v10_submission_runtime.py"
    ).read_text(encoding="utf-8")
    production_api_source = (
        PROJECT_ROOT / "src/prooflaunch_remix/v10_submission_production_api.py"
    ).read_text(encoding="utf-8")
    web_app_source = (PROJECT_ROOT / "web/app.js").read_text(encoding="utf-8")
    web_index_source = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    platform_codex_showcase_api_present = (
        'path == "/v1/platform-capability-showcase"' in production_api_source
        and "load_verified_platform_capability_showcase(project_root)"
        in production_api_source
    )
    platform_codex_showcase_browser_digest_verified = (
        'requestJson("/v1/platform-capability-showcase")' in web_app_source
        and "ProofLaunchPlatformCapabilityShowcasePublicV1" in web_app_source
        and "computedDigest === suppliedDigest" in web_app_source
    )
    platform_codex_showcase_ui_present = (
        'id="platform-capability-surface"' in web_index_source
        and 'id="platform-capability-grid"' in web_index_source
        and 'id="platform-capability-boundary"' in web_index_source
    )
    codex_integrated_campaign_api_present = (
        'path == "/v1/codex-integrated-campaign-portfolio"'
        in production_api_source
        and "load_verified_codex_integrated_campaign_portfolio"
        in production_api_source
    )
    codex_integrated_campaign_browser_digest_verified = (
        'requestJson("/v1/codex-integrated-campaign-portfolio")'
        in web_app_source
        and "ProofLaunchCodexIntegratedCampaignPortfolioV1" in web_app_source
        and "portfolio.platform_candidate_count === 26" in web_app_source
        and "portfolio.release_eligible_count === 0" in web_app_source
        and "portfolio.production_effect_observed === false" in web_app_source
    )
    codex_integrated_campaign_ui_present = (
        'id="integrated-campaign-model"' in web_index_source
        and 'id="integrated-campaign-core"' in web_index_source
        and 'id="integrated-campaign-phases"' in web_index_source
        and 'id="integrated-campaign-emails"' in web_index_source
        and 'id="integrated-campaign-media"' in web_index_source
        and 'id="integrated-campaign-experiments"' in web_index_source
        and 'id="integrated-campaign-boundary"' in web_index_source
    )
    codex_campaign_adaptation_api_present = (
        'path == "/v1/codex-campaign-adaptation-summary"'
        in production_api_source
        and "load_verified_codex_campaign_adaptation_summary"
        in production_api_source
    )
    codex_campaign_adaptation_browser_digest_verified = (
        'requestJson("/v1/codex-campaign-adaptation-summary")'
        in web_app_source
        and "ProofLaunchCodexCampaignAdaptationSummaryPublicV1"
        in web_app_source
        and "summary.case_count === 456" in web_app_source
        and "summary.model_call_count === 0" in web_app_source
        and "summary.release_eligible_count === 0" in web_app_source
        and "computedDigest === suppliedDigest" in web_app_source
    )
    codex_campaign_adaptation_ui_present = (
        'id="codex-adaptation-status"' in web_index_source
        and 'id="codex-adaptation-archetype"' in web_index_source
        and 'id="codex-adaptation-core"' in web_index_source
        and 'id="codex-adaptation-output"' in web_index_source
        and 'id="codex-adaptation-boundary"' in web_index_source
    )
    codex_lighthouse_api_present = (
        'path == "/v1/codex-lighthouse-portfolio"' in production_api_source
        and "load_verified_codex_lighthouse_portfolio" in production_api_source
    )
    codex_lighthouse_browser_digest_verified = (
        'requestJson("/v1/codex-lighthouse-portfolio")' in web_app_source
        and "ProofLaunchCodexLighthousePortfolioPublicV1" in web_app_source
        and "portfolio.candidate_count === 8" in web_app_source
        and "portfolio.level_1_audit_pass_count === 8" in web_app_source
        and "portfolio.qualified_human_review_count === 0" in web_app_source
        and "portfolio.production_effect_observed_count === 0" in web_app_source
        and "computedDigest === suppliedDigest" in web_app_source
    )
    codex_lighthouse_ui_present = (
        'id="codex-lighthouse-status"' in web_index_source
        and 'id="codex-lighthouse-case"' in web_index_source
        and 'id="codex-lighthouse-core"' in web_index_source
        and 'id="codex-lighthouse-assets"' in web_index_source
        and 'id="codex-lighthouse-email"' in web_index_source
        and 'id="codex-lighthouse-search"' in web_index_source
        and 'id="codex-lighthouse-video"' in web_index_source
        and 'id="codex-lighthouse-experiment"' in web_index_source
        and 'id="codex-lighthouse-boundary"' in web_index_source
    )
    if not all(
        (
            platform_codex_showcase_api_present,
            platform_codex_showcase_browser_digest_verified,
            platform_codex_showcase_ui_present,
            codex_integrated_campaign_api_present,
            codex_integrated_campaign_browser_digest_verified,
            codex_integrated_campaign_ui_present,
            codex_campaign_adaptation_api_present,
            codex_campaign_adaptation_browser_digest_verified,
            codex_campaign_adaptation_ui_present,
            codex_lighthouse_api_present,
            codex_lighthouse_browser_digest_verified,
            codex_lighthouse_ui_present,
        )
    ):
        raise SystemExit("Codex capability, integrated campaign, adaptation, or lighthouse API/UI binding is missing")
    blind_review_status = BlindReviewService(
        PROJECT_ROOT
        / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger"
    ).status()
    portfolio_blind_review_runtime_status = PortfolioBlindReviewService(
        PROJECT_ROOT
        / "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2"
    ).status()
    campaign_pack_blind_review_status = CampaignPackBlindReviewService(
        PROJECT_ROOT / "artifacts/campaign-pack-visual-blind-review-v3",
        project_root=PROJECT_ROOT,
    ).status()
    platform_b2b_publication_ready_count = sum(
        row["mechanical_publication_ready"]
        for row in platform_publication_audit["rows"]
        if row["business_model"] == "b2b"
    )
    platform_b2c_publication_ready_count = sum(
        row["mechanical_publication_ready"]
        for row in platform_publication_audit["rows"]
        if row["business_model"] == "b2c"
    )
    platform_gold_b2b_publication_ready_count = sum(
        row["mechanical_publication_ready"]
        for row in platform_gold_publication_audit["rows"]
        if row["business_model"] == "b2b"
    )
    platform_gold_b2c_publication_ready_count = sum(
        row["mechanical_publication_ready"]
        for row in platform_gold_publication_audit["rows"]
        if row["business_model"] == "b2c"
    )
    discrete_scenario_count = (
        len(BusinessModel)
        * len(LifecycleStage)
        * len(BudgetTier)
        * len(IndustryRisk)
    )
    receipt: dict[str, object] = {
        "schema": "ProofLaunchAug3ProductReadinessV1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "deadline": "2026-08-03",
        "launch_decision": "local_demo_ready_effect_unproven",
        "required_file_sha256": {
            relative: sha256_path(PROJECT_ROOT / relative) for relative in REQUIRED_PATHS
        },
        "verification": {
            "product_critical_regression": tests,
            "local_route_head_node_regression": local_route_node_tests,
            "web_product_build": web_product_build,
            "local_route_head_training_observed": True,
            "local_route_head_base_model": local_route_model["base_embedding_model"]["name"],
            "local_route_head_base_model_digest": local_route_model["base_embedding_model"]["digest"],
            "local_route_head_download_performed": local_route_receipt["network_download_performed"],
            "local_route_head_cloud_api_calls": local_route_receipt["cloud_api_calls"],
            "local_route_head_training_record_count": local_route_receipt["record_count"],
            "local_route_head_final_test_count": local_route_metrics["test"]["count"],
            "local_route_head_test_accuracy": local_route_metrics["test"]["accuracy"],
            "local_route_head_test_macro_f1": local_route_metrics["test"]["macro_f1"],
            "local_route_head_test_accepted_coverage": local_route_metrics["test"]["accepted_coverage"],
            "local_route_head_test_accepted_accuracy": local_route_metrics["test"]["accepted_accuracy"],
            "local_route_head_promotion_gate_passed": local_route_receipt["promotion_gate_passed"],
            "local_route_head_promoted": local_route_receipt["promoted"],
            "local_route_head_automatic_external_action_enabled": local_route_model["automatic_external_action_enabled"],
            "local_generative_baseline_model": local_generative_baseline["model"]["name"],
            "local_generative_baseline_model_digest": local_generative_baseline["model"]["digest"],
            "local_generative_baseline_case_count": local_generative_baseline["case_count"],
            "local_generative_baseline_first_pass_contract_rate": local_generative_baseline["first_pass_hard_contract_pass_rate"],
            "local_generative_baseline_final_contract_rate": local_generative_baseline["final_hard_contract_pass_rate"],
            "local_generative_baseline_repair_call_count": local_generative_baseline["repair_call_count"],
            "local_generative_baseline_wrapper_normalization_count": local_generative_baseline["deterministic_wrapper_normalization_count"],
            "local_generative_baseline_training_observed": local_generative_baseline["training_observed"],
            "local_generative_baseline_cloud_api_calls": local_generative_baseline["cloud_api_calls"],
            "local_generative_baseline_download_performed": local_generative_baseline["network_download_performed"],
            "local_gemma3_strategy_probe_model": local_gemma_strategy_probe[
                "execution"
            ]["model_id"],
            "local_gemma3_strategy_probe_download_performed": local_gemma_strategy_probe[
                "execution"
            ]["network_download_performed"],
            "local_gemma3_strategy_probe_cloud_api_calls": local_gemma_strategy_probe[
                "execution"
            ]["cloud_api_calls"],
            "local_gemma3_strategy_probe_training_observed": local_gemma_strategy_probe[
                "execution"
            ]["training_observed"],
            "local_gemma3_strategy_probe_draft_accepted": local_gemma_strategy_probe[
                "draft"
            ]["harness"]["accepted"],
            "local_gemma3_strategy_probe_repair_accepted": local_gemma_strategy_probe[
                "bounded_repair"
            ]["accepted"],
            "local_gemma3_strategy_challenger_model": local_gemma_strategy_challenger[
                "execution"
            ]["model_id"],
            "local_gemma3_strategy_challenger_revision": local_gemma_strategy_challenger[
                "execution"
            ]["model_revision"],
            "local_gemma3_strategy_challenger_manifest_sha256": local_gemma_strategy_challenger[
                "execution"
            ]["model_manifest_sha256"],
            "local_gemma3_strategy_challenger_accepted": local_gemma_strategy_challenger[
                "accepted"
            ],
            "local_gemma3_strategy_challenger_attempt_count": len(
                local_gemma_strategy_challenger["attempts"]
            ),
            "local_gemma3_strategy_challenger_candidate_sha256": (
                local_gemma_strategy_challenger["accepted_candidate"]["content_sha256"]
                if local_gemma_strategy_challenger["accepted"]
                else None
            ),
            "local_gemma3_strategy_challenger_download_performed": local_gemma_strategy_challenger[
                "execution"
            ]["network_download_performed"],
            "local_gemma3_strategy_challenger_cloud_api_calls": local_gemma_strategy_challenger[
                "execution"
            ]["cloud_api_calls"],
            "local_gemma3_strategy_challenger_training_observed": local_gemma_strategy_challenger[
                "execution"
            ]["training_observed"],
            "local_gemma3_strategy_challenger_radeon_observed": local_gemma_strategy_challenger[
                "execution"
            ]["radeon_local_inference_observed"],
            "local_gemma3_strategy_challenger_automatic_release_authority": local_gemma_strategy_challenger[
                "automatic_release_authority"
            ],
            "local_gemma3_strategy_portfolio_status": local_gemma_strategy_portfolio[
                "status"
            ],
            "local_gemma3_strategy_portfolio_content_sha256": local_gemma_strategy_portfolio[
                "content_sha256"
            ],
            "local_gemma3_strategy_portfolio_case_count": local_gemma_strategy_portfolio[
                "case_count"
            ],
            "local_gemma3_strategy_portfolio_accepted_case_count": local_gemma_strategy_portfolio[
                "accepted_case_count"
            ],
            "local_gemma3_strategy_portfolio_all_cases_accepted": local_gemma_strategy_portfolio[
                "all_cases_accepted"
            ],
            "local_gemma3_strategy_portfolio_model_load_count": local_gemma_strategy_portfolio[
                "execution"
            ]["model_load_count"],
            "local_gemma3_strategy_portfolio_download_performed": local_gemma_strategy_portfolio[
                "execution"
            ]["network_download_performed"],
            "local_gemma3_strategy_portfolio_cloud_api_calls": local_gemma_strategy_portfolio[
                "execution"
            ]["cloud_api_calls"],
            "local_gemma3_strategy_portfolio_training_observed": local_gemma_strategy_portfolio[
                "execution"
            ]["training_observed"],
            "local_gemma3_strategy_portfolio_radeon_observed": local_gemma_strategy_portfolio[
                "execution"
            ]["radeon_local_inference_observed"],
            "local_gemma3_strategy_portfolio_quality_gate_passed": local_gemma_strategy_portfolio_quality[
                "portfolio_quality_gate_passed"
            ],
            "local_gemma3_strategy_portfolio_channel_distribution": local_gemma_strategy_portfolio_quality[
                "channel_distribution"
            ],
            "local_gemma3_strategy_portfolio_unique_strategy_count": local_gemma_strategy_portfolio_quality[
                "unique_strategy_count"
            ],
            "local_gemma3_strategy_portfolio_maximum_pairwise_content_jaccard": local_gemma_strategy_portfolio_quality[
                "maximum_pairwise_content_jaccard"
            ],
            "local_gemma3_strategy_portfolio_human_preference_observed": local_gemma_strategy_portfolio_quality[
                "human_preference_observed"
            ],
            "local_gemma3_strategy_portfolio_production_effect_observed": local_gemma_strategy_portfolio_quality[
                "production_effect_observed"
            ],
            "local_gemma3_text_craft_model": local_gemma_text_craft_quality["model"][
                "model_id"
            ],
            "local_gemma3_text_craft_revision": local_gemma_text_craft_quality[
                "model"
            ]["revision"],
            "local_gemma3_text_craft_manifest_sha256": local_gemma_text_craft_quality[
                "model"
            ]["manifest_sha256"],
            "local_gemma3_text_craft_device": local_gemma_text_craft_quality["model"][
                "device_family"
            ],
            "local_gemma3_text_craft_model_load_count": local_gemma_text_craft_quality[
                "model"
            ]["model_load_count"],
            "local_gemma3_text_craft_quality_call_count": local_gemma_text_craft_quality[
                "quality_call_count"
            ],
            "local_gemma3_text_craft_advisory_pass_territory_count": sum(
                record["status"]
                in {
                    "advisory_pass_pending_human_review",
                    "repaired_advisory_pass_pending_human_review",
                }
                for record in local_gemma_text_craft_quality["quality_execution"][
                    "records"
                ]
            ),
            "local_gemma3_text_craft_repaired_candidate_count": sum(
                record["repair"] is not None
                for record in local_gemma_text_craft_quality["quality_execution"][
                    "records"
                ]
            ),
            "local_gemma3_text_craft_post_repair_review_count": sum(
                len(record["post_repair_reviews"])
                for record in local_gemma_text_craft_quality["quality_execution"][
                    "records"
                ]
            ),
            "local_gemma3_text_craft_all_territories_advisory_pass": local_gemma_text_craft_quality[
                "quality_execution"
            ]["all_territories_advisory_pass"],
            "local_gemma3_text_craft_network_download_performed": local_gemma_text_craft_quality[
                "network_download_performed"
            ],
            "local_gemma3_text_craft_cloud_api_calls": local_gemma_text_craft_quality[
                "cloud_api_calls"
            ],
            "local_gemma3_text_craft_blind_human_review_completed": local_gemma_text_craft_quality[
                "blind_human_review_completed"
            ],
            "local_gemma3_text_craft_production_effect_observed": local_gemma_text_craft_quality[
                "production_effect_observed"
            ],
            "gtm_cockpit_schema_present": "ProofLaunchGTMCockpitV1" in runtime_source,
            "gtm_cockpit_tenant_scoped_api_present": (
                "/gtm-cockpit" in production_api_source
                and "self._require_run_tenant(match.group(1), tenant_id)"
                in production_api_source
            ),
            "gtm_cockpit_browser_digest_verified": (
                "computedDigest === suppliedDigest" in web_app_source
                and "stableJsonValue(unsigned)" in web_app_source
            ),
            "gtm_cockpit_operator_route_present": (
                'data-route="/control/gtm-cockpit"' in web_index_source
                and '["/control/gtm-cockpit",' in web_app_source
            ),
            "gtm_cockpit_automatic_external_action_enabled": False,
            "gtm_cockpit_four_a_effect_claim_eligible": False,
            "gtm_cockpit_top1_claim_eligible": False,
            "local_gtm_mission_status": local_gtm_mission["status"],
            "local_gtm_mission_run_id": local_gtm_mission["run_id"],
            "local_gtm_mission_graph_loop_harness_executed": local_gtm_mission[
                "graph_loop_harness_executed"
            ],
            "local_gtm_mission_human_release_gate_reached": local_gtm_mission[
                "human_release_gate_reached"
            ],
            "local_gtm_mission_model": local_gtm_mission["local_model"]["name"],
            "local_gtm_mission_model_digest": local_gtm_mission["local_model"][
                "digest"
            ],
            "local_gtm_mission_completed_model_calls": local_gtm_mission[
                "text_challenger"
            ]["completed_call_count"],
            "local_gtm_mission_validated_candidate_count": local_gtm_mission[
                "text_challenger"
            ]["candidate_count"],
            "local_gtm_mission_blind_pair_count": local_gtm_mission[
                "text_challenger"
            ]["blind_pair_count"],
            "local_gtm_mission_empty_human_review_task_count": local_gtm_mission[
                "text_challenger"
            ]["human_review_task_count"],
            "local_gtm_mission_cloud_api_calls": local_gtm_mission[
                "cloud_api_calls"
            ],
            "local_gtm_mission_download_performed": local_gtm_mission[
                "network_download_performed"
            ],
            "local_gtm_mission_human_review_completed": local_gtm_mission[
                "blind_review_completed"
            ],
            "local_gtm_mission_winner_selected": local_gtm_mission[
                "winner_selected"
            ],
            "local_gtm_mission_live_human_review_submitted_count": blind_review_status[
                "submitted_review_count"
            ],
            "local_gtm_mission_live_human_review_complete": blind_review_status[
                "review_complete"
            ],
            "local_gtm_mission_multimodal_production_entry_created": blind_review_status[
                "multimodal_production_entry_created"
            ],
            "local_gtm_mission_post_selection_compiler_ready": True,
            "local_gtm_mission_post_selection_compiler_lane_count": 4,
            "local_gtm_mission_post_selection_compiler_automatic_gpu_execution_enabled": False,
            "local_gtm_mission_omnichannel_compiler_ready": True,
            "local_gtm_mission_omnichannel_compiler_lane_count": 9,
            "local_gtm_mission_omnichannel_activation_observed": blind_review_status[
                "omnichannel_activation_plan_created"
            ],
            "local_gtm_mission_omnichannel_automatic_external_action_enabled": False,
            "frontier_free_api_candidate_count": len([
                item for item in frontier_panel["candidates"]
                if item["access_class"] == "zero_cost_rate_limited"
            ]),
            "frontier_free_api_live_calls_executed": frontier_free_sprint["live_calls_executed"],
            "frontier_free_api_paid_routes_enabled": frontier_free_sprint[
                "paid_routes_enabled"
            ],
            "frontier_free_api_external_output_release_authority": frontier_free_sprint[
                "external_output_release_authority"
            ],
            "frontier_free_api_external_output_training_admitted": frontier_free_sprint[
                "external_output_training_admitted"
            ],
            "frontier_free_compute_route_count": len(frontier_panel["free_compute_matrix"]),
            "frontier_free_cloud_api_roles_ready": free_cloud_execution_plan[
                "ready_api_role_count"
            ],
            "frontier_free_cloud_selected_api_candidate_count": free_cloud_execution_plan[
                "selected_api_candidate_count"
            ],
            "frontier_free_cloud_selected_weight_training_route": free_cloud_execution_plan[
                "selected_weight_training_route"
            ],
            "frontier_free_cloud_paid_fallback_enabled": free_cloud_execution_plan[
                "paid_fallback_enabled"
            ],
            "local_creative_benchmark_status": local_creative_benchmark["status"],
            "local_creative_benchmark_blocker": local_creative_benchmark.get(
                "blocker"
            ),
            "local_creative_benchmark_active_case_id": local_creative_benchmark.get(
                "active_case_id"
            ),
            "local_creative_benchmark_preflight_passed": local_creative_benchmark[
                "preflight"
            ]["passed"],
            "local_creative_benchmark_planned_case_count": local_creative_benchmark[
                "planned_case_count"
            ],
            "local_creative_benchmark_observed_case_count": local_creative_benchmark.get(
                "observed_case_count", 0
            ),
            "local_creative_benchmark_completed_case_count": local_creative_benchmark[
                "completed_case_count"
            ],
            "local_creative_benchmark_planned_model_call_count": local_creative_benchmark[
                "planned_model_call_count"
            ],
            "local_creative_benchmark_completed_model_call_count": local_creative_benchmark[
                "completed_model_call_count"
            ],
            "local_creative_benchmark_validated_candidate_count": local_creative_benchmark[
                "validated_candidate_count"
            ],
            "local_creative_benchmark_cloud_api_calls": local_creative_benchmark[
                "cloud_api_calls"
            ],
            "local_creative_benchmark_training_observed": local_creative_benchmark[
                "training_observed"
            ],
            "local_creative_benchmark_radeon_local_inference_observed": local_creative_benchmark[
                "radeon_local_inference_observed"
            ],
            "local_creative_effect_gate_passed": local_creative_effect_audit[
                "final_gate"
            ]["passed"],
            "local_creative_effect_case_count": local_creative_effect_audit[
                "final_gate"
            ]["observed_case_count"],
            "local_creative_effect_candidate_count": local_creative_effect_audit[
                "final_gate"
            ]["observed_candidate_count"],
            "local_creative_effect_channel_draft_count": local_creative_effect_audit[
                "final_gate"
            ]["observed_channel_draft_count"],
            "local_creative_effect_channel_type_count": local_creative_effect_audit[
                "final_gate"
            ]["covered_channel_type_count"],
            "local_creative_effect_maximum_pair_jaccard": local_creative_effect_audit[
                "final_gate"
            ]["maximum_cross_scenario_pair_jaccard"],
            "local_creative_effect_human_preference_observed": local_creative_effect_audit[
                "final_gate"
            ]["exact_human_preference_observed"],
            "local_portfolio_blind_review_status": local_portfolio_blind_review[
                "status"
            ],
            "judge_calibration_protocol_present": (
                "ProofLaunchJudgeCalibrationPublicV1"
                in (
                    PROJECT_ROOT
                    / "src/prooflaunch_remix/gtm_judge_calibration.py"
                ).read_text(encoding="utf-8")
            ),
            "judge_calibration_minimum_distinct_case_count": 100,
            "judge_calibration_humans_per_case": 3,
            "judge_calibration_first_queue_expected_label_count": 300,
            "judge_calibration_queue_ready": (
                local_judge_calibration_queue["observed_model_call_count"] == 100
                and local_judge_calibration_queue["expected_human_label_count"] == 300
            ),
            "judge_calibration_observed_local_model_call_count": local_judge_calibration_queue[
                "observed_model_call_count"
            ],
            "judge_calibration_local_model_name": local_judge_calibration_queue["model"][
                "name"
            ],
            "judge_calibration_local_model_digest": local_judge_calibration_queue["model"][
                "digest"
            ],
            "judge_calibration_prediction_positive_count": local_judge_calibration_queue[
                "judge_prediction_positive_count"
            ],
            "judge_calibration_prediction_negative_count": local_judge_calibration_queue[
                "judge_prediction_negative_count"
            ],
            "judge_calibration_real_human_label_count": local_judge_calibration_queue[
                "real_human_label_count"
            ],
            "judge_calibration_tpr_observed": False,
            "judge_calibration_tnr_observed": False,
            "judge_calibration_passed": local_judge_calibration_queue[
                "judge_calibrated"
            ],
            "judge_calibration_automatic_promotion_enabled": local_judge_calibration_queue[
                "automatic_judge_promotion_enabled"
            ],
            "judge_calibration_cloud_api_calls": local_judge_calibration_queue[
                "cloud_api_calls"
            ],
            "judge_calibration_radeon_local_inference": local_judge_calibration_queue[
                "model"
            ]["radeon_local_inference"],
            "local_portfolio_blind_review_public_packet_sha256": local_portfolio_blind_review[
                "public_packet_content_sha256"
            ],
            "local_portfolio_blind_review_case_count": local_portfolio_blind_review[
                "case_count"
            ],
            "local_portfolio_blind_review_pair_count": local_portfolio_blind_review[
                "pair_count"
            ],
            "local_portfolio_blind_review_reviewer_slot_count": local_portfolio_blind_review[
                "reviewer_slot_count"
            ],
            "local_portfolio_blind_review_expected_review_count": local_portfolio_blind_review[
                "expected_review_count"
            ],
            "local_portfolio_blind_review_submitted_review_count": local_portfolio_blind_review[
                "submitted_review_count"
            ],
            "local_portfolio_blind_review_complete": local_portfolio_blind_review[
                "review_complete"
            ],
            "local_portfolio_blind_review_promotion_passed": local_portfolio_blind_review[
                "portfolio_promotion_passed"
            ],
            "local_portfolio_blind_review_human_preference_observed": local_portfolio_blind_review[
                "human_preference_observed"
            ],
            "local_portfolio_blind_review_runtime_api_present": True,
            "local_portfolio_blind_review_runtime_expected_review_count": portfolio_blind_review_runtime_status[
                "expected_review_count"
            ],
            "local_portfolio_blind_review_runtime_submitted_review_count": portfolio_blind_review_runtime_status[
                "submitted_review_count"
            ],
            "local_portfolio_blind_review_runtime_automatic_winner_selection_enabled": portfolio_blind_review_runtime_status[
                "automatic_winner_selection_enabled"
            ],
            "agentic_product_readiness_audit_sha256": agentic_product_readiness[
                "content_sha256"
            ],
            "agentic_product_readiness_passed_item_count": agentic_product_readiness[
                "passed_item_count"
            ],
            "agentic_product_readiness_gap_item_count": agentic_product_readiness[
                "gap_item_count"
            ],
            "agentic_product_enterprise_production_ready": False,
            "tool_execution_sandbox_adapter_present": True,
            "tool_execution_sandbox_observed": tool_sandbox_receipt is not None,
            "tool_execution_sandbox_runtime_passed": bool(
                tool_sandbox_receipt and tool_sandbox_receipt["passed"]
            ),
            "tool_execution_sandbox_network_egress_blocked": bool(
                tool_sandbox_receipt
                and tool_sandbox_receipt["probes"]["dns_egress_blocked"]
                and tool_sandbox_receipt["probes"]["tcp_egress_blocked"]
            ),
            "tool_execution_sandbox_filesystem_escape_blocked": bool(
                tool_sandbox_receipt
                and tool_sandbox_receipt["probes"]["root_filesystem_write_blocked"]
                and tool_sandbox_receipt["probes"]["filesystem_escape_blocked"]
            ),
            "tool_execution_sandbox_secret_boundary_passed": bool(
                tool_sandbox_receipt
                and tool_sandbox_receipt["secret_boundary"][
                    "mounted_at_tool_boundary"
                ]
                and tool_sandbox_receipt["secret_boundary"]["readable_by_tool"]
                and not tool_sandbox_receipt["secret_boundary"][
                    "present_in_environment"
                ]
                and not tool_sandbox_receipt["secret_boundary"][
                    "present_in_job_context"
                ]
                and not tool_sandbox_receipt["secret_boundary"][
                    "persisted_in_receipt"
                ]
            ),
            "gtm_context_quality_sha256": gtm_context_quality["content_sha256"],
            "gtm_context_observed_local_call_count": gtm_context_quality[
                "observed_local_call_count"
            ],
            "gtm_context_median_utilization": gtm_context_quality[
                "median_context_utilization"
            ],
            "gtm_context_p95_utilization": gtm_context_quality[
                "p95_context_utilization"
            ],
            "gtm_context_utilization_gate_passed": gtm_context_quality[
                "context_utilization_gate_passed"
            ],
            "gtm_long_session_eval_count": gtm_context_quality[
                "long_session_eval_count"
            ],
            "gtm_long_session_compaction_gate_passed": gtm_context_quality[
                "long_session_compaction_gate_passed"
            ],
            "gtm_context_quality_new_model_calls": gtm_context_quality[
                "new_model_calls"
            ],
            "production_guardrail_eval_sha256": production_guardrail_eval[
                "content_sha256"
            ],
            "production_guardrail_eval_case_count": production_guardrail_eval[
                "case_count"
            ],
            "production_guardrail_attack_recall": production_guardrail_eval[
                "attack_recall"
            ],
            "production_guardrail_false_block_rate": production_guardrail_eval[
                "false_block_rate"
            ],
            "production_guardrail_escape_count": production_guardrail_eval[
                "escape_count"
            ],
            "production_guardrail_api_boundary_enforced": production_guardrail_eval[
                "api_boundary_enforced"
            ],
            "production_guardrail_deployment_observed": production_guardrail_eval[
                "production_deployment_observed"
            ],
            "production_trace_retention_sha256": production_trace_retention[
                "content_sha256"
            ],
            "production_trace_retention_days": production_trace_retention[
                "retention_days"
            ],
            "production_trace_local_restart_smoke_observed": production_trace_retention[
                "local_restart_smoke_observed"
            ],
            "production_trace_hash_chain_valid": production_trace_retention[
                "hash_chain_valid"
            ],
            "production_trace_valid_request_boundary_instrumented": production_trace_retention[
                "valid_request_boundary_instrumented"
            ],
            "production_trace_raw_content_retained": production_trace_retention[
                "raw_content_retained"
            ],
            "production_trace_remote_required_check_observed": production_trace_retention[
                "remote_required_check_observed"
            ],
            "production_trace_deployment_observed": production_trace_retention[
                "production_deployment_observed"
            ],
            "local_agentic_api_soak_sha256": local_agentic_api_soak[
                "content_sha256"
            ],
            "local_agentic_api_soak_case_count": local_agentic_api_soak[
                "execution"
            ]["accepted_run_count"],
            "local_agentic_api_soak_awaiting_human_release_count": (
                local_agentic_api_soak["execution"][
                    "awaiting_human_release_count"
                ]
            ),
            "local_agentic_api_soak_restart_recovery_passed": (
                local_agentic_api_soak["execution"][
                    "durable_run_recovered_after_restart"
                ]
            ),
            "local_agentic_api_soak_trace_count": local_agentic_api_soak[
                "trace_ledger"
            ]["request_trace_count"],
            "local_agentic_api_soak_trace_hash_chain_valid": (
                local_agentic_api_soak["trace_ledger"]["hash_chain_valid"]
            ),
            "local_agentic_api_soak_external_calls": local_agentic_api_soak[
                "execution"
            ]["external_model_api_calls"],
            "local_agentic_api_soak_external_actions": local_agentic_api_soak[
                "execution"
            ]["external_publish_or_send_actions"],
            "local_agentic_api_soak_production_observed": local_agentic_api_soak[
                "truth_boundary"
            ]["production_deployment_observed"],
            "local_cached_model_count": (
                len(local_cloud_resources["ollama_models"])
                + len(local_cloud_resources["huggingface_cached_models"])
            ),
            "local_multimodal_role_coverage": local_cloud_resources["local_role_coverage"],
            "local_model_download_performed": local_cloud_resources["download_performed"],
            "hybrid_quality_control_content_sha256": hybrid_quality_control[
                "content_sha256"
            ],
            "hybrid_quality_control_category_count": hybrid_quality_control[
                "portfolio"
            ]["category_count"],
            "hybrid_quality_control_job_count": hybrid_quality_control["portfolio"][
                "job_count"
            ],
            "hybrid_quality_control_local_ready_category_count": hybrid_quality_control[
                "portfolio"
            ]["local_ready_category_count"],
            "hybrid_quality_control_challenger_dossier_count_admitted": hybrid_quality_control[
                "portfolio"
            ]["challenger_dossier_count_admitted"],
            "hybrid_quality_control_cloud_api_role_count_ready": hybrid_quality_control[
                "portfolio"
            ]["cloud_api_role_count_ready"],
            "hybrid_quality_control_local_runtime_blocked_by_cloud": hybrid_quality_control[
                "portfolio"
            ]["product_local_runtime_blocked_by_cloud"],
            "hybrid_quality_control_hardware_and_provider_are_replaceable": hybrid_quality_control[
                "routing_invariants"
            ]["hardware_and_provider_are_replaceable"],
            "hybrid_quality_control_jobs_route_by_capability_not_vendor": hybrid_quality_control[
                "routing_invariants"
            ]["jobs_route_by_capability_not_vendor"],
            "hybrid_quality_control_local_pipeline_continues_without_cloud": hybrid_quality_control[
                "routing_invariants"
            ]["local_pipeline_continues_without_cloud"],
            "hybrid_quality_control_cloud_gpu_is_runtime_dependency": not hybrid_quality_control[
                "routing_invariants"
            ]["cloud_gpu_is_quality_accelerator_not_product_runtime_dependency"],
            "hybrid_quality_control_radeon_required_for_product_closure": hybrid_quality_control[
                "routing_invariants"
            ]["radeon_required_for_product_closure"],
            "hybrid_quality_control_model_judge_can_promote": hybrid_quality_control[
                "routing_invariants"
            ]["model_judge_can_promote"],
            "hybrid_quality_control_human_release_required": hybrid_quality_control[
                "routing_invariants"
            ]["human_release_required"],
            "omnichannel_craft_playbook_count": len(
                hybrid_quality_control["lanes"]
            ),
            "omnichannel_craft_distinct_playbook_count": len(
                {
                    lane["specialist_craft_playbook"]["content_sha256"]
                    for lane in hybrid_quality_control["lanes"]
                }
            ),
            "omnichannel_craft_work_order_count": sum(
                lane["specialist_craft_playbook"]["work_order_count"]
                for lane in hybrid_quality_control["lanes"]
            ),
            "omnichannel_craft_skill_assignment_count": sum(
                lane["specialist_craft_playbook"][
                    "selected_atomic_skill_assignment_count"
                ]
                for lane in hybrid_quality_control["lanes"]
            ),
            "omnichannel_craft_job_binding_count": sum(
                "specialist_craft_job_binding" in job
                for job in hybrid_quality_control["jobs"]
            ),
            "omnichannel_craft_automatic_external_action_count": sum(
                job["specialist_craft_job_binding"][
                    "automatic_external_action_count"
                ]
                for job in hybrid_quality_control["jobs"]
            ),
            "adaptive_capability_graph_content_sha256": adaptive_capability_graph[
                "content_sha256"
            ],
            "adaptive_capability_graph_public_content_sha256": adaptive_capability_graph_public[
                "content_sha256"
            ],
            "adaptive_capability_graph_context_count": adaptive_capability_graph[
                "coverage"
            ]["context_count"],
            "adaptive_capability_graph_lane_decision_count": adaptive_capability_graph[
                "coverage"
            ]["lane_decision_count"],
            "adaptive_capability_graph_distinct_lane_state_profiles": adaptive_capability_graph[
                "coverage"
            ]["distinct_lane_state_profiles"],
            "adaptive_capability_graph_zero_budget_paid_activation_count": adaptive_capability_graph[
                "coverage"
            ]["zero_budget_paid_activation_count"],
            "adaptive_capability_graph_regulated_missing_specialist_gate_count": adaptive_capability_graph[
                "coverage"
            ]["regulated_missing_specialist_gate_count"],
            "adaptive_capability_graph_automatic_external_action_count": adaptive_capability_graph[
                "coverage"
            ]["automatic_external_action_count"],
            "adaptive_capability_graph_hardware_in_plan_identity": adaptive_capability_graph[
                "executor_binding"
            ]["included_in_plan_identity"],
            "adaptive_capability_plan_embedded_in_run_strategy": (
                '"adaptive_capability_plan"' in runtime_source
                and "compile_adaptive_context" in runtime_source
            ),
            "adaptive_capability_plan_exposed_in_gtm_cockpit": (
                '"adaptive_lane_states"' in runtime_source
                and "adaptive_focus_lanes" in runtime_source
                and "adaptive_focus_lanes" in web_app_source
            ),
            "adaptive_capability_plan_runtime_test": (
                "tests.test_v10_submission_runtime.ProductionAgentRuntimeTests."
                "test_owner_attested_strategy_is_draft_unverified_and_not_durable_memory"
            ),
            "creative_alpha_embedded_in_text_challenger": (
                '"creative_alpha_plan"' in runtime_source
                and "compile_creative_alpha_plan" in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_text_challenger.py"
                ).read_text(encoding="utf-8")
            ),
            "creative_alpha_exposed_in_gtm_cockpit": (
                "creative_alpha_plan_sha256" in runtime_source
                and "creative_alpha_style_ids" in web_app_source
            ),
            "creative_alpha_runtime_test": (
                "tests.test_v10_submission_runtime.ProductionAgentRuntimeTests."
                "test_preview_exposes_text_challenger_status_without_claiming_generation"
            ),
            "creative_alpha_distinct_style_binding_present": (
                '"assigned_style"' in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_text_challenger.py"
                ).read_text(encoding="utf-8")
                and "territories lack distinct creative-alpha style bindings" in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_text_challenger.py"
                ).read_text(encoding="utf-8")
            ),
            "creative_alpha_market_surface_platform_runtime_bound": (
                '"product_category"' in runtime_source
                and '"product_surface"' in runtime_source
                and '"distribution_platform"' in runtime_source
            ),
            "creative_alpha_bounded_self_evolution_present": (
                '"self_evolution_contract"' in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_creative_alpha.py"
                ).read_text(encoding="utf-8")
                and '"current_run_mutation_allowed": False' in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_creative_alpha.py"
                ).read_text(encoding="utf-8")
            ),
            "creative_alpha_market_surface_runtime_test": (
                "tests.test_v10_submission_runtime.ProductionAgentRuntimeTests."
                "test_product_category_surface_persona_and_timing_reach_real_creative_plan"
            ),
            "market_language_contract_runtime_bound": (
                '"market_language_contract"' in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_creative_alpha.py"
                ).read_text(encoding="utf-8")
                and '"audience_role"' in runtime_source
                and "market_language_signature_sha256" in runtime_source
                and "market_language_primary_role" in web_app_source
            ),
            "market_language_matrix_content_sha256": market_language_matrix[
                "content_sha256"
            ],
            "market_language_matrix_total_case_count": market_language_matrix[
                "coverage"
            ]["total_case_count"],
            "market_language_matrix_distinct_signature_count": market_language_matrix[
                "coverage"
            ]["distinct_language_signature_count"],
            "market_language_matrix_zero_budget_paid_activation_count": market_language_matrix[
                "coverage"
            ]["zero_budget_paid_activation_count"],
            "market_language_matrix_automatic_external_action_count": market_language_matrix[
                "coverage"
            ]["automatic_external_action_count"],
            "market_language_matrix_owner_confirmation_complete": (
                market_language_matrix["coverage"][
                    "missing_owner_confirmation_count"
                ]
                == 0
            ),
            "market_language_matrix_runtime_test": (
                "tests.test_gtm_market_language.MarketLanguageTests."
                "test_full_market_language_matrix_is_exact_distinct_and_action_free"
            ),
            "gtm_team_capability_contract_runtime_bound": (
                '"gtm_team_capability_contract"' in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_creative_alpha.py"
                ).read_text(encoding="utf-8")
                and "gtm_team_capability_contract_sha256" in runtime_source
                and "gtm_team_active_role_ids" in web_app_source
            ),
            "gtm_team_reference_cohort_status": team_capability_matrix[
                "reference_cohorts"
            ]["status"],
            "gtm_team_reference_company_count": sum(
                len(rows)
                for rows in team_capability_matrix["reference_cohorts"][
                    "cohorts"
                ].values()
            ),
            "gtm_team_role_count": team_capability_matrix[
                "role_skill_registry"
            ]["role_count"],
            "gtm_team_skills_per_role": team_capability_matrix[
                "role_skill_registry"
            ]["skills_per_role"],
            "gtm_team_atomic_skill_count": team_capability_matrix[
                "role_skill_registry"
            ]["atomic_skill_count"],
            "gtm_team_staffing_context_count": team_capability_matrix[
                "coverage"
            ]["staffing_context_count"],
            "gtm_team_distinct_contract_count": team_capability_matrix[
                "coverage"
            ]["distinct_contract_count"],
            "gtm_team_activated_role_count": team_capability_matrix[
                "coverage"
            ]["activated_role_count"],
            "gtm_team_automatic_external_action_count": team_capability_matrix[
                "coverage"
            ]["automatic_external_action_count"],
            "gtm_team_capability_matrix_content_sha256": team_capability_matrix[
                "content_sha256"
            ],
            "gtm_team_capability_matrix_test": (
                "tests.test_gtm_team_capability_os.GTMTeamCapabilityTests."
                "test_sealed_staffing_matrix_covers_all_roles_and_contexts"
            ),
            "gtm_craft_handoff_matrix_content_sha256": craft_handoff_matrix[
                "content_sha256"
            ],
            "gtm_craft_handoff_context_count": craft_handoff_matrix["coverage"][
                "context_count"
            ],
            "gtm_craft_handoff_territory_count": craft_handoff_matrix["coverage"][
                "territory_handoff_count"
            ],
            "gtm_craft_handoff_work_order_count": craft_handoff_matrix["coverage"][
                "total_work_order_count"
            ],
            "gtm_craft_handoff_skill_assignment_count": craft_handoff_matrix[
                "coverage"
            ]["selected_atomic_skill_assignment_count"],
            "gtm_craft_handoff_professional_axis_assignment_count": craft_handoff_matrix[
                "coverage"
            ]["professional_axis_assignment_count"],
            "gtm_craft_handoff_surface_specialist_lens_assignment_count": craft_handoff_matrix[
                "coverage"
            ]["surface_specialist_lens_assignment_count"],
            "gtm_craft_handoff_unconventional_edge_play_binding_count": craft_handoff_matrix[
                "coverage"
            ]["unconventional_edge_play_binding_count"],
            "gtm_craft_handoff_review_separation_pass_count": craft_handoff_matrix[
                "coverage"
            ]["producer_reviewer_separation_pass_count"],
            "gtm_craft_handoff_automatic_external_action_count": craft_handoff_matrix[
                "coverage"
            ]["automatic_external_action_count"],
            "gtm_craft_handoff_matrix_test": (
                "tests.test_gtm_craft_handoff_matrix.GTMCraftHandoffMatrixTests."
                "test_matrix_quantifies_real_work_orders_not_only_role_inventory"
            ),
            "gtm_human_capability_kernel_content_sha256": human_capability_kernel[
                "content_sha256"
            ],
            "gtm_human_capability_role_count": human_capability_kernel["coverage"][
                "role_count"
            ],
            "gtm_human_capability_skill_card_count": human_capability_kernel[
                "coverage"
            ]["professional_skill_card_count"],
            "gtm_human_capability_professional_axis_count": human_capability_kernel[
                "coverage"
            ]["professional_axis_count"],
            "gtm_human_capability_eval_check_count": human_capability_kernel[
                "coverage"
            ]["eval_check_count"],
            "gtm_human_capability_kpi_binding_count": human_capability_kernel[
                "coverage"
            ]["kpi_binding_count"],
            "gtm_human_capability_surface_count": human_capability_kernel[
                "coverage"
            ]["surface_count"],
            "gtm_human_capability_surface_specialist_lens_count": human_capability_kernel[
                "coverage"
            ]["surface_specialist_lens_count"],
            "gtm_human_capability_unconventional_edge_play_card_count": human_capability_kernel[
                "coverage"
            ]["unconventional_edge_play_card_count"],
            "gtm_human_capability_automatic_external_action_count": human_capability_kernel[
                "coverage"
            ]["automatic_external_action_count"],
            "gtm_human_capability_runtime_work_order_binding_present": (
                "selected_professional_skill_card_ids" in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_craft_handoff.py"
                ).read_text(encoding="utf-8")
                and "surface_specialist_lens_ids" in (
                    PROJECT_ROOT / "src/prooflaunch_remix/gtm_craft_handoff.py"
                ).read_text(encoding="utf-8")
            ),
            "gtm_human_capability_structural_coverage_is_effect_evidence": human_capability_kernel[
                "promotion_gate"
            ]["structural_coverage_is_effect_evidence"],
            "gtm_human_capability_comparative_superiority_claim_allowed_now": human_capability_kernel[
                "promotion_gate"
            ]["comparative_superiority_claim_allowed_now"],
            "gtm_human_capability_kernel_test": (
                "tests.test_gtm_human_capability_kernel.GTMHumanCapabilityKernelTests."
                "test_ten_x_detail_is_exact_execution_and_eval_coverage"
            ),
            "local_multimodal_qualification_content_sha256": (
                local_multimodal_qualification["content_sha256"]
            ),
            "local_multimodal_qualification_inference_observed": (
                local_multimodal_qualification["execution"][
                    "local_model_inference_observed"
                ]
            ),
            "local_multimodal_qualification_cloud_api_calls": (
                local_multimodal_qualification["execution"]["cloud_api_calls"]
            ),
            "local_multimodal_qualification_network_downloads": (
                local_multimodal_qualification["execution"]["network_downloads"]
            ),
            "local_multimodal_speech_delivery_spec_passed": (
                local_multimodal_qualification["quality_gates"][
                    "speech_48khz_stereo_24bit_delivery"
                ]
            ),
            "local_multimodal_speech_human_review_passed": (
                local_multimodal_qualification["quality_gates"][
                    "speech_named_human_listening_review"
                ]
            ),
            "local_multimodal_video_subject_recognizable": (
                local_multimodal_qualification["quality_gates"][
                    "video_subject_recognizable_after_bounded_repair"
                ]
            ),
            "local_multimodal_video_delivery_gate_passed": (
                local_multimodal_qualification["quality_gates"][
                    "video_delivery_gate_passed"
                ]
            ),
            "local_multimodal_product_admission_passed": (
                local_multimodal_qualification["quality_gates"][
                    "product_admission_passed"
                ]
            ),
            "local_multimodal_qualification_playable_api_present": True,
            "local_campaign_pack_content_sha256": local_campaign_pack[
                "content_sha256"
            ],
            "local_campaign_pack_source_model": local_campaign_pack[
                "source_generation"
            ]["model"],
            "local_campaign_pack_source_accelerator": local_campaign_pack[
                "source_generation"
            ]["accelerator"],
            "local_campaign_pack_cloud_api_calls": local_campaign_pack[
                "source_generation"
            ]["cloud_api_calls"],
            "local_campaign_pack_network_downloads": local_campaign_pack[
                "source_generation"
            ]["network_downloads"],
            "local_campaign_pack_artifact_count": len(local_campaign_pack["artifacts"]),
            "local_campaign_pack_true_4k_geometry": local_campaign_pack[
                "quality_gates"
            ]["hero_true_4k_geometry"],
            "local_campaign_pack_mechanical_ready": local_campaign_pack[
                "quality_gates"
            ]["mechanical_campaign_pack_ready"],
            "local_campaign_pack_named_human_review_passed": local_campaign_pack[
                "quality_gates"
            ]["named_human_blind_review_passed"],
            "local_campaign_pack_four_a_preference_proven": local_campaign_pack[
                "quality_gates"
            ]["four_a_preference_proven"],
            "local_campaign_pack_product_admission_passed": local_campaign_pack[
                "quality_gates"
            ]["product_admission_passed"],
            "local_campaign_pack_playable_api_present": True,
            "local_campaign_pack_visual_blind_review_api_present": True,
            "local_campaign_pack_visual_offline_review_kit_available": (
                campaign_pack_blind_review_status["offline_review_kit_available"]
            ),
            "local_campaign_pack_visual_offline_review_kit_invitation_bound": (
                campaign_pack_blind_review_status[
                    "offline_review_kit_invitation_bound"
                ]
            ),
            "local_campaign_pack_visual_offline_review_kit_contains_token": (
                campaign_pack_blind_review_status[
                    "offline_review_kit_contains_invitation_token"
                ]
            ),
            "local_campaign_pack_visual_offline_review_network_submission_enabled": (
                campaign_pack_blind_review_status[
                    "offline_review_kit_network_submission_enabled"
                ]
            ),
            "local_campaign_pack_visual_blind_review_public_packet_sha256": (
                campaign_pack_blind_review_status["public_packet_sha256"]
            ),
            "local_campaign_pack_visual_blind_review_expected_review_count": (
                campaign_pack_blind_review_status["expected_review_count"]
            ),
            "local_campaign_pack_visual_blind_review_submitted_review_count": (
                campaign_pack_blind_review_status["submitted_review_count"]
            ),
            "local_campaign_pack_visual_blind_review_complete": (
                campaign_pack_blind_review_status["review_complete"]
            ),
            "local_campaign_pack_visual_human_preference_observed": (
                campaign_pack_blind_review_status["human_preference_observed"]
            ),
            "local_campaign_pack_visual_promotion_recommendation_eligible": (
                campaign_pack_blind_review_status[
                    "promotion_recommendation_eligible"
                ]
            ),
            "local_campaign_pack_visual_automatic_runtime_switch_enabled": (
                campaign_pack_blind_review_status[
                    "automatic_runtime_switch_enabled"
                ]
            ),
            "local_campaign_pack_visual_automatic_publish_enabled": (
                campaign_pack_blind_review_status["automatic_publish_enabled"]
            ),
            "local_campaign_pack_visual_product_admission_passed": (
                campaign_pack_blind_review_status["product_admission_passed"]
            ),
            "local_campaign_pack_visual_four_a_preference_proven": (
                campaign_pack_blind_review_status["four_a_preference_proven"]
            ),
            "local_campaign_pack_visual_production_effect_proven": (
                campaign_pack_blind_review_status["production_effect_proven"]
            ),
            "lifecycle_closure_content_sha256": lifecycle_closure[
                "content_sha256"
            ],
            "lifecycle_closure_case_count": lifecycle_closure["case_count"],
            "lifecycle_closure_scenario_count": lifecycle_closure[
                "scenario_count"
            ],
            "lifecycle_closure_named_failure_mode_count": lifecycle_closure[
                "named_failure_mode_count"
            ],
            "lifecycle_closure_minimum_cases_per_failure_mode": lifecycle_closure[
                "minimum_cases_per_failure_mode"
            ],
            "lifecycle_closure_all_ten_capabilities_connected": lifecycle_closure[
                "all_ten_lifecycle_capabilities_connected"
            ],
            "lifecycle_closure_zero_budget_paid_channels_excluded": lifecycle_closure[
                "all_zero_budget_paid_channels_excluded"
            ],
            "lifecycle_closure_positive_paths_require_human_review": lifecycle_closure[
                "all_positive_paths_require_human_review"
            ],
            "lifecycle_closure_all_external_actions_disabled": lifecycle_closure[
                "all_external_actions_disabled"
            ],
            "lifecycle_closure_campaign_workspace_artifact_count": lifecycle_closure[
                "campaign_workspace_artifact_count"
            ],
            "lifecycle_closure_campaign_workspace_same_evidence_spine": lifecycle_closure[
                "all_campaign_workspaces_same_evidence_spine"
            ],
            "lifecycle_closure_campaign_workspace_activations_disabled": lifecycle_closure[
                "all_campaign_workspace_activations_disabled"
            ],
            "lifecycle_closure_post_selection_omnichannel_lane_count": lifecycle_closure[
                "post_selection_omnichannel_lane_count"
            ],
            "lifecycle_closure_all_post_selection_campaign_identities_bound": lifecycle_closure[
                "all_post_selection_campaign_identities_bound"
            ],
            "lifecycle_closure_all_post_selection_creative_systems_connected": lifecycle_closure[
                "all_post_selection_creative_systems_connected"
            ],
            "lifecycle_closure_all_post_selection_evidence_spines_connected": lifecycle_closure[
                "all_post_selection_evidence_spines_connected"
            ],
            "lifecycle_closure_all_post_selection_external_actions_disabled": lifecycle_closure[
                "all_post_selection_external_actions_disabled"
            ],
            "lifecycle_closure_post_selection_human_observations": lifecycle_closure[
                "post_selection_human_observations"
            ],
            "lifecycle_closure_production_outcomes_observed": lifecycle_closure[
                "production_outcomes_observed"
            ],
            "revenue_memory_demo_content_sha256": revenue_memory_demo[
                "content_sha256"
            ],
            "revenue_memory_demo_data_class": revenue_memory_demo["data_class"],
            "revenue_memory_demo_device_a_bundle_ready": (
                revenue_memory_demo["device_a"]["release_status"] == "bundle_ready"
            ),
            "revenue_memory_demo_positive_feedback_mechanics_ready": (
                revenue_memory_demo["device_a"][
                    "revenue_positive_feedback_ready"
                ]
            ),
            "revenue_memory_demo_pending_import_memory_count": (
                revenue_memory_demo["device_b"]["pending_context_memory_count"]
            ),
            "revenue_memory_demo_approved_import_memory_count": (
                revenue_memory_demo["device_b"]["frozen_context_memory_count"]
            ),
            "revenue_memory_demo_device_a_final_cockpit_closed": (
                revenue_memory_demo["device_a"]["final_cockpit_next_action_ids"]
                == ["decide_next_cycle"]
            ),
            "revenue_memory_demo_manual_publication_receipt_recorded": (
                isinstance(
                    revenue_memory_demo["device_a"].get(
                        "manual_publication_receipt_sha256"
                    ),
                    str,
                )
                and len(
                    revenue_memory_demo["device_a"][
                        "manual_publication_receipt_sha256"
                    ]
                )
                == 64
                and revenue_memory_demo["device_a"][
                    "publication_performed_by_prooflaunch"
                ]
                is False
                and revenue_memory_demo["device_a"]["platform_delivery_verified"]
                is False
            ),
            "revenue_memory_demo_device_b_next_cycle_prepared": (
                revenue_memory_demo["device_b"]["prepared_status"]
                == "awaiting_release"
                and revenue_memory_demo["device_b"][
                    "next_cycle_workspace_artifact_count"
                ]
                == 9
            ),
            "revenue_memory_demo_device_b_inherited_memory_count": (
                revenue_memory_demo["device_b"][
                    "next_cycle_inherited_memory_count"
                ]
            ),
            "revenue_memory_demo_device_b_eligible_memory_count": (
                revenue_memory_demo["device_b"][
                    "next_cycle_eligible_memory_count"
                ]
            ),
            "revenue_memory_demo_device_b_memory_application_status": (
                revenue_memory_demo["device_b"][
                    "next_cycle_memory_application_status"
                ]
            ),
            "revenue_memory_demo_device_b_memory_conflict_count": (
                revenue_memory_demo["device_b"][
                    "next_cycle_memory_conflict_count"
                ]
            ),
            "revenue_memory_demo_device_b_memory_decision_sha256": (
                revenue_memory_demo["device_b"][
                    "next_cycle_memory_decision_sha256"
                ]
            ),
            "revenue_memory_demo_device_b_memory_human_application_required": (
                revenue_memory_demo["device_b"][
                    "next_cycle_memory_human_application_required"
                ]
            ),
            "synthetic_lifecycle_demo_api_present": True,
            "synthetic_lifecycle_demo_browser_integrity_gate_present": True,
            "synthetic_lifecycle_demo_content_sha256": synthetic_lifecycle_demo[
                "content_sha256"
            ],
            "synthetic_lifecycle_demo_device_a_closed_loop": (
                synthetic_lifecycle_demo["device_a"]["run_status"] == "delivered"
                and synthetic_lifecycle_demo["device_a"]["next_best_actions"][0][
                    "id"
                ]
                == "decide_next_cycle"
            ),
            "synthetic_lifecycle_demo_device_b_inherited_cycle": (
                synthetic_lifecycle_demo["device_b"]["run_status"]
                == "awaiting_release"
                and synthetic_lifecycle_demo["device_b"]["cross_device_memory"][
                    "inherited_memory_count"
                ]
                == 1
                and synthetic_lifecycle_demo["device_b"]["cross_device_memory"][
                    "eligible_memory_count"
                ]
                == 1
                and synthetic_lifecycle_demo["device_b"]["cross_device_memory"][
                    "conflict_count"
                ]
                == 0
                and synthetic_lifecycle_demo["device_b"]["cross_device_memory"][
                    "application_status"
                ]
                == "eligible_pending_human_application"
            ),
            "gtm_capability_effect_matrix_count": synthetic_lifecycle_demo[
                "device_a"
            ]["capability_effect_matrix"]["capability_count"],
            "gtm_capability_effect_matrix_connected_count": synthetic_lifecycle_demo[
                "device_a"
            ]["capability_effect_matrix"]["contract_connected_count"],
            "gtm_capability_effect_matrix_generated_deliverable_count": synthetic_lifecycle_demo[
                "device_a"
            ]["capability_effect_matrix"]["generated_deliverable_count"],
            "gtm_capability_effect_matrix_named_human_quality_count": synthetic_lifecycle_demo[
                "device_a"
            ]["capability_effect_matrix"]["named_human_quality_count"],
            "gtm_capability_effect_matrix_production_effect_attributed_count": synthetic_lifecycle_demo[
                "device_a"
            ]["capability_effect_matrix"]["production_effect_attributed_count"],
            "gtm_capability_effect_matrix_all_effects_proven": synthetic_lifecycle_demo[
                "device_a"
            ]["capability_effect_matrix"]["all_capability_effects_proven"],
            "gtm_capability_effect_matrix_video_stage": next(
                row["evidence_stage"]
                for row in synthetic_lifecycle_demo["device_a"][
                    "capability_effect_matrix"
                ]["capabilities"]
                if row["capability_id"] == "video_generation"
            ),
            "gtm_capability_effect_matrix_audio_stage": next(
                row["evidence_stage"]
                for row in synthetic_lifecycle_demo["device_a"][
                    "capability_effect_matrix"
                ]["capabilities"]
                if row["capability_id"] == "audio_generation"
            ),
            "gtm_capability_effect_matrix_advertising_stage": next(
                row["evidence_stage"]
                for row in synthetic_lifecycle_demo["device_a"][
                    "capability_effect_matrix"
                ]["capabilities"]
                if row["capability_id"] == "advertising"
            ),
            "run_bound_multimodal_deliverable_registration_present": True,
            "run_bound_multimodal_allowed_media_types": ["audio/wav", "video/mp4"],
            "run_bound_multimodal_signature_validation_present": True,
            "run_bound_multimodal_requires_delivered_approved_run": True,
            "run_bound_multimodal_tenant_campaign_identity_bound": True,
            "run_bound_multimodal_execution_receipt_bound": True,
            "run_bound_multimodal_immutable_model_revision_required": True,
            "run_bound_multimodal_rights_confirmation_required": True,
            "run_bound_multimodal_named_human_review_separate": True,
            "run_bound_multimodal_self_attested_effect_or_4a_allowed": False,
            "run_bound_capability_deliverable_registration_present": True,
            "run_bound_capability_exact_delivered_bytes_required": True,
            "run_bound_capability_tenant_campaign_rights_bound": True,
            "run_bound_capability_named_human_review_separate": True,
            "run_bound_multimodal_demo_content_sha256": (
                run_bound_multimodal_demo["content_sha256"]
            ),
            "run_bound_multimodal_demo_evidence_class": (
                run_bound_multimodal_demo["evidence_class"]
            ),
            "run_bound_multimodal_demo_real_artifact_count": (
                run_bound_multimodal_demo["real_artifact_count"]
            ),
            "run_bound_multimodal_demo_generated_deliverable_count": (
                run_bound_multimodal_demo[
                    "registered_multimodal_deliverable_count"
                ]
            ),
            "run_bound_capability_demo_generated_deliverable_count": (
                run_bound_multimodal_demo[
                    "registered_capability_deliverable_count"
                ]
            ),
            "run_bound_portfolio_demo_generated_deliverable_count": (
                run_bound_multimodal_demo[
                    "registered_run_bound_deliverable_count"
                ]
            ),
            "run_bound_multimodal_demo_named_human_quality_count": (
                run_bound_multimodal_demo["named_human_quality_count"]
            ),
            "run_bound_multimodal_demo_production_effect_count": (
                run_bound_multimodal_demo["production_effect_attributed_count"]
            ),
            "run_bound_multimodal_demo_new_model_calls": (
                run_bound_multimodal_demo["source_execution"][
                    "new_model_calls_executed_by_this_demo"
                ]
            ),
            "run_bound_multimodal_demo_new_downloads": (
                run_bound_multimodal_demo["source_execution"][
                    "new_downloads_executed_by_this_demo"
                ]
            ),
            "run_bound_multimodal_demo_local_model_inference_observed": (
                run_bound_multimodal_demo["source_execution"][
                    "local_model_inference_observed"
                ]
            ),
            "run_bound_multimodal_demo_provider_generation_observed": (
                run_bound_multimodal_demo["source_execution"][
                    "provider_api_generation_observed"
                ]
            ),
            "run_bound_multimodal_demo_radeon_observed": (
                run_bound_multimodal_demo["source_execution"][
                    "radeon_execution_observed"
                ]
            ),
            "synthetic_lifecycle_demo_production_effect_proven": (
                synthetic_lifecycle_demo["production_effect_proven"]
            ),
            "revenue_memory_demo_external_api_calls": revenue_memory_demo[
                "external_api_calls"
            ],
            "revenue_memory_demo_external_publish_executed": (
                revenue_memory_demo["external_publish_executed"]
            ),
            "revenue_memory_demo_synthetic_revenue_is_production_evidence": (
                revenue_memory_demo["gates"][
                    "synthetic_revenue_is_production_evidence"
                ]
            ),
            "discrete_strategy_contract_count": discrete_scenario_count,
            "industry_gtm_archetype_count": industry_profile_matrix[
                "archetype_count"
            ],
            "industry_gtm_frozen_case_count": industry_profile_matrix[
                "case_count"
            ],
            "industry_gtm_zero_budget_case_count": industry_profile_matrix[
                "zero_budget_case_count"
            ],
            "industry_gtm_regulated_case_count": industry_profile_matrix[
                "regulated_case_count"
            ],
            "industry_gtm_distinct_zero_budget_engine_count": industry_profile_matrix[
                "distinct_zero_budget_engine_count"
            ],
            "industry_gtm_distinct_conversion_unit_count": industry_profile_matrix[
                "distinct_conversion_unit_count"
            ],
            "industry_gtm_distinct_unit_economics_signature_count": industry_profile_matrix[
                "distinct_unit_economics_signature_count"
            ],
            "industry_gtm_all_external_activation_disabled": industry_profile_matrix[
                "all_external_activation_disabled"
            ],
            "industry_gtm_matrix_sha256": industry_profile_matrix[
                "content_sha256"
            ],
            "discrete_strategy_matrix_test": (
                "tests.test_gtm_strategy_memory."
                "StrategyStageCoverageTests."
                "test_full_discrete_strategy_matrix_compiles_48_governed_contracts"
            ),
            "channel_portfolio_governed_route_count": len(Channel),
            "channel_portfolio_focus_capacity": 2,
            "channel_portfolio_test_capacity": 2,
            "channel_portfolio_automatic_activation_enabled": False,
            "channel_portfolio_matrix_evidence_sha256": channel_portfolio_matrix[
                "content_sha256"
            ],
            "channel_portfolio_matrix_case_count": channel_portfolio_matrix[
                "scenario_count"
            ],
            "channel_portfolio_matrix_test": (
                "tests.test_gtm_production_pack."
                "ProductionPackChannelPortfolioTests."
                "test_full_48_scenario_matrix_covers_every_channel_with_bounded_focus"
            ),
            "distribution_advantage_algorithm": "distribution_advantage_frontier_v2",
            "distribution_advantage_matrix_case_count": distribution_advantage_matrix[
                "scenario_count"
            ],
            "distribution_advantage_matrix_evidence_sha256": distribution_advantage_matrix[
                "content_sha256"
            ],
            "distribution_advantage_research_source_count": distribution_advantage_research[
                "source_count"
            ],
            "distribution_advantage_research_evidence_sha256": distribution_advantage_research[
                "content_sha256"
            ],
            "distribution_advantage_automatic_activation_enabled": False,
            "distribution_advantage_automatic_reallocation_enabled": False,
            "distribution_advantage_reallocation_scope": "named_human_review_next_run_only",
            "ten_peer_effect_alignment_category_count": effect_alignment_benchmark[
                "category_count"
            ],
            "ten_peer_effect_alignment_reference_product_count": effect_alignment_benchmark[
                "reference_product_count"
            ],
            "ten_peer_effect_alignment_open_source_project_count": effect_alignment_benchmark[
                "open_source_project_count"
            ],
            "ten_peer_effect_alignment_achieved": effect_alignment_benchmark[
                "portfolio_effect_alignment_achieved"
            ],
            "ten_peer_effect_alignment_evidence_sha256": effect_alignment_benchmark[
                "content_sha256"
            ],
            "last_mile_effect_primary_axis": last_mile_quality_benchmark[
                "effect_definition"
            ]["primary"],
            "last_mile_effect_secondary_axis": last_mile_quality_benchmark[
                "effect_definition"
            ]["secondary"],
            "last_mile_production_lane_count": last_mile_quality_benchmark[
                "lane_count"
            ],
            "last_mile_mechanically_ready_lane_count": last_mile_quality_benchmark[
                "portfolio"
            ]["mechanically_ready_lane_count"],
            "last_mile_same_brief_comparison_completed_lane_count": last_mile_quality_benchmark[
                "portfolio"
            ]["same_brief_comparison_completed_lane_count"],
            "last_mile_execution_quality_alignment_achieved": last_mile_quality_benchmark[
                "portfolio"
            ]["last_mile_execution_quality_alignment_achieved"],
            "last_mile_business_outcome_observed": last_mile_quality_benchmark[
                "portfolio"
            ]["business_outcome_observed"],
            "last_mile_quality_evidence_sha256": last_mile_quality_benchmark[
                "content_sha256"
            ],
            "last_mile_internal_challenger_model": last_mile_challenger[
                "execution"
            ]["model_id"],
            "last_mile_internal_challenger_lane_count": last_mile_challenger[
                "lane_count"
            ],
            "last_mile_internal_challenger_cloud_api_calls": last_mile_challenger[
                "execution"
            ]["cloud_api_calls"],
            "last_mile_internal_challenger_network_download_performed": last_mile_challenger[
                "execution"
            ]["network_download_performed"],
            "last_mile_internal_challenger_critical_before_repair": last_mile_challenger_repair[
                "diagnostic_before"
            ]["critical_finding_count"],
            "last_mile_internal_challenger_critical_after_repair": last_mile_challenger_repair[
                "diagnostic_after"
            ]["critical_finding_count"],
            "last_mile_internal_challenger_review_admission_allowed": last_mile_challenger_repair[
                "blind_review_admission_allowed"
            ],
            "last_mile_internal_review_pair_count": last_mile_internal_review[
                "lane_count"
            ],
            "last_mile_internal_review_expected_human_count": last_mile_internal_review[
                "expected_human_review_count"
            ],
            "last_mile_internal_review_submitted_human_count": last_mile_internal_review[
                "submitted_human_review_count"
            ],
            "last_mile_internal_review_top_product_baseline": last_mile_internal_review[
                "top_product_baseline"
            ],
            "last_mile_audio_candidate_count": last_mile_audio_candidates[
                "candidate_count"
            ],
            "last_mile_audio_candidate_offline_cloud_api_calls": last_mile_audio_candidates[
                "runtime"
            ]["cloud_api_calls"],
            "last_mile_audio_candidate_network_downloads": last_mile_audio_candidates[
                "runtime"
            ]["network_downloads"],
            "last_mile_audio_candidate_all_fifteen_seconds": all(
                abs(float(row["master"]["duration_seconds"]) - 15.0) <= 0.10
                for row in last_mile_audio_candidates["candidates"]
            ),
            "last_mile_audio_candidate_human_preference_observed": last_mile_audio_candidates[
                "human_preference_observed"
            ],
            "last_mile_video_challenger_content_sha256": last_mile_video_challenger[
                "content_sha256"
            ],
            "last_mile_video_challenger_video_sha256": last_mile_video_challenger[
                "video"
            ]["sha256"],
            "last_mile_video_challenger_duration_seconds": last_mile_video_challenger[
                "video"
            ]["duration_seconds"],
            "last_mile_video_challenger_dimensions": [
                last_mile_video_challenger["video"]["width"],
                last_mile_video_challenger["video"]["height"],
            ],
            "last_mile_video_challenger_three_beat_gate_passed": last_mile_video_challenger[
                "mechanical_three_beat_gate_passed"
            ],
            "last_mile_video_challenger_minimum_adjacent_rms": min(
                last_mile_video_challenger["adjacent_beat_rms_differences"]
            ),
            "last_mile_video_challenger_human_preference_observed": last_mile_video_challenger[
                "human_preference_observed"
            ],
            "last_mile_video_challenger_four_a_quality_proven": last_mile_video_challenger[
                "four_a_quality_proven"
            ],
            "last_mile_unified_review_lane_count": last_mile_unified_review[
                "lane_count"
            ],
            "last_mile_unified_review_pair_count": last_mile_unified_review[
                "comparison_pair_count"
            ],
            "last_mile_unified_review_expected_human_count": last_mile_unified_review[
                "expected_human_review_count"
            ],
            "last_mile_unified_review_submitted_human_count": last_mile_unified_review[
                "submitted_human_review_count"
            ],
            "last_mile_unified_review_top_product_baselines_present": last_mile_unified_review[
                "top_product_baselines_present"
            ],
            "last_mile_offline_review_kit_content_sha256": last_mile_offline_review_kit[
                "content_sha256"
            ],
            "last_mile_offline_review_kit_archive_sha256": last_mile_offline_review_kit[
                "archive"
            ]["sha256"],
            "last_mile_offline_review_kit_archive_bytes": last_mile_offline_review_kit[
                "archive"
            ]["bytes"],
            "last_mile_offline_review_kit_reviewer_page_count": last_mile_offline_review_kit[
                "reviewer_page_count"
            ],
            "last_mile_offline_review_kit_expected_human_count": last_mile_offline_review_kit[
                "expected_human_review_count"
            ],
            "last_mile_offline_review_kit_submitted_human_count": last_mile_offline_review_kit[
                "submitted_human_review_count"
            ],
            "last_mile_offline_review_kit_network_calls": last_mile_offline_review_kit[
                "network_calls"
            ],
            "last_mile_offline_review_kit_automatic_external_actions": last_mile_offline_review_kit[
                "automatic_external_actions"
            ],
            "last_mile_offline_review_kit_schema": last_mile_offline_review_manifest[
                "schema"
            ],
            "last_mile_offline_review_kit_hash_bound_generic_pair_count": len(
                last_mile_offline_review_manifest["generic_pairs"]
            ),
            "last_mile_offline_review_kit_visual_task_count": len(
                last_mile_offline_review_manifest["visual_tasks"]
            ),
            "last_mile_offline_review_kit_automatic_promotion_enabled": last_mile_offline_review_manifest[
                "automatic_promotion_enabled"
            ],
            "apple_mlx_runtime_preflight_passed": apple_mlx_preflight["passed"],
            "apple_mlx_runtime_metal_available": apple_mlx_preflight[
                "metal_available"
            ],
            "apple_mlx_runtime_metal_checked": apple_mlx_preflight["metal_checked"],
            "apple_mlx_runtime_observed_packages": apple_mlx_preflight[
                "observed_packages"
            ],
            "apple_mlx_runtime_preflight_content_sha256": apple_mlx_preflight[
                "content_sha256"
            ],
            "platform_native_b2b_generated_surface_count": platform_b2b_receipt[
                "accepted_surface_count"
            ],
            "platform_native_b2c_generated_surface_count": platform_b2c_receipt[
                "accepted_surface_count"
            ],
            "platform_native_b2b_local_model_device_family": platform_b2b_receipt[
                "model"
            ]["device_family"],
            "platform_native_b2b_cloud_api_calls": platform_b2b_receipt["model"][
                "cloud_api_calls"
            ],
            "platform_native_b2b_network_download_performed": platform_b2b_receipt[
                "model"
            ]["network_download_performed"],
            "platform_native_b2b_mechanical_publication_ready_count": platform_b2b_publication_ready_count,
            "platform_native_b2c_mechanical_publication_ready_count": platform_b2c_publication_ready_count,
            "platform_native_publication_human_review_completed_count": platform_publication_audit[
                "human_review_completed_count"
            ],
            "platform_native_publication_external_publish_executed": platform_publication_audit[
                "external_publish_executed"
            ],
            "platform_native_publication_audit_content_sha256": platform_publication_audit[
                "content_sha256"
            ],
            "platform_craft_review_artifact_count": platform_craft_public[
                "artifact_count"
            ],
            "platform_craft_review_reviewer_count": platform_craft_public[
                "reviewer_count"
            ],
            "platform_craft_review_expected_human_count": platform_craft_public[
                "review_task_count"
            ],
            "platform_craft_review_submitted_human_count": platform_craft_public[
                "submitted_human_review_count"
            ],
            "platform_craft_review_completed": platform_craft_public[
                "craft_review_completed"
            ],
            "platform_craft_review_named_product_comparison_executed": platform_craft_public[
                "named_product_comparison_executed"
            ],
            "platform_craft_review_network_submission_enabled": platform_craft_manifest[
                "network_submission_enabled"
            ],
            "platform_craft_review_automatic_publish_enabled": platform_craft_manifest[
                "automatic_publish_enabled"
            ],
            "platform_craft_review_archive_sha256": platform_craft_export["archive"][
                "sha256"
            ],
            "platform_craft_review_archive_bytes": platform_craft_export["archive"][
                "bytes"
            ],
            "platform_craft_review_public_packet_sha256": platform_craft_public[
                "content_sha256"
            ],
            "platform_gold_reference_rights_status": platform_gold_reference[
                "rights_status"
            ],
            "platform_gold_reference_training_admission": platform_gold_reference[
                "training_admission"
            ],
            "platform_gold_reference_candidate_count": len(
                platform_gold_reference["candidates"]
            ),
            "platform_gold_reference_provider": platform_gold_b2b_receipt["model"][
                "provider"
            ],
            "platform_gold_reference_local_inference_claimed": platform_gold_b2b_receipt[
                "model"
            ]["local_inference_claimed"],
            "platform_gold_reference_cloud_api_call_count": platform_gold_b2b_receipt[
                "model"
            ]["cloud_api_call_count"],
            "platform_gold_reference_pre_human_quality_pass_count": platform_gold_quality_audit[
                "pre_human_quality_pass_count"
            ],
            "platform_gold_reference_pre_human_quality_blocked_count": platform_gold_quality_audit[
                "blocked_count"
            ],
            "platform_gold_reference_cross_surface_duplicate_pair_count": len(
                platform_gold_quality_audit["cross_surface_duplicate_pairs"]
            ),
            "platform_gold_reference_mechanical_publication_ready_count": platform_gold_b2b_publication_ready_count,
            "platform_gold_reference_synthetic_b2c_publication_ready_count": platform_gold_b2c_publication_ready_count,
            "platform_gold_reference_human_review_completed_count": platform_gold_quality_audit[
                "human_craft_review_completed_count"
            ],
            "platform_gold_reference_production_effect_observed": platform_gold_quality_audit[
                "production_effect_observed"
            ],
            "platform_gold_reference_four_a_claim_eligible": platform_gold_quality_audit[
                "four_a_claim_eligible"
            ],
            "platform_gold_reference_top1_claim_eligible": platform_gold_quality_audit[
                "top1_claim_eligible"
            ],
            "platform_gold_reference_named_product_baseline": platform_gold_reference[
                "named_product_baseline"
            ],
            "platform_gold_reference_quality_audit_sha256": platform_gold_quality_audit[
                "content_sha256"
            ],
            "platform_gold_reference_publication_audit_sha256": platform_gold_publication_audit[
                "content_sha256"
            ],
            "platform_codex_capability_overlay_surface_count": len(
                platform_codex_overrides
            ),
            "platform_codex_capability_explicit_synthetic_surface_count": platform_codex_explicit_synthetic_surface_count,
            "platform_codex_capability_provider": platform_codex_receipt["model"][
                "provider"
            ],
            "platform_codex_capability_local_inference_claimed": platform_codex_receipt[
                "model"
            ]["local_inference_claimed"],
            "platform_codex_capability_cloud_api_call_count": platform_codex_receipt[
                "model"
            ]["cloud_api_call_count"],
            "platform_codex_capability_accepted_surface_count": platform_codex_receipt[
                "accepted_surface_count"
            ],
            "platform_codex_capability_pre_human_quality_pass_count": platform_codex_quality_audit[
                "pre_human_quality_pass_count"
            ],
            "platform_codex_capability_blocked_count": platform_codex_quality_audit[
                "blocked_count"
            ],
            "platform_codex_capability_cross_surface_duplicate_pair_count": len(
                platform_codex_quality_audit["cross_surface_duplicate_pairs"]
            ),
            "platform_codex_capability_human_review_completed_count": platform_codex_quality_audit[
                "human_craft_review_completed_count"
            ],
            "platform_codex_capability_production_effect_observed": platform_codex_quality_audit[
                "production_effect_observed"
            ],
            "platform_codex_capability_named_product_baseline": platform_codex_overlay[
                "named_product_baseline"
            ],
            "platform_codex_capability_four_a_claim_eligible": platform_codex_quality_audit[
                "four_a_claim_eligible"
            ],
            "platform_codex_capability_top1_claim_eligible": platform_codex_quality_audit[
                "top1_claim_eligible"
            ],
            "platform_codex_capability_receipt_sha256": platform_codex_receipt[
                "content_sha256"
            ],
            "platform_codex_capability_quality_audit_sha256": platform_codex_quality_audit[
                "content_sha256"
            ],
            "platform_codex_b2c_capability_reference_surface_count": len(
                platform_codex_b2c_reference["candidates"]
            ),
            "platform_codex_b2c_capability_provider": platform_codex_b2c_receipt[
                "model"
            ]["provider"],
            "platform_codex_b2c_capability_local_inference_claimed": platform_codex_b2c_receipt[
                "model"
            ]["local_inference_claimed"],
            "platform_codex_b2c_capability_cloud_api_call_count": platform_codex_b2c_receipt[
                "model"
            ]["cloud_api_call_count"],
            "platform_codex_b2c_capability_pre_human_quality_pass_count": platform_codex_b2c_quality_audit[
                "pre_human_quality_pass_count"
            ],
            "platform_codex_b2c_capability_blocked_count": platform_codex_b2c_quality_audit[
                "blocked_count"
            ],
            "platform_codex_b2c_capability_cross_surface_duplicate_pair_count": len(
                platform_codex_b2c_quality_audit["cross_surface_duplicate_pairs"]
            ),
            "platform_codex_b2c_capability_mechanical_publication_ready_count": platform_codex_b2c_quality_audit[
                "mechanically_publication_ready_count"
            ],
            "platform_codex_b2c_capability_publication_blocked_count": platform_codex_b2c_quality_audit[
                "publication_blocked_count"
            ],
            "platform_codex_b2c_capability_human_review_completed_count": platform_codex_b2c_quality_audit[
                "human_craft_review_completed_count"
            ],
            "platform_codex_b2c_capability_production_effect_observed": platform_codex_b2c_quality_audit[
                "production_effect_observed"
            ],
            "platform_codex_b2c_capability_named_product_baseline": platform_codex_b2c_reference[
                "named_product_baseline"
            ],
            "platform_codex_b2c_capability_four_a_claim_eligible": platform_codex_b2c_quality_audit[
                "four_a_claim_eligible"
            ],
            "platform_codex_b2c_capability_top1_claim_eligible": platform_codex_b2c_quality_audit[
                "top1_claim_eligible"
            ],
            "platform_codex_b2c_capability_receipt_sha256": platform_codex_b2c_receipt[
                "content_sha256"
            ],
            "platform_codex_b2c_capability_quality_audit_sha256": platform_codex_b2c_quality_audit[
                "content_sha256"
            ],
            "platform_codex_capability_showcase_candidate_count": (
                platform_codex_receipt["accepted_surface_count"]
                + platform_codex_b2c_receipt["accepted_surface_count"]
            ),
            "platform_codex_capability_showcase_api_present": platform_codex_showcase_api_present,
            "platform_codex_capability_showcase_browser_digest_verified": platform_codex_showcase_browser_digest_verified,
            "platform_codex_capability_showcase_ui_present": platform_codex_showcase_ui_present,
            "platform_codex_capability_showcase_release_eligible_count": 0,
            "platform_codex_capability_showcase_human_review_completed_count": 0,
            "platform_codex_capability_showcase_production_effect_observed": False,
            "codex_integrated_campaign_portfolio_sha256": codex_integrated_campaign_portfolio[
                "content_sha256"
            ],
            "codex_integrated_campaign_pack_count": codex_integrated_campaign_portfolio[
                "pack_count"
            ],
            "codex_integrated_campaign_platform_candidate_count": codex_integrated_campaign_portfolio[
                "platform_candidate_count"
            ],
            "codex_integrated_campaign_email_count": codex_integrated_campaign_portfolio[
                "email_count"
            ],
            "codex_integrated_campaign_production_direction_count": codex_integrated_campaign_portfolio[
                "production_direction_count"
            ],
            "codex_integrated_campaign_search_geo_node_count": codex_integrated_campaign_portfolio[
                "search_geo_node_count"
            ],
            "codex_integrated_campaign_seven_day_flight_slot_count": codex_integrated_campaign_portfolio[
                "seven_day_flight_slot_count"
            ],
            "codex_integrated_campaign_experiment_count": codex_integrated_campaign_portfolio[
                "experiment_count"
            ],
            "codex_integrated_campaign_api_present": codex_integrated_campaign_api_present,
            "codex_integrated_campaign_browser_digest_verified": codex_integrated_campaign_browser_digest_verified,
            "codex_integrated_campaign_ui_present": codex_integrated_campaign_ui_present,
            "codex_integrated_campaign_release_eligible_count": codex_integrated_campaign_portfolio[
                "release_eligible_count"
            ],
            "codex_integrated_campaign_human_review_completed_count": codex_integrated_campaign_portfolio[
                "human_review_completed_count"
            ],
            "codex_integrated_campaign_production_effect_observed": codex_integrated_campaign_portfolio[
                "production_effect_observed"
            ],
            "codex_integrated_campaign_named_product_pk_completed_count": codex_integrated_campaign_portfolio[
                "named_product_pk_completed_count"
            ],
            "codex_campaign_adaptation_matrix_sha256": codex_campaign_adaptation_matrix[
                "content_sha256"
            ],
            "codex_campaign_adaptation_case_count": codex_campaign_adaptation_matrix[
                "case_count"
            ],
            "codex_campaign_adaptation_industry_archetype_count": codex_campaign_adaptation_matrix[
                "industry_archetype_count"
            ],
            "codex_campaign_adaptation_zero_budget_count": codex_campaign_adaptation_matrix[
                "zero_budget_work_order_count"
            ],
            "codex_campaign_adaptation_regulated_count": codex_campaign_adaptation_matrix[
                "regulated_work_order_count"
            ],
            "codex_campaign_adaptation_graph_stage_count": len(
                codex_campaign_adaptation_matrix["generation_protocol"]["graph"]
            ),
            "codex_campaign_adaptation_named_failure_mode_count": len(
                codex_campaign_adaptation_matrix["generation_protocol"][
                    "named_failure_modes"
                ]
            ),
            "codex_campaign_adaptation_api_present": codex_campaign_adaptation_api_present,
            "codex_campaign_adaptation_browser_digest_verified": codex_campaign_adaptation_browser_digest_verified,
            "codex_campaign_adaptation_ui_present": codex_campaign_adaptation_ui_present,
            "codex_campaign_adaptation_model_call_count": codex_campaign_adaptation_matrix[
                "model_call_count"
            ],
            "codex_campaign_adaptation_candidate_output_count": codex_campaign_adaptation_matrix[
                "candidate_output_count"
            ],
            "codex_campaign_adaptation_human_review_completed_count": codex_campaign_adaptation_matrix[
                "human_review_completed_count"
            ],
            "codex_campaign_adaptation_release_eligible_count": codex_campaign_adaptation_matrix[
                "release_eligible_count"
            ],
            "codex_campaign_adaptation_production_effect_observed_count": codex_campaign_adaptation_matrix[
                "production_effect_observed_count"
            ],
            "codex_lighthouse_portfolio_sha256": codex_lighthouse_portfolio[
                "content_sha256"
            ],
            "codex_lighthouse_quality_sha256": codex_lighthouse_quality[
                "content_sha256"
            ],
            "codex_lighthouse_candidate_count": codex_lighthouse_portfolio[
                "candidate_count"
            ],
            "codex_lighthouse_workspace_authored_candidate_count": codex_lighthouse_portfolio[
                "workspace_authored_candidate_count"
            ],
            "codex_lighthouse_platform_asset_count": codex_lighthouse_portfolio[
                "platform_asset_count"
            ],
            "codex_lighthouse_level_1_pass_count": codex_lighthouse_quality[
                "level_1_pass_count"
            ],
            "codex_lighthouse_level_1_reject_count": codex_lighthouse_quality[
                "level_1_reject_count"
            ],
            "codex_lighthouse_api_present": codex_lighthouse_api_present,
            "codex_lighthouse_browser_digest_verified": codex_lighthouse_browser_digest_verified,
            "codex_lighthouse_ui_present": codex_lighthouse_ui_present,
            "codex_lighthouse_flagship_api_inference_observed_count": codex_lighthouse_public[
                "flagship_api_inference_observed_count"
            ],
            "codex_lighthouse_calibrated_model_critic_pass_count": codex_lighthouse_quality[
                "calibrated_model_critic_pass_count"
            ],
            "codex_lighthouse_qualified_human_review_count": codex_lighthouse_quality[
                "qualified_human_review_count"
            ],
            "codex_lighthouse_release_eligible_count": codex_lighthouse_quality[
                "release_eligible_count"
            ],
            "codex_lighthouse_external_publish_executed_count": codex_lighthouse_quality[
                "external_publish_executed_count"
            ],
            "codex_lighthouse_production_effect_observed_count": codex_lighthouse_quality[
                "production_effect_observed_count"
            ],
            "codex_lighthouse_causal_revenue_effect_proven_count": codex_lighthouse_quality[
                "causal_revenue_effect_proven_count"
            ],
            "platform_gold_craft_review_expected_human_count": platform_gold_craft_public[
                "review_task_count"
            ],
            "platform_gold_craft_review_submitted_human_count": platform_gold_craft_public[
                "submitted_human_review_count"
            ],
            "platform_gold_craft_review_completed": platform_gold_craft_public[
                "craft_review_completed"
            ],
            "platform_gold_craft_review_named_product_comparison_executed": platform_gold_craft_public[
                "named_product_comparison_executed"
            ],
            "platform_gold_craft_review_network_submission_enabled": platform_gold_craft_manifest[
                "network_submission_enabled"
            ],
            "platform_gold_craft_review_automatic_publish_enabled": platform_gold_craft_manifest[
                "automatic_publish_enabled"
            ],
            "platform_gold_craft_review_archive_sha256": platform_gold_craft_export[
                "archive"
            ]["sha256"],
            "platform_gold_craft_review_public_packet_sha256": platform_gold_craft_public[
                "content_sha256"
            ],
            "named_product_baseline_capture_category_count": named_product_baseline_capture_manifest[
                "category_count"
            ],
            "named_product_baseline_capture_slot_count": named_product_baseline_capture_manifest[
                "capture_slot_count"
            ],
            "named_product_baseline_capture_authorized_count": named_product_baseline_capture_manifest[
                "authorized_baseline_count"
            ],
            "named_product_baseline_capture_network_submission_enabled": named_product_baseline_capture_manifest[
                "network_submission_enabled"
            ],
            "named_product_baseline_capture_automatic_product_execution_enabled": named_product_baseline_capture_manifest[
                "automatic_product_execution_enabled"
            ],
            "named_product_baseline_capture_automatic_pk_promotion_enabled": named_product_baseline_capture_manifest[
                "automatic_pk_promotion_enabled"
            ],
            "named_product_baseline_capture_human_review_required": named_product_baseline_capture_manifest[
                "human_review_required"
            ],
            "named_product_baseline_capture_manifest_content_sha256": named_product_baseline_capture_manifest[
                "content_sha256"
            ],
            "named_product_baseline_capture_archive_sha256": named_product_baseline_capture_receipt[
                "archive"
            ]["sha256"],
            "named_product_baseline_capture_archive_bytes": named_product_baseline_capture_receipt[
                "archive"
            ]["bytes"],
            "named_product_pk_portfolio_schema": named_product_pk_portfolio["schema"],
            "named_product_pk_portfolio_completed_rows": named_product_pk_portfolio[
                "completed_product_pk_rows"
            ],
            "named_product_pk_portfolio_candidate_wins": named_product_pk_portfolio[
                "candidate_won_product_pk_rows"
            ],
            "named_product_pk_portfolio_effect_aligned_categories": named_product_pk_portfolio[
                "effect_aligned_category_count"
            ],
            "named_product_pk_portfolio_global_alignment": named_product_pk_portfolio[
                "named_product_last_mile_alignment_achieved"
            ],
            "named_product_pk_portfolio_automatic_runtime_switch_enabled": named_product_pk_portfolio[
                "automatic_runtime_switch_enabled"
            ],
            "named_product_pk_portfolio_four_a_quality_proven": named_product_pk_portfolio[
                "four_a_quality_proven"
            ],
            "named_product_pk_portfolio_content_sha256": named_product_pk_portfolio[
                "content_sha256"
            ],
            "named_product_challenger_dossier_count": named_product_challenger_admission[
                "dossier_count"
            ],
            "named_product_challenger_admitted_category_count": named_product_challenger_admission[
                "admitted_category_count"
            ],
            "named_product_challenger_blocked_category_count": named_product_challenger_admission[
                "blocked_category_count"
            ],
            "named_product_challenger_automatic_pairing_enabled": named_product_challenger_admission[
                "automatic_pairing_enabled"
            ],
            "named_product_challenger_four_a_quality_proven": named_product_challenger_admission[
                "four_a_quality_proven"
            ],
            "named_product_challenger_admission_content_sha256": named_product_challenger_admission[
                "content_sha256"
            ],
            "named_product_challenger_repair_artifact_count": named_product_challenger_repairs[
                "repair_artifact_count"
            ],
            "named_product_challenger_repair_content_sha256": named_product_challenger_repairs[
                "content_sha256"
            ],
            "named_product_challenger_repair_production_effect_observed": named_product_challenger_repairs[
                "production_effect_observed"
            ],
            "concrete_product_effect_pk_category_count": concrete_product_effect_pk[
                "category_count"
            ],
            "concrete_product_effect_pk_reference_row_count": concrete_product_effect_pk[
                "reference_product_row_count"
            ],
            "concrete_product_effect_pk_completed_row_count": concrete_product_effect_pk[
                "portfolio"
            ]["completed_product_pk_rows"],
            "concrete_product_effect_pk_effect_aligned_category_count": concrete_product_effect_pk[
                "portfolio"
            ]["effect_aligned_categories"],
            "concrete_product_effect_pk_internal_opponent_category_count": concrete_product_effect_pk[
                "portfolio"
            ]["categories_with_internal_same_brief_opponent"],
            "concrete_product_effect_pk_named_product_baseline_category_count": concrete_product_effect_pk[
                "portfolio"
            ]["categories_with_named_product_baseline"],
            "concrete_product_effect_pk_evidence_sha256": concrete_product_effect_pk[
                "content_sha256"
            ],
            "content_calendar_slot_count": 7,
            "content_calendar_operator_timezone_required": True,
            "content_calendar_minimum_review_window_hours": 24,
            "content_calendar_automatic_publish_enabled": False,
            "content_calendar_matrix_test": (
                "tests.test_gtm_content_calendar.ContentCalendarContractTests."
                "test_all_48_strategy_scenarios_compile_across_four_timezones"
            ),
            "breakout_growth_loop_step_count": 5,
            "breakout_growth_loop_archetype_count": 8,
            "breakout_growth_loop_paid_independent_core": True,
            "breakout_growth_loop_automatic_external_actions_enabled": False,
            "breakout_growth_loop_matrix_evidence_sha256": channel_portfolio_matrix[
                "content_sha256"
            ],
            "breakout_growth_loop_matrix_test": (
                "tests.test_gtm_breakout_loop.BreakoutGrowthLoopTests."
                "test_full_48_scenario_matrix_compiles"
            ),
            "text_creative_challenger_territory_count": 3,
            "text_creative_challenger_official_first_required": True,
            "text_creative_challenger_maximum_model_calls": 3,
            "text_creative_challenger_execution_mode": "sequential_fail_fast",
            "text_creative_challenger_maximum_concurrency": 1,
            "text_creative_challenger_default_retry_rounds": 0,
            "text_creative_challenger_blind_pair_count": 6,
            "text_creative_challenger_human_review_task_count": 30,
            "text_creative_challenger_model_judge_autofill_enabled": False,
            "text_creative_challenger_human_attestation_required": True,
            "text_creative_challenger_binary_preference_only": True,
            "text_creative_challenger_wilson_confidence_gate": True,
            "text_creative_challenger_tie_auto_selection_enabled": False,
            "text_creative_challenger_automatic_winner_selection_enabled": False,
            "text_creative_challenger_automatic_external_publish_enabled": False,
            "text_creative_challenger_matrix_evidence_sha256": channel_portfolio_matrix[
                "content_sha256"
            ],
            "text_creative_challenger_contract_test": (
                "tests.test_gtm_text_challenger.TextCreativeChallengerTests."
                "test_receipt_binds_all_three_candidates_and_rejects_tamper"
            ),
            "text_creative_challenger_runner_test": (
                "tests.test_gtm_text_challenger_runner."
                "TextCreativeChallengerRunnerTests."
                "test_blind_bundle_has_six_role_hidden_pairs_and_thirty_empty_human_tasks"
            ),
            "text_creative_challenger_human_aggregate_test": (
                "tests.test_gtm_text_challenger_runner."
                "TextCreativeChallengerRunnerTests."
                "test_completed_human_reviews_recommend_unique_leader_but_do_not_select_or_publish"
            ),
            "business_models": [item.value for item in BusinessModel],
            "lifecycle_stages": [item.value for item in LifecycleStage],
            "budget_tiers": [item.value for item in BudgetTier],
            "industry_risk_tiers": [item.value for item in IndustryRisk],
            "open_source_connector_count": len(connectors),
            "live_social_executor_ids": sorted(
                connector.connector_id
                for connector in connectors
                if connector.live_execution_admitted
            ),
            "public_signal_snapshot_and_receipt_pair_required": (
                "creative signals require a snapshot, collection receipt and field-level data class"
                in runtime_source
            ),
            "public_signal_field_level_data_class_present": (
                "creative_signal_data_class" in runtime_source
                and 'creative_signal_data_class: "public"' in web_app_source
                and 'data_class: "internal"' in web_app_source
            ),
            "public_signal_collection_receipt_self_hash_verified": (
                "supplied_receipt_sha256 != computed_receipt_sha256" in runtime_source
            ),
            "public_signal_collection_receipt_exact_snapshot_bound": (
                'receipt.get("creative_signal_snapshot_sha256")' in runtime_source
                and "!= snapshot_content_sha256" in runtime_source
            ),
            "public_signal_collector_no_bypass_gate_present": (
                'item.get("captcha_or_auth_bypass_attempted") is not False'
                in runtime_source
            ),
            "public_signal_training_and_publish_admission_disabled": (
                'receipt.get("training_admitted") is not False' in runtime_source
                and 'receipt.get("external_publish_executed") is not False'
                in runtime_source
            ),
            "public_signal_browser_pair_upload_present": (
                'name="creative_signal_collection_receipt"' in web_index_source
                and "stageCreativeSignalCollectionReceipt" in web_app_source
            ),
            "real_public_signal_collection_completed": (
                public_signal_collection_receipt["status"] == "completed"
                and public_signal_collection_receipt["normalized_signal_count"] == 28
                and len(public_signal_collection_receipt["runs"]) == 2
                and all(
                    row["status"] == "completed"
                    and row["captcha_or_auth_bypass_attempted"] is False
                    and row["raw_content_training_admitted"] is False
                    for row in public_signal_collection_receipt["runs"]
                )
                and supplied_signal_collection_sha256
                == computed_signal_collection_sha256
            ),
            "real_public_signal_gtm_pilot_bound": (
                public_signal_gtm_pilot["status"] == "awaiting_human_release"
                and public_signal_gtm_pilot["signal_count"] == 28
                and len(public_signal_gtm_pilot["platform_counts"]) == 2
                and public_signal_gtm_pilot["creative_signal_data_class"] == "public"
                and public_signal_gtm_pilot["run_data_class"] == "internal"
                and supplied_signal_pilot_sha256 == computed_signal_pilot_sha256
            ),
            "real_public_signal_cockpit_api_present": (
                'path == "/v1/public-signal-pilot"' in production_api_source
                and "_public_signal_pilot(pilot)" in production_api_source
                and public_signal_pilot_projection["signal_count"] == 28
                and public_signal_pilot_projection["hypothesis_count"] == 3
            ),
            "real_public_signal_cockpit_browser_digest_verified": (
                'requestJson("/v1/public-signal-pilot")' in web_app_source
                and "ProofLaunchPublicSignalGTMPilotPublicV1" in web_app_source
                and "computedDigest === suppliedDigest" in web_app_source
                and "pilot.automatic_strategy_mutation_executed === false"
                in web_app_source
                and "pilot.automatic_schedule_mutation_executed === false"
                in web_app_source
                and "pilot.external_release_executed === false" in web_app_source
            ),
            "real_public_signal_gtm_pilot_external_release_executed": (
                public_signal_gtm_pilot["external_release_executed"]
            ),
            "real_public_signal_gtm_pilot_automatic_strategy_mutation_executed": (
                public_signal_gtm_pilot["automatic_strategy_mutation_executed"]
            ),
            "graph_loop_harness_present": True,
            "tenant_isolation_model": "single_node_sqlite_scoped_vertical_slice",
            "tenant_principal_server_bound": True,
            "tenant_client_identity_override_allowed": False,
            "tenant_artifact_access_scoped": True,
            "tenant_run_access_scoped": True,
            "tenant_event_and_job_payloads_scoped": True,
            "tenant_learning_memory_scope_enforced": True,
            "tenant_idempotency_namespace_scoped": True,
            "portable_memory_capsule_signed": True,
            "portable_memory_capsule_tenant_and_project_bound": True,
            "portable_memory_capsule_expiry_enforced_at_import": True,
            "portable_memory_capsule_human_review_required": True,
            "portable_memory_capsule_pending_import_applied": False,
            "portable_memory_capsule_automatic_strategy_mutation_enabled": False,
            "portable_memory_capsule_external_action_enabled": False,
            "strategy_memory_contextual_arbitration_present": True,
            "strategy_memory_named_conflict_resolution_present": True,
            "strategy_memory_resolution_tenant_scoped": True,
            "strategy_memory_resolution_idempotent": True,
            "strategy_memory_resolution_source_run_mutated": False,
            "strategy_memory_resolution_future_runs_only": True,
            "strategy_memory_resolution_human_application_required": True,
            "strategy_memory_resolution_automatic_strategy_mutation_enabled": False,
            "strategy_memory_resolution_api_test": (
                "tests.test_v10_submission_production_api.ProductionSubmissionAPITests."
                "test_strategy_memory_resolution_api_is_named_tenant_bound_and_future_only"
            ),
            "strategy_memory_resolution_runtime_test": (
                "tests.test_v10_submission_runtime.ProductionAgentRuntimeTests."
                "test_named_conflict_resolution_applies_only_to_later_frozen_run"
            ),
            "tenant_browser_token_persistence": "session_storage_only",
            "tenant_browser_event_transport": "authenticated_incremental_json_polling",
            "tenant_cross_scope_regression_test": (
                "tests.test_v10_submission_production_api.ProductionSubmissionAPITests."
                "test_tenant_principal_blocks_run_artifact_memory_cache_and_injection_bleed"
            ),
            "content_bound_human_gate_present": True,
            "completed_human_review_verifier_present": True,
            "comfyui_isolated_production_adapter_present": True,
            "multi_route_multi_seed_candidate_batch_present": True,
            "candidate_batch_automatic_winner_selection_enabled": False,
            "blind_selected_progressive_multimodal_funnel_present": True,
            "progressive_multimodal_master_mux_enabled": False,
            "product_readiness_control_plane_present": True,
            "comfyui_admitted_backend_count": comfyui_backend_registry[
                "current_executable_backend_count"
            ],
            "official_comfyui_blueprint_capture_count": official_comfyui_manifest[
                "workflow_count"
            ],
            "official_comfyui_api_export_count": official_comfyui_manifest[
                "api_format_export_count"
            ],
            "open_source_capability_lane_count": len(
                open_source_capability_radar["capability_lanes"]
            ),
            "pinned_open_source_project_count": len(
                open_source_capability_radar["projects"]
            ),
            "open_source_radar_automatic_publish_enabled": (
                open_source_capability_radar["selection_counts"][
                    "automatic_external_publish_enabled"
                ]
            ),
            "open_source_radar_automatic_strategy_mutation_enabled": (
                open_source_capability_radar["selection_counts"][
                    "automatic_strategy_mutation_enabled"
                ]
            ),
            "revenue_feedback_source_bound_unit_economics_present": True,
            "revenue_feedback_contribution_cost_component_count": 6,
            "revenue_feedback_refund_and_chargeback_guard_present": True,
            "revenue_feedback_zero_budget_media_spend_gate_present": True,
            "revenue_feedback_pipeline_counted_as_revenue": False,
            "revenue_feedback_causal_revenue_claim_allowed": False,
            "revenue_feedback_automatic_budget_activation_enabled": False,
            "revenue_feedback_human_revenue_review_required": True,
            "official_comfyui_declared_weight_count": comfyui_weight_supply_chain[
                "weight_count"
            ],
            "official_comfyui_immutable_weight_metadata_count": (
                comfyui_weight_supply_chain["server_reported_weight_sha256_count"]
            ),
            "official_comfyui_total_declared_weight_bytes": (
                comfyui_weight_supply_chain["total_size_bytes"]
            ),
            "official_comfyui_locally_verified_weight_count": (
                comfyui_weight_supply_chain["installed_verified_weight_count"]
            ),
            "official_comfyui_weight_rights_gate_passed": comfyui_weight_supply_chain[
                "rights_gate_passed"
            ],
            "comfyui_model_card_license_ready_workflow_ids": (
                comfyui_weight_supply_chain["model_card_license_ready_workflow_ids"]
            ),
            "comfyui_evidence_output_wrapper_count": comfyui_execution_wrappers[
                "wrapper_count"
            ],
            "comfyui_output_wrapper_schema_validated_count": (
                comfyui_execution_wrapper_schema["validated_wrapper_count"]
            ),
            "comfyui_executable_wrapper_count": comfyui_execution_wrappers[
                "executable_wrapper_count"
            ],
            "comfyui_prompt_structure_validated_wrapper_count": (
                comfyui_wrapper_prompt_validation["validated_wrapper_count"]
            ),
            "comfyui_prompt_validation_queued_count": (
                comfyui_wrapper_prompt_validation["prompt_queued_count"]
            ),
            "comfyui_gpu_handoff_workflow_ids": comfyui_gpu_handoff[
                "selected_workflow_ids"
            ],
            "comfyui_gpu_handoff_download_count": comfyui_gpu_handoff[
                "download_count"
            ],
            "comfyui_gpu_handoff_total_weight_bytes": comfyui_gpu_handoff[
                "total_size_bytes"
            ],
            "comfyui_frozen_binding_contract_count": len(
                comfyui_execution_bindings["workflows"]
            ),
            "post_release_effect_feedback_present": True,
            "production_observation_field_kit_available": True,
            "production_observation_field_kit_source_files_included": False,
            "production_observation_field_kit_credentials_included": False,
            "production_observation_field_kit_network_submission_enabled": False,
            "production_observation_field_kit_human_submission_required": True,
            "production_observation_field_kit_human_economics_submission_present": True,
            "production_observation_field_kit_aggregate_attribution_plan_present": True,
            "production_observation_field_kit_distinct_arm_tags_present": True,
            "production_observation_field_kit_tracking_pixel_included": False,
            "production_observation_field_kit_person_level_export_allowed": False,
            "manual_publication_receipt_contract_present": True,
            "manual_publication_receipt_requires_delivered_approved_run": True,
            "manual_publication_receipt_exact_asset_attribution_url_binding": True,
            "manual_publication_receipt_prooflaunch_publish_enabled": False,
            "manual_publication_receipt_observed_count": 0,
            "manual_publication_platform_delivery_verified_count": 0,
            "human_promoted_cross_run_learning_present": True,
            "automatic_external_publish_enabled": False,
            "automatic_strategy_mutation_enabled": False,
        },
        "external_gate_snapshot": {
            "production_guardrails": {
                "policy_version": production_guardrail_eval["policy_version"],
                "case_count": production_guardrail_eval["case_count"],
                "minimum_cases_per_category": production_guardrail_eval[
                    "minimum_cases_per_category"
                ],
                "attack_recall": production_guardrail_eval["attack_recall"],
                "false_block_rate": production_guardrail_eval[
                    "false_block_rate"
                ],
                "escape_count": production_guardrail_eval["escape_count"],
                "api_boundary_enforced": production_guardrail_eval[
                    "api_boundary_enforced"
                ],
                "raw_prompt_or_pii_retained": production_guardrail_eval[
                    "raw_prompt_or_pii_retained"
                ],
                "production_deployment_observed": production_guardrail_eval[
                    "production_deployment_observed"
                ],
                "truth_boundary": production_guardrail_eval["truth_boundary"],
            },
            "production_trace_retention": {
                "policy_version": production_trace_retention["policy_version"],
                "retention_days": production_trace_retention["retention_days"],
                "local_restart_smoke_observed": production_trace_retention[
                    "local_restart_smoke_observed"
                ],
                "hash_chain_valid": production_trace_retention["hash_chain_valid"],
                "valid_request_boundary_instrumented": production_trace_retention[
                    "valid_request_boundary_instrumented"
                ],
                "raw_content_retained": production_trace_retention[
                    "raw_content_retained"
                ],
                "remote_required_check_observed": production_trace_retention[
                    "remote_required_check_observed"
                ],
                "production_deployment_observed": production_trace_retention[
                    "production_deployment_observed"
                ],
                "production_trace_coverage_observed": production_trace_retention[
                    "production_trace_coverage_observed"
                ],
                "truth_boundary": production_trace_retention["truth_boundary"],
            },
            "local_agentic_api_soak": {
                "transport": local_agentic_api_soak["execution"]["transport"],
                "case_count": local_agentic_api_soak["execution"][
                    "accepted_run_count"
                ],
                "awaiting_human_release_count": local_agentic_api_soak[
                    "execution"
                ]["awaiting_human_release_count"],
                "restart_recovery_passed": local_agentic_api_soak["execution"][
                    "durable_run_recovered_after_restart"
                ],
                "trace_count": local_agentic_api_soak["trace_ledger"][
                    "request_trace_count"
                ],
                "trace_hash_chain_valid": local_agentic_api_soak["trace_ledger"][
                    "hash_chain_valid"
                ],
                "production_deployment_observed": local_agentic_api_soak[
                    "truth_boundary"
                ]["production_deployment_observed"],
                "truth_boundary": local_agentic_api_soak["truth_boundary"],
            },
            "gtm_context_quality": {
                "observed_local_call_count": gtm_context_quality[
                    "observed_local_call_count"
                ],
                "median_context_utilization": gtm_context_quality[
                    "median_context_utilization"
                ],
                "p95_context_utilization": gtm_context_quality[
                    "p95_context_utilization"
                ],
                "context_utilization_gate_passed": gtm_context_quality[
                    "context_utilization_gate_passed"
                ],
                "long_session_eval_count": gtm_context_quality[
                    "long_session_eval_count"
                ],
                "minimum_long_session_message_count": gtm_context_quality[
                    "minimum_long_session_message_count"
                ],
                "long_session_compaction_gate_passed": gtm_context_quality[
                    "long_session_compaction_gate_passed"
                ],
                "new_model_calls": gtm_context_quality["new_model_calls"],
            },
            "agentic_product_readiness": {
                "launch_decision": agentic_product_readiness["launch_decision"],
                "audit_item_count": agentic_product_readiness["audit_item_count"],
                "passed_item_count": agentic_product_readiness[
                    "passed_item_count"
                ],
                "gap_item_count": agentic_product_readiness["gap_item_count"],
                "gap_ids": [
                    item["id"]
                    for item in agentic_product_readiness["items"]
                    if item["status"] == "gap"
                ],
                "enterprise_production_ready": False,
                "truth_boundary": agentic_product_readiness["truth_boundary"],
            },
            "tool_execution_sandbox": {
                "adapter_present": True,
                "runtime_observed": tool_sandbox_receipt is not None,
                "runtime_passed": bool(
                    tool_sandbox_receipt and tool_sandbox_receipt["passed"]
                ),
                "receipt_content_sha256": (
                    tool_sandbox_receipt["content_sha256"]
                    if tool_sandbox_receipt
                    else None
                ),
                "truth_boundary": (
                    "A validated container runtime receipt proves the bounded "
                    "filesystem, network, and secret-boundary probes for this run."
                    if tool_sandbox_receipt
                    else "The sandbox adapter and probes exist, but no validated "
                    "container runtime receipt exists; isolation is not claimed."
                ),
            },
            "local_portfolio_blind_review": {
                "status": local_portfolio_blind_review["status"],
                "public_packet_content_sha256": local_portfolio_blind_review[
                    "public_packet_content_sha256"
                ],
                "case_count": local_portfolio_blind_review["case_count"],
                "pair_count": local_portfolio_blind_review["pair_count"],
                "reviewer_slot_count": local_portfolio_blind_review[
                    "reviewer_slot_count"
                ],
                "expected_review_count": local_portfolio_blind_review[
                    "expected_review_count"
                ],
                "submitted_review_count": local_portfolio_blind_review[
                    "submitted_review_count"
                ],
                "review_complete": local_portfolio_blind_review[
                    "review_complete"
                ],
                "portfolio_promotion_passed": local_portfolio_blind_review[
                    "portfolio_promotion_passed"
                ],
                "human_preference_observed": local_portfolio_blind_review[
                    "human_preference_observed"
                ],
                "runtime_api_present": True,
                "runtime_expected_review_count": portfolio_blind_review_runtime_status[
                    "expected_review_count"
                ],
                "runtime_submitted_review_count": portfolio_blind_review_runtime_status[
                    "submitted_review_count"
                ],
                "review_submission_enabled": True,
                "restart_durable": True,
                "automatic_winner_selection_enabled": portfolio_blind_review_runtime_status[
                    "automatic_winner_selection_enabled"
                ],
                "truth_boundary": local_portfolio_blind_review["truth_boundary"],
            },
            "campaign_pack_visual_blind_review": {
                "public_packet_content_sha256": campaign_pack_blind_review_status[
                    "public_packet_sha256"
                ],
                "expected_review_count": campaign_pack_blind_review_status[
                    "expected_review_count"
                ],
                "submitted_review_count": campaign_pack_blind_review_status[
                    "submitted_review_count"
                ],
                "review_complete": campaign_pack_blind_review_status[
                    "review_complete"
                ],
                "human_preference_observed": campaign_pack_blind_review_status[
                    "human_preference_observed"
                ],
                "promotion_recommendation_eligible": (
                    campaign_pack_blind_review_status[
                        "promotion_recommendation_eligible"
                    ]
                ),
                "review_submission_enabled": True,
                "offline_review_kit_available": campaign_pack_blind_review_status[
                    "offline_review_kit_available"
                ],
                "offline_review_kit_invitation_bound": (
                    campaign_pack_blind_review_status[
                        "offline_review_kit_invitation_bound"
                    ]
                ),
                "offline_review_kit_contains_invitation_token": False,
                "offline_review_kit_network_submission_enabled": False,
                "restart_durable": True,
                "automatic_runtime_switch_enabled": False,
                "automatic_publish_enabled": False,
                "product_admission_passed": False,
                "four_a_preference_proven": False,
                "production_effect_proven": False,
                "truth_boundary": (
                    "The five-person V6/V8 three-format comparison is sealed and "
                    "runnable. Until all five independent reviews exist, no human "
                    "preference is observed; even a passing result is recommendation-"
                    "only and does not prove 4A quality or production effect."
                ),
            },
            "hybrid_quality_control": {
                "category_count": hybrid_quality_control["portfolio"]["category_count"],
                "job_count": hybrid_quality_control["portfolio"]["job_count"],
                "local_ready_category_count": hybrid_quality_control["portfolio"][
                    "local_ready_category_count"
                ],
                "cloud_api_role_count_ready": hybrid_quality_control["portfolio"][
                    "cloud_api_role_count_ready"
                ],
                "cloud_gpu_training_status": hybrid_quality_control["portfolio"][
                    "cloud_gpu_training_status"
                ],
                "hardware_and_provider_are_replaceable": True,
                "jobs_route_by_capability_not_vendor": True,
                "local_pipeline_continues_without_cloud": True,
                "cloud_gpu_is_product_runtime_dependency": False,
                "radeon_required_for_product_closure": False,
                "authorized_named_product_baseline_count": 0,
                "completed_named_product_pk_count": 0,
                "candidate_wins": 0,
                "effect_aligned_categories": 0,
                "specialist_craft_playbook_count": len(
                    hybrid_quality_control["lanes"]
                ),
                "specialist_craft_job_binding_count": len(
                    hybrid_quality_control["jobs"]
                ),
                "truth_boundary": hybrid_quality_control["truth_boundary"],
            },
            "adaptive_capability_graph": {
                "context_count": adaptive_capability_graph["coverage"]["context_count"],
                "lane_decision_count": adaptive_capability_graph["coverage"]["lane_decision_count"],
                "distinct_lane_state_profiles": adaptive_capability_graph["coverage"]["distinct_lane_state_profiles"],
                "distinct_focus_profiles": adaptive_capability_graph["coverage"]["distinct_focus_profiles"],
                "distinct_growth_route_profiles": adaptive_capability_graph["coverage"]["distinct_growth_route_profiles"],
                "zero_budget_paid_activation_count": adaptive_capability_graph["coverage"]["zero_budget_paid_activation_count"],
                "regulated_missing_specialist_gate_count": adaptive_capability_graph["coverage"]["regulated_missing_specialist_gate_count"],
                "automatic_external_action_count": adaptive_capability_graph["coverage"]["automatic_external_action_count"],
                "shadow_candidate_count": adaptive_capability_graph["shadow_candidate_registry"]["candidate_count"],
                "hardware_and_provider_in_plan_identity": adaptive_capability_graph["executor_binding"]["included_in_plan_identity"],
                "named_product_pk_wins": adaptive_capability_graph["coverage"]["named_product_pk_wins"],
                "truth_boundary": adaptive_capability_graph["truth_boundary"],
            },
            "human_capability_kernel": {
                "role_count": human_capability_kernel["coverage"]["role_count"],
                "professional_skill_card_count": human_capability_kernel["coverage"]["professional_skill_card_count"],
                "professional_axis_count": human_capability_kernel["coverage"]["professional_axis_count"],
                "eval_check_count": human_capability_kernel["coverage"]["eval_check_count"],
                "surface_count": human_capability_kernel["coverage"]["surface_count"],
                "surface_specialist_lens_count": human_capability_kernel["coverage"]["surface_specialist_lens_count"],
                "unconventional_edge_play_card_count": human_capability_kernel["coverage"]["unconventional_edge_play_card_count"],
                "automatic_external_action_count": human_capability_kernel["coverage"]["automatic_external_action_count"],
                "comparative_superiority_claim_allowed_now": human_capability_kernel["promotion_gate"]["comparative_superiority_claim_allowed_now"],
                "truth_boundary": human_capability_kernel["truth_boundary"],
            },
            "local_creative_benchmark": {
                "status": local_creative_benchmark["status"],
                "blocker": local_creative_benchmark.get("blocker"),
                "active_case_id": local_creative_benchmark.get("active_case_id"),
                "preflight_passed": local_creative_benchmark["preflight"]["passed"],
                "planned_case_count": local_creative_benchmark["planned_case_count"],
                "observed_case_count": local_creative_benchmark.get(
                    "observed_case_count", 0
                ),
                "completed_case_count": local_creative_benchmark[
                    "completed_case_count"
                ],
                "planned_model_call_count": local_creative_benchmark[
                    "planned_model_call_count"
                ],
                "completed_model_call_count": local_creative_benchmark[
                    "completed_model_call_count"
                ],
                "validated_candidate_count": local_creative_benchmark[
                    "validated_candidate_count"
                ],
                "failure": local_creative_benchmark.get("failure"),
                "truth_boundary": local_creative_benchmark["truth_boundary"],
                "effect_audit_status": local_creative_effect_audit["status"],
                "effect_gate_passed": local_creative_effect_audit["final_gate"][
                    "passed"
                ],
                "covered_channel_type_count": local_creative_effect_audit[
                    "final_gate"
                ]["covered_channel_type_count"],
                "channel_draft_count": local_creative_effect_audit["final_gate"][
                    "observed_channel_draft_count"
                ],
                "maximum_cross_scenario_pair_jaccard": local_creative_effect_audit[
                    "final_gate"
                ]["maximum_cross_scenario_pair_jaccard"],
                "human_preference_observed": local_creative_effect_audit[
                    "final_gate"
                ]["exact_human_preference_observed"],
            },
            "free_cloud_upgrade": {
                "status": frontier_free_sprint["status"],
                "candidate_count": frontier_free_sprint["candidate_count"],
                "live_calls_executed": frontier_free_sprint["live_calls_executed"],
                "paid_routes_enabled": frontier_free_sprint["paid_routes_enabled"],
                "competition_core_eligible": frontier_free_sprint["competition_core_eligible"],
                "local_first_status": local_cloud_resources["status"],
                "local_role_coverage": local_cloud_resources["local_role_coverage"],
                "download_performed": local_cloud_resources["download_performed"],
                "composite_plan_status": free_cloud_execution_plan["status"],
                "api_roles_ready": free_cloud_execution_plan["ready_api_role_count"],
                "api_roles_possible": free_cloud_execution_plan["possible_api_role_count"],
                "selected_api_candidate_count": free_cloud_execution_plan[
                    "selected_api_candidate_count"
                ],
                "qualification_request_ceiling": free_cloud_execution_plan[
                    "qualification_request_ceiling"
                ],
                "selected_weight_training_route": free_cloud_execution_plan[
                    "selected_weight_training_route"
                ],
                "weight_training_status": free_cloud_execution_plan[
                    "weight_training_status"
                ],
            },
            "public_signal_gtm_pilot": {
                "collection_status": public_signal_collection_receipt["status"],
                "captured_at": public_signal_collection_receipt["captured_at"],
                "signal_count": public_signal_gtm_pilot["signal_count"],
                "platform_counts": public_signal_gtm_pilot["platform_counts"],
                "hypothesis_count": public_signal_gtm_pilot["hypothesis_count"],
                "status": public_signal_gtm_pilot["status"],
                "human_release_required": public_signal_gtm_pilot[
                    "human_release_required"
                ],
                "automatic_strategy_mutation_executed": public_signal_gtm_pilot[
                    "automatic_strategy_mutation_executed"
                ],
                "external_release_executed": public_signal_gtm_pilot[
                    "external_release_executed"
                ],
                "cockpit_api_present": (
                    'path == "/v1/public-signal-pilot"' in production_api_source
                ),
                "cockpit_browser_digest_verified": (
                    'requestJson("/v1/public-signal-pilot")' in web_app_source
                    and "ProofLaunchPublicSignalGTMPilotPublicV1" in web_app_source
                ),
                "truth_boundary": public_signal_gtm_pilot["truth_boundary"],
            },
            "gold_human_review": {
                "status": gold_human_gate["status"],
                "submitted_review_count": gold_human_gate["submitted_review_count"],
                "expected_review_count": gold_human_gate["expected_review_count"],
                "promotion_passed": gold_human_gate["promotion_passed"],
            },
            "curated_human_audit": {
                "status": curated_human_gate["status"],
                "submitted_review_count": curated_human_gate[
                    "submitted_review_count"
                ],
                "expected_review_count": curated_human_gate[
                    "expected_review_count"
                ],
                "freeze_passed": curated_human_gate["freeze_passed"],
            },
            "amd_official_advisory_review": {
                "run_status": official_advisory["run_status"],
                "stop_reason": official_advisory["stop_reason"],
                "passed_attempts": official_advisory["passed_attempts"],
                "blocked_attempts": official_advisory["blocked_attempts"],
                "accepted_as_training_material": official_advisory[
                    "accepted_as_training_material"
                ],
                "truth_boundary": official_advisory["truth_boundary"],
            },
            "amd_product_closure_sprint": {
                "status": product_closure_sprint["status"],
                "stop_reason": product_closure_sprint["stop_reason"],
                "sealed_failed_record_count": product_closure_sprint[
                    "sealed_failed_record_count"
                ],
                "observed_spend_delta_usd": product_closure_sprint[
                    "observed_spend_delta_usd"
                ],
                "accepted_as_training_material": product_closure_sprint[
                    "accepted_as_training_material"
                ],
                "truth_boundary": product_closure_sprint["truth_boundary"],
            },
        },
        "evidence_status": {
            "strategy_to_bundle_mechanical_closure": "verified",
            "post_release_observation_contract": "verified_mechanical",
            "production_observation_field_kit": "verified_mechanical_empty_of_results",
            "b2b_b2c_lifecycle_budget_risk_schema_coverage": "verified_mechanical",
            "distribution_advantage_context_and_signal_coverage": "verified_1920_deterministic_decisions_not_effect_evidence",
            "ten_peer_cross_category_effect_alignment": "not_achieved_13_categories_130_references_actions_and_gates_sealed",
            "last_mile_generated_execution_quality": "14_of_14_lanes_mechanically_reviewable_zero_of_14_same_brief_human_pk_completed_4a_unproven",
            "unified_offline_human_review_execution": "v2_five_identity_hidden_reviewer_pages_16_hash_bound_pairs_each_80_tasks_immutable_import_and_predeclared_aggregate_gate_zero_submitted_zero_automatic_promotion",
            "platform_native_b2b_publication_execution": "thirteen_local_apple_metal_drafts_thirteen_mechanical_publication_gates_passed_zero_of_sixty_five_source_hidden_human_craft_reviews_submitted_named_product_pk_unchanged",
            "codex_direct_platform_capability_reference": "thirteen_of_thirteen_clean_room_surfaces_passed_pre_human_mechanical_quality_three_explicitly_labeled_synthetic_capability_cases_zero_human_reviews_zero_named_baselines_effect_unproven",
            "codex_direct_b2c_capability_reference": "thirteen_of_thirteen_clean_room_surfaces_passed_capability_craft_gate_zero_cross_surface_duplicates_all_thirteen_permanently_publication_blocked_as_synthetic_benchmark_zero_human_reviews_effect_unproven",
            "codex_direct_capability_product_surface": "digest_verified_read_only_api_and_thirteen_surface_b2b_b2c_browser_comparison_twenty_six_of_twenty_six_craft_zero_release_eligible_zero_human_effect",
            "codex_integrated_campaign_product_surface": "two_digest_verified_brief_bound_campaign_systems_twenty_six_platform_assets_eight_emails_six_multimodal_directions_fourteen_search_geo_nodes_fourteen_flight_slots_eight_frozen_experiments_zero_release_human_effect_or_named_pk",
            "codex_arbitrary_brief_adaptation_surface": "four_hundred_fifty_six_digest_bound_b2b_b2c_industry_lifecycle_budget_work_orders_twenty_archetypes_bounded_l2_graph_five_stages_ten_failure_modes_zero_model_calls_candidates_human_reviews_release_or_effect",
            "named_product_same_brief_capture_execution": "thirteen_frozen_briefs_130_rights_attested_local_capture_slots_zero_authorized_baselines_zero_automatic_promotion",
            "named_product_blind_pk_execution": "explicit_human_preparation_source_hidden_counterbalanced_five_reviewer_packets_immutable_row_and_130_row_portfolio_gates_zero_completed_zero_wins",
            "named_product_challenger_admission": "thirteen_self_contained_dossiers_thirteen_materially_admitted_after_seven_located_repairs_no_auto_pairing_no_effect_claim",
            "hybrid_capability_routing": "thirteen_of_thirteen_local_lanes_130_capability_routed_jobs_cloud_and_radeon_optional_zero_named_product_wins",
            "business_outcome_effect": "tracked_as_separate_secondary_axis_not_observed",
            "single_node_tenant_isolation": "verified_mechanical",
            "cross_device_portable_aggregate_memory": "verified_mechanical_pending_enterprise_key_management",
            "synthetic_strategy_to_revenue_to_cross_device_memory_demo": "verified_mechanical_not_production_effect",
            "distributed_database_row_level_security": "not_implemented",
            "enterprise_identity_provider_sso_scim": "not_implemented",
            "real_named_human_blind_preference": "not_observed",
            "real_external_publication": "not_observed",
            "real_model_generated_multimodal_deliverable": (
                "two_run_bound_audio_video_deliverables_registered_with_mixed_real_provenance_"
                "synthetic_control_plane_human_quality_and_effect_unproven"
            ),
            "local_model_generated_speech": "observed_technical_master_human_listening_unreviewed",
            "local_model_generated_video": (
                "observed_4k_14.72s_three_beat_internal_challenger_temporal_diversity_"
                "and_provenance_gates_passed_human_hook_preference_4a_and_effect_gates_pending"
            ),
            "local_model_generated_image": "observed_qwen_image_2512_source_sanitized_into_4k_1080p_and_4x5_delivery",
            "local_campaign_pack": "mechanical_ready_human_4a_business_and_radeon_gates_unproven",
            "full_lifecycle_cross_capability_closure": "verified_456_contracts_1976_synthetic_feedback_trajectories_not_production_effect",
            "local_non_model_multimodal_fixture": "generated_but_not_effect_evidence",
            "comfyui_production_execution": "not_observed",
            "comfyui_weight_metadata": "18_of_18_server_reported_hashes_pinned",
            "comfyui_local_weight_files": "0_of_18_verified",
            "comfyui_weight_rights": "not_cleared",
            "comfyui_evidence_output_wrappers": "4_schema_validated_not_executed",
            "real_production_business_outcome": "not_observed",
            "causal_revenue_lift": "not_observed",
            "radeon_local_key_inference": "not_observed_by_this_receipt",
            "apple_local_bge_route_head_training": "observed_gate_passed_not_promoted",
            "apple_local_qwen_generative_contract": "observed_14_of_14_after_bounded_repair_harness_not_training",
            "apple_local_gemma3_strategy_portfolio": (
                "observed_8_of_8_four_channel_contract_and_distinctiveness_gate_passed_human_effect_unproven"
                if local_gemma_strategy_portfolio_quality["portfolio_quality_gate_passed"]
                else "observed_portfolio_quality_gate_failed"
            ),
            "apple_local_end_to_end_gtm_mission": "observed_3_validated_candidates_6_blind_pairs_30_empty_human_tasks",
            "apple_local_cross_scenario_creative_benchmark": (
                "completed_9_cases_27_validated_candidates_localhost_only_unreviewed"
                if local_creative_benchmark["status"] == "completed"
                else "blocked_after_successful_preflight_with_transactional_progress"
                if local_creative_benchmark["status"] == "blocked_case_execution"
                else local_creative_benchmark["status"]
            ),
            "cross_scenario_human_preference": (
                "observed_portfolio_gate_passed"
                if local_portfolio_blind_review["portfolio_promotion_passed"]
                else "compiled_54_blind_pairs_270_empty_tasks_no_human_result"
            ),
            "cloud_flagship_upgrade": "configured_but_not_executed_missing_credentials",
            "four_a_effect_claim": "not_eligible",
            "top1_claim": "not_eligible",
        },
        "remaining_proof_gates": [
            "run blinded human candidate-vs-incumbent evaluation with the frozen rubric",
            "bind at least one real rights-cleared production observation to its preregistered experiment",
            "capture one qualifying Radeon-local key inference for competition evidence",
            "materialize and independently hash all admitted workflow weight files on the target GPU instance",
            "clear the five unresolved or legally gated model/component repositories before production use",
            "complete named human blind/listening review for the two run-bound generated deliverables",
            "replace the local token map and SQLite vertical slice with audited IdP, KMS, database RLS, and distributed worker isolation before enterprise production",
            "replace the local shared memory-capsule secret with KMS-backed per-tenant key rotation and device revocation before enterprise production",
        ],
        "truth_boundary": (
            "This receipt proves the selected product-critical local mechanics, scenario-"
            "contract coverage and regression status. It does not prove the entire repository, "
            "4A creative quality, Top-1 standing, "
            "external publication, causal lift, revenue, or Radeon execution."
            " Tenant isolation is verified only for the single-node local SQLite vertical slice;"
            " it does not prove distributed database RLS, SSO/SCIM, KMS, or multi-region isolation."
        ),
    }
    digest_basis = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    receipt["receipt_sha256"] = hashlib.sha256(digest_basis).hexdigest()
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(PROJECT_ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        output,
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    print(json.dumps({"output": str(output), **receipt["verification"]}, indent=2))


if __name__ == "__main__":
    main()
