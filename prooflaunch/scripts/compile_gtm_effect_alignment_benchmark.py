#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "config/gtm_open_source_capability_radar_v1.json"
OBSERVED_AT = "2026-08-02"


def product(name: str, url: str, reference_capability: str) -> dict[str, str]:
    return {
        "name": name,
        "official_or_primary_url": url,
        "reference_capability": reference_capability,
    }


REFERENCE_PRODUCTS: dict[str, list[dict[str, str]]] = {
    "cross_device_memory": [
        product("ChatGPT Memory", "https://help.openai.com/en/articles/8590148-memory-faq", "user controls plus saved and history-derived personalization"),
        product("Claude Memory", "https://support.anthropic.com/", "project-aware continuity and portable personalization controls"),
        product("Gemini personalization", "https://support.google.com/gemini/answer/16598469", "past-chat context across the Gemini experience"),
        product("Microsoft 365 Copilot Memory", "https://support.microsoft.com/en-us/Microsoft-365-Copilot/personalize-what-microsoft-365-copilot-remembers", "work-context preferences with administrator and user controls"),
        product("Zep", "https://www.getzep.com/", "source-traceable temporal context graph"),
        product("Mem0", "https://mem0.ai/", "user, session and agent memory with reproducible evaluation"),
        product("Letta", "https://www.letta.com/", "stateful agents with self-managed tiered memory"),
        product("MemOS", "https://memos.openmem.net/", "multimodal memory operating layer"),
        product("Personal AI", "https://www.personal.ai/", "user-owned personal model and persistent knowledge"),
        product("Glean Assistant", "https://www.glean.com/product/assistant", "permission-aware enterprise knowledge continuity"),
    ],
    "data_strategy_intelligence": [
        product("Palantir AIP", "https://www.palantir.com/platforms/aip/", "ontology-bound decisions and governed operational actions"),
        product("Databricks AI/BI", "https://www.databricks.com/product/ai-bi", "semantic data intelligence over governed lakehouse data"),
        product("Snowflake Intelligence", "https://www.snowflake.com/en/product/features/snowflake-intelligence/", "agentic analysis over governed enterprise data"),
        product("Microsoft Fabric", "https://www.microsoft.com/en-us/microsoft-fabric", "end-to-end data, BI and AI operating fabric"),
        product("Tableau", "https://www.tableau.com/", "visual analytics with governed semantic context"),
        product("ThoughtSpot", "https://www.thoughtspot.com/", "natural-language, explainable agentic analytics"),
        product("Qlik", "https://www.qlik.com/us/products/qlik-cloud-analytics", "associative analytics and governed data integration"),
        product("Looker", "https://cloud.google.com/looker", "semantic metrics and embedded BI"),
        product("Sigma", "https://www.sigmacomputing.com/", "spreadsheet-like governed cloud analytics"),
        product("Hex", "https://hex.tech/", "collaborative notebooks, semantic apps and data agents"),
    ],
    "content_scheduling_operations": [
        product("Hootsuite", "https://www.hootsuite.com/", "listen-create-schedule-engage-analyze operating suite"),
        product("Sprout Social", "https://sproutsocial.com/", "enterprise publishing, inbox, listening and analytics"),
        product("Buffer", "https://buffer.com/", "simple multi-network publishing and approval"),
        product("Later", "https://later.com/", "visual planning, creator and social commerce workflows"),
        product("Metricool", "https://metricool.com/", "calendar, competitor analytics and cross-network reporting"),
        product("Planable", "https://planable.io/", "collaborative preview and approval workflow"),
        product("Loomly", "https://www.loomly.com/", "brand calendars, approval and asset workflows"),
        product("Publer", "https://publer.io/", "bulk scheduling, recycling and workspace controls"),
        product("SocialBee", "https://socialbee.com/", "category-based evergreen scheduling"),
        product("Postiz", "https://postiz.com/", "open-source multi-platform scheduling and automation"),
    ],
    "image_generation_editing": [
        product("Midjourney", "https://www.midjourney.com/", "high-taste visual exploration and art direction"),
        product("Adobe Firefly", "https://firefly.adobe.com/", "commercial creative workflow and iterative editing"),
        product("OpenAI Image", "https://openai.com/index/introducing-4o-image-generation/", "instruction-following generation and conversational edits"),
        product("Google Imagen", "https://deepmind.google/models/imagen/", "photoreal generation and editing"),
        product("FLUX", "https://bfl.ai/", "high-fidelity open-weight and hosted image generation"),
        product("Ideogram", "https://ideogram.ai/", "typography and graphic-design generation"),
        product("Recraft", "https://www.recraft.ai/", "brand styles, vector and design-system outputs"),
        product("Leonardo.Ai", "https://leonardo.ai/", "production asset workflows and custom styles"),
        product("Qwen-Image", "https://github.com/QwenLM/Qwen-Image", "open image generation/editing with text rendering"),
        product("Canva Magic Media", "https://www.canva.com/magic-media/", "template-native campaign production for non-designers"),
    ],
    "video_generation_production": [
        product("Google Veo", "https://deepmind.google/models/veo/", "cinematic generation with audio and shot control"),
        product("Runway", "https://runwayml.com/", "generation, motion control and editing workflow"),
        product("Adobe Firefly Video", "https://www.adobe.com/products/firefly/features/ai-video-generator.html", "commercial creative-suite video workflow"),
        product("Kling AI", "https://klingai.com/", "longer coherent motion and controllable generation"),
        product("MiniMax Hailuo", "https://hailuoai.video/", "fast cinematic text/image-to-video"),
        product("Luma Dream Machine", "https://lumalabs.ai/dream-machine", "cinematic keyframe and modify workflows"),
        product("Pika", "https://pika.art/", "rapid social-native effects and transformations"),
        product("HeyGen", "https://www.heygen.com/", "marketing avatars, translation and localization"),
        product("Synthesia", "https://www.synthesia.io/", "governed enterprise avatar video production"),
        product("Seedance", "https://seed.bytedance.com/en/seedance", "multishot motion and instruction adherence"),
    ],
    "audio_voice_music": [
        product("ElevenLabs", "https://elevenlabs.io/", "expressive speech, dubbing, agents and voice controls"),
        product("Suno", "https://suno.com/", "full-song generation and iterative music creation"),
        product("Udio", "https://www.udio.com/", "music generation, extension and remix workflow"),
        product("Google Lyria", "https://deepmind.google/models/lyria/", "high-fidelity music generation and control"),
        product("Adobe Firefly Audio", "https://www.adobe.com/products/firefly/features.html", "commercial speech, sound and soundtrack workflow"),
        product("Stable Audio", "https://stableaudio.com/", "text-to-music and sound generation"),
        product("MiniMax Audio", "https://www.minimax.io/audio", "multilingual expressive speech and voice design"),
        product("Qwen3-TTS", "https://github.com/QwenLM/Qwen3-TTS", "open multilingual voice design and cloning"),
        product("ACE-Step 1.5", "https://github.com/ace-step/ACE-Step-1.5", "open music generation and audio retake"),
        product("Descript", "https://www.descript.com/", "text-native audio/video editing and voice workflow"),
    ],
    "text_content_generation": [
        product("ChatGPT", "https://chatgpt.com/", "general creation, research, files and iterative multimodal work"),
        product("Claude", "https://claude.ai/", "long-form reasoning, voice preservation and artifact creation"),
        product("Gemini", "https://gemini.google.com/", "grounded creation across Google workspace context"),
        product("Jasper", "https://www.jasper.ai/", "brand-governed campaign content operations"),
        product("Copy.ai", "https://www.copy.ai/", "GTM workflows and multi-asset copy generation"),
        product("Writer", "https://writer.com/", "enterprise knowledge, governance and brand-safe generation"),
        product("Notion AI", "https://www.notion.so/product/ai", "workspace-grounded writing and knowledge synthesis"),
        product("Grammarly", "https://www.grammarly.com/", "cross-application editing and brand tone"),
        product("Perplexity", "https://www.perplexity.ai/", "source-cited research and answer generation"),
        product("Writesonic", "https://writesonic.com/", "SEO/GEO-connected content production"),
    ],
    "product_marketing_analytics": [
        product("Amplitude", "https://amplitude.com/", "behavioral analytics, experimentation and session replay"),
        product("Mixpanel", "https://mixpanel.com/", "fast event-based funnels, retention and cohorts"),
        product("PostHog", "https://posthog.com/", "open product analytics, experiments, replay and warehouse"),
        product("Heap", "https://www.heap.io/", "automatic capture and digital journey analysis"),
        product("Pendo", "https://www.pendo.io/", "analytics plus in-product guidance and feedback"),
        product("Statsig", "https://www.statsig.com/", "feature experimentation and causal decision infrastructure"),
        product("Google Analytics", "https://marketingplatform.google.com/about/analytics/", "web and acquisition measurement at broad reach"),
        product("Tableau", "https://www.tableau.com/", "executive visual analytics and governed dashboards"),
        product("Power BI", "https://www.microsoft.com/en-us/power-platform/products/power-bi", "enterprise semantic BI and Copilot-assisted analysis"),
        product("ThoughtSpot", "https://www.thoughtspot.com/", "explainable natural-language analysis and agents"),
    ],
    "geo_ai_visibility": [
        product("Profound", "https://www.tryprofound.com/", "enterprise answer-engine visibility and agent analytics"),
        product("Scrunch AI", "https://scrunch.com/", "AI-search presence, entity and content diagnostics"),
        product("Peec AI", "https://peec.ai/", "multi-engine visibility and prompt monitoring"),
        product("Otterly.AI", "https://otterly.ai/", "self-serve AI-search monitoring and citation tracking"),
        product("AthenaHQ", "https://www.athenahq.ai/", "GEO monitoring and content action recommendations"),
        product("Goodie AI", "https://higoodie.com/", "answer-engine optimization workflow"),
        product("Evertune", "https://www.evertune.ai/", "brand perception and AI visibility intelligence"),
        product("Writesonic GEO", "https://writesonic.com/generative-engine-optimization-geo", "visibility monitoring connected to content execution"),
        product("Semrush AI Visibility", "https://www.semrush.com/ai-visibility/", "AI visibility inside a broader search suite"),
        product("Ahrefs Brand Radar", "https://ahrefs.com/brand-radar", "brand mentions and share of voice across AI and web"),
    ],
    "seo_operations": [
        product("Ahrefs", "https://ahrefs.com/", "crawl, backlinks, keywords, competitive and AI visibility data"),
        product("Semrush", "https://www.semrush.com/", "integrated SEO, content, competitive and visibility suite"),
        product("Moz Pro", "https://moz.com/products/pro", "keyword, link and site optimization workflow"),
        product("Screaming Frog", "https://www.screamingfrog.co.uk/seo-spider/", "deep deterministic technical crawling"),
        product("Sitebulb", "https://sitebulb.com/", "prioritized technical SEO diagnostics and visualization"),
        product("SE Ranking", "https://seranking.com/", "rank tracking, audit and agency operations"),
        product("Surfer", "https://surferseo.com/", "search-informed content optimization"),
        product("Clearscope", "https://www.clearscope.io/", "content relevance and editorial optimization"),
        product("Conductor", "https://www.conductor.com/", "enterprise organic marketing and site monitoring"),
        product("BrightEdge", "https://www.brightedge.com/", "enterprise search intelligence and content performance"),
    ],
    "employee_agent_platforms": [
        product("Salesforce Agentforce", "https://www.salesforce.com/agentforce/", "CRM-native agents with data and action governance"),
        product("Microsoft Copilot Studio", "https://www.microsoft.com/en-us/microsoft-copilot/microsoft-copilot-studio", "low-code enterprise agents and connector governance"),
        product("Gemini Enterprise", "https://cloud.google.com/gemini-enterprise", "organization-wide agent development and control plane"),
        product("OpenAI ChatGPT agent", "https://openai.com/index/introducing-chatgpt-agent/", "browser/computer/research action in one user surface"),
        product("Claude Enterprise", "https://www.anthropic.com/enterprise", "knowledge work, computer use and enterprise controls"),
        product("ServiceNow AI Agents", "https://www.servicenow.com/products/ai-agents.html", "workflow-native enterprise actions and orchestration"),
        product("Glean Agents", "https://www.glean.com/product/agents", "permission-aware knowledge agents and model choice"),
        product("Relevance AI", "https://relevanceai.com/", "no-code multi-agent workforce builder"),
        product("Lindy", "https://www.lindy.ai/", "small-team workflow agents and human handoff"),
        product("SAP Joule", "https://www.sap.com/products/artificial-intelligence/ai-assistant.html", "business-process agents over SAP context"),
    ],
    "advertising_activation": [
        product("Google Performance Max", "https://ads.google.com/home/campaigns/performance-max/", "cross-inventory goal-based bidding and creative assembly"),
        product("Meta Advantage+", "https://www.facebook.com/business/ads/meta-advantage-plus", "automated audience, placement and creative optimization"),
        product("TikTok Smart+", "https://ads.tiktok.com/business/en-US/smart-plus", "automated TikTok campaign setup and optimization"),
        product("Amazon Performance+", "https://advertising.amazon.com/solutions/products/performance-plus", "commerce-signal audience and conversion optimization"),
        product("LinkedIn Accelerate", "https://business.linkedin.com/marketing-solutions/accelerate", "AI-assisted B2B campaign construction"),
        product("The Trade Desk Kokai", "https://www.thetradedesk.com/us/kokai", "open-internet media planning, bidding and measurement"),
        product("Adobe GenStudio for Performance Marketing", "https://business.adobe.com/products/genstudio-for-performance-marketing.html", "brand-governed content supply chain and performance insight"),
        product("Smartly", "https://www.smartly.io/", "cross-platform creative and media operations"),
        product("Skai", "https://skai.io/", "omnichannel retail media, search and social optimization"),
        product("Sprinklr Advertising", "https://www.sprinklr.com/products/marketing/advertising/", "governed enterprise cross-channel advertising operations"),
    ],
    "gtm_lifecycle_orchestration": [
        product("Adobe Journey Optimizer", "https://business.adobe.com/products/journey-optimizer.html", "real-time omnichannel journeys, data, content and experimentation"),
        product("Braze", "https://www.braze.com/product/journey-orchestration", "first-party lifecycle decisioning and cross-channel journeys"),
        product("HubSpot", "https://www.hubspot.com/products/marketing", "CRM-bound content, campaign, lifecycle and reporting"),
        product("Salesforce Marketing Cloud", "https://www.salesforce.com/marketing/", "enterprise customer data, journeys and agentic optimization"),
        product("Iterable", "https://iterable.com/", "cross-channel lifecycle experimentation and personalization"),
        product("Customer.io", "https://customer.io/", "event-triggered messaging and journey automation"),
        product("Klaviyo", "https://www.klaviyo.com/", "commerce data, messaging and revenue attribution"),
        product("Hightouch", "https://hightouch.com/", "warehouse-native audience activation and decisioning"),
        product("Clay", "https://www.clay.com/", "GTM data enrichment and agentic outbound workflows"),
        product("Apollo", "https://www.apollo.io/", "B2B data, engagement and pipeline workflow"),
    ],
}


CATEGORY_SPECS: dict[str, dict[str, object]] = {
    "cross_device_memory": {
        "benchmark_axes": ["temporal recall", "multimodal recall", "citation provenance", "contradiction resolution", "user controls", "exact deletion", "tenant isolation", "cross-device continuity"],
        "open_source_projects": ["mem0", "graphiti", "memos", "neo4j_agent_memory", "qwen3_embedding"],
        "algorithms": ["episodic-semantic-procedural separation", "hybrid dense sparse graph retrieval", "temporal validity", "contradiction-aware consolidation", "tenant-scoped tombstones"],
        "candidate_models": ["bge-m3:latest", "mlx-community/gemma-3-12b-it-4bit", "Qwen3-Embedding"],
        "demonstrated_axes": ["citation provenance", "user controls", "exact deletion", "cross-device continuity"],
        "current_evidence": ["docs/product/GTM_CROSS_DEVICE_MEMORY_CAPSULE_V1.md", "evidence/v10/gtm-revenue-memory-demo.json"],
        "largest_gap": "No independent temporal/multimodal recall benchmark, enterprise KMS rotation or multi-tenant adversarial test.",
        "effect_gate": "LongMemEval-style held-out recall plus exact deletion, contradiction, tenant leakage and cross-device consistency tests.",
        "next_action": "P0: run a frozen incumbent-vs-Mem0/Graphiti shadow benchmark; keep the existing event log unless a challenger wins every safety gate.",
    },
    "data_strategy_intelligence": {
        "benchmark_axes": ["semantic metrics", "point-in-time correctness", "lineage", "scenario planning", "forecast uncertainty", "decision explanation", "source drill-through", "governed action"],
        "open_source_projects": ["duckdb", "polars", "openlineage", "feast", "great_expectations", "docling", "graphrag"],
        "algorithms": ["semantic metric contracts", "point-in-time joins", "causal DAGs", "Monte Carlo scenarios", "forecast intervals", "decision provenance"],
        "candidate_models": ["bge-m3:latest", "Gemma 3 12B local candidate", "Qwen3.6/GPT-OSS cloud critics when credentials exist"],
        "demonstrated_axes": ["semantic metrics", "lineage", "decision explanation", "source drill-through"],
        "current_evidence": ["evidence/v10/gtm-context-quality-v1.json", "evidence/v10/gtm-industry-profile-matrix-v1.json"],
        "largest_gap": "No live governed warehouse, point-in-time feature store or forecast calibration on observed business data.",
        "effect_gate": "Metric reconciliation, leakage-free rolling-origin backtest, calibrated intervals and every recommendation drilling to admissible evidence.",
        "next_action": "P1: add DuckDB/Polars point-in-time contract and an observed-data connector before adding an autonomous data agent.",
    },
    "content_scheduling_operations": {
        "benchmark_axes": ["native preview", "timezone correctness", "dependency planning", "approvals", "failure recovery", "frequency caps", "best-time evidence", "cross-network analytics"],
        "open_source_projects": ["postiz", "temporal", "openlineage"],
        "algorithms": ["constraint scheduling", "critical path planning", "frequency capping", "idempotent release", "compensating rollback"],
        "candidate_models": ["deterministic scheduler", "local text candidates only inside draft nodes"],
        "demonstrated_axes": ["timezone correctness", "dependency planning", "approvals", "frequency caps"],
        "current_evidence": ["docs/product/GTM_CONTENT_CALENDAR_V1.md", "evidence/v10/channel-portfolio-matrix.json"],
        "largest_gap": "No authorized platform publication, upload retry, native preview parity or observed best-time lift.",
        "effect_gate": "Sandbox replay then manual live canary with zero duplicate posts, exact media validation, rollback and outcome receipt.",
        "next_action": "P0: finish one human-approved dry-run connector and native preview; do not add broad auto-publish.",
    },
    "image_generation_editing": {
        "benchmark_axes": ["art direction", "typography", "brand identity", "product fidelity", "edit locality", "layout", "commercial provenance", "human preference"],
        "open_source_projects": ["comfyui", "qwen_image", "flux2", "paddleocr", "sam2", "open_clip"],
        "algorithms": ["multi-candidate generation", "OCR feedback", "segmentation-guided repair", "reference-conditioned editing", "brand embedding checks", "blind pairwise review"],
        "candidate_models": ["cached Qwen-Image-2512", "cached FLUX.2 Klein", "Qwen-Image-2.0 challenger after admission"],
        "demonstrated_axes": ["typography", "layout", "commercial provenance"],
        "current_evidence": ["evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json", "docs/product/CAMPAIGN_PACK_VISUAL_BLIND_REVIEW_V1.md"],
        "largest_gap": "No completed expert blind preference, admitted immutable workflow weights or demonstrated product/identity consistency across a real brand set.",
        "effect_gate": "Frozen prompt set with OCR/layout/product fidelity mechanics plus three independent 4A reviewers and critical-failure veto.",
        "next_action": "P0: render the same 12 brand tasks through cached Qwen/FLUX routes, then complete the existing identity-hidden expert review queue.",
    },
    "video_generation_production": {
        "benchmark_axes": ["story arc", "motion fidelity", "identity continuity", "shot control", "audio sync", "native duration", "4K delivery", "human preference"],
        "open_source_projects": ["comfyui", "wan22", "ltx2", "vbench", "mova"],
        "algorithms": ["shot DAG", "keyframe conditioning", "identity anchor propagation", "temporal defect detection", "audio-event alignment", "blind pairwise review"],
        "candidate_models": ["cached LTX-2.3", "cached Wan2.2 T2V/I2V", "MOVA research challenger"],
        "demonstrated_axes": ["story arc", "native duration", "4K delivery"],
        "current_evidence": ["evidence/v10/local-multimodal-qualification.json", "artifacts/run-bound-multimodal-demo-v1/demo-receipt.json"],
        "largest_gap": "The local LTX synthetic qualification failed subject recognition before repair and no video has passed named-human 4A preference or full continuity/audio-sync gates.",
        "effect_gate": "VBench plus campaign-specific identity, typography, audio-sync and story rubrics followed by blinded expert preference and platform-native playback.",
        "next_action": "P0: use cached Wan/LTX as specialists on one 15-second three-shot B2B and one B2C brief; reject before mastering unless identity and story gates pass.",
    },
    "audio_voice_music": {
        "benchmark_axes": ["intelligibility", "prosody", "emotion", "speaker consistency", "multilingual delivery", "music fit", "mix/master", "consent provenance"],
        "open_source_projects": ["qwen3_tts", "ace_step15", "whisper", "whisperx", "step_audio_editx"],
        "algorithms": ["voice design", "ASR round-trip", "prosody classification", "loudness/true-peak mastering", "music-brand embedding", "human MUSHRA-style review"],
        "candidate_models": ["cached Qwen3-TTS VoiceDesign", "cached LongCat-Audio", "ACE-Step 1.5 after weight admission"],
        "demonstrated_axes": ["intelligibility", "mix/master", "consent provenance"],
        "current_evidence": ["evidence/v10/local-multimodal-qualification.json", "evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json"],
        "largest_gap": "No transcript-aligned expressive score, multilingual suite, music originality screen or named-human listening result.",
        "effect_gate": "ASR/WER, prosody/emotion labels, LUFS/peak compliance, consent/rights receipt and blinded listening preference.",
        "next_action": "P0: generate three Qwen3-TTS deliveries for one frozen script, run Whisper round-trip and loudness gates, then collect named-human listening votes.",
    },
    "text_content_generation": {
        "benchmark_axes": ["strategy fidelity", "originality", "brand voice", "claim safety", "evidence grounding", "platform nativeness", "CTA clarity", "human preference"],
        "open_source_projects": ["dspy", "promptfoo", "qwen3_embedding", "cleanlab"],
        "algorithms": ["retrieval-grounded generation", "contrastive territories", "claim entailment", "style embedding", "semantic diversity", "blind pairwise review"],
        "candidate_models": ["cached Gemma 3 12B", "qwen2.5-coder:1.5b", "Groq Qwen3.6/GPT-OSS and Gemini cloud challengers when credentials exist"],
        "demonstrated_axes": ["strategy fidelity", "claim safety", "evidence grounding", "platform nativeness", "CTA clarity"],
        "current_evidence": ["evidence/v10/local-gemma3-12b-strategy-portfolio-quality-v1.json", "evidence/v10/local-gtm-portfolio-blind-review-status.json"],
        "largest_gap": "Mechanical candidate validation is strong but the frozen review queue remains 0/270, so originality and 4A preference are unproven.",
        "effect_gate": "Complete identity-hidden expert reviews with Wilson-bound preference, critical-failure veto and cross-scenario anti-collapse checks.",
        "next_action": "P0: stop expanding prompts and complete the existing blind review queue; escalate only failed slices to a credentialed flagship critic.",
    },
    "product_marketing_analytics": {
        "benchmark_axes": ["event quality", "identity-safe funnels", "cohorts", "retention", "experiments", "session evidence", "causal incrementality", "revenue reconciliation"],
        "open_source_projects": ["posthog", "growthbook", "duckdb", "polars", "openlineage", "dowhy"],
        "algorithms": ["event contracts", "SRM detection", "CUPED", "sequential testing", "causal refutation", "contribution-margin reconciliation"],
        "candidate_models": ["deterministic metric engine", "local/cloud models limited to explanation and query planning"],
        "demonstrated_axes": ["event quality", "experiments", "causal incrementality", "revenue reconciliation"],
        "current_evidence": ["docs/product/GTM_EFFECT_FIRST_EXECUTION_CONTRACT_V1.md", "evidence/v10/gtm-revenue-memory-demo.json"],
        "largest_gap": "All outcome trajectories are synthetic; no production exposure, control, net revenue or cost ledger has been observed.",
        "effect_gate": "One rights-cleared live experiment with preregistration, SRM check, source-bound exposure, net revenue/cost reconciliation and uncertainty interval.",
        "next_action": "P0: instrument one manually released campaign canary; keep all optimization advisory until an observed effect packet passes.",
    },
    "geo_ai_visibility": {
        "benchmark_axes": ["engine coverage", "regional prompts", "citation share", "answer share", "entity consistency", "source diagnostics", "change detection", "action validation"],
        "open_source_projects": ["open_seo", "siteone", "networkx", "qwen3_embedding", "qwen3_vl_embedding"],
        "algorithms": ["frozen prompt panels", "regional stratification", "citation graph", "entity resolution", "bootstrap uncertainty", "difference-in-differences where feasible"],
        "candidate_models": ["multi-provider frozen evaluator panel", "Qwen3 text/VL embeddings"],
        "demonstrated_axes": ["source diagnostics", "entity consistency"],
        "current_evidence": ["config/gtm_open_source_capability_radar_v1.json", "docs/product/GTM_DISTRIBUTION_ADVANTAGE_V2.md"],
        "largest_gap": "No live multi-engine, multi-region prompt panel or measured citation/answer-share delta.",
        "effect_gate": "Repeated frozen prompts across engines/regions with citation precision, variance and pre/post source changes; no deterministic rank promise.",
        "next_action": "P1: launch a 30-query, three-engine, two-region observation panel on a rights-cleared owned domain before generating GEO fixes.",
    },
    "seo_operations": {
        "benchmark_axes": ["crawl coverage", "indexability", "structured data", "performance", "canonical duplication", "internal graph", "content relevance", "measured organic delta"],
        "open_source_projects": ["siteone", "lighthouse", "open_seo", "networkx", "playwright"],
        "algorithms": ["deterministic crawl", "severity-weighted defects", "site graph centrality", "schema validation", "performance budgets", "query-page relevance"],
        "candidate_models": ["deterministic Lighthouse/SiteOne primary", "local LLM explanation only"],
        "demonstrated_axes": ["crawl coverage", "performance", "structured data"],
        "current_evidence": ["config/gtm_open_source_capability_radar_v1.json", "web/site10x.manifest.json"],
        "largest_gap": "No full owned-domain crawl receipt, Search Console baseline or post-fix organic outcome.",
        "effect_gate": "Sealed crawl before/after, defect closure, CWV/indexability deltas and an observation window for qualified organic outcomes.",
        "next_action": "P1: run Lighthouse plus SiteOne on the demo domain and bind every fix to a replayable before/after receipt.",
    },
    "employee_agent_platforms": {
        "benchmark_axes": ["end-to-end task completion", "tool reliability", "durability", "memory", "permissions", "human handoff", "observability", "enterprise isolation"],
        "open_source_projects": ["pydantic_ai", "temporal", "playwright", "browser_use", "openllmetry", "opa"],
        "algorithms": ["deterministic Graph", "bounded reflective Loop", "policy Harness", "checkpoint/replay", "idempotency", "risk-tiered human approval"],
        "candidate_models": ["local Gemma/Qwen candidates", "Radeon vLLM route", "flagship cloud critics only when authenticated"],
        "demonstrated_axes": ["end-to-end task completion", "tool reliability", "memory", "permissions", "human handoff", "observability"],
        "current_evidence": ["evidence/v10/agentic-product-readiness-audit.json", "docs/ARCHITECTURE_V10.md"],
        "largest_gap": "No qualifying Radeon-local key inference in the latest receipt, distributed worker isolation, enterprise IdP/KMS/RLS or held-out OSWorld-style benchmark.",
        "effect_gate": "Held-out executable tasks, recovery and permission adversaries, zero unapproved consequential actions, exact traces and named operator acceptance.",
        "next_action": "P0: run the complete approved GTM mission through one real local operator session; separately capture Radeon evidence when hardware returns.",
    },
    "advertising_activation": {
        "benchmark_axes": ["objective setup", "audience controls", "creative variants", "budget constraints", "incrementality", "brand safety", "cross-channel pacing", "human authority"],
        "open_source_projects": ["meridian", "dowhy", "econml", "causalml", "vowpal_wabbit", "opa"],
        "algorithms": ["budget frontier", "MMM", "uplift modeling", "safe contextual bandits", "frequency caps", "incrementality experiments"],
        "candidate_models": ["deterministic policy and measurement engine", "models may recommend but never activate spend"],
        "demonstrated_axes": ["objective setup", "budget constraints", "brand safety", "human authority"],
        "current_evidence": ["docs/product/GTM_HUMAN_SELECTED_OMNICHANNEL_ACTIVATION_V1.md", "evidence/v10/gtm-distribution-advantage-matrix-v2.json"],
        "largest_gap": "No platform credentials, live spend, conversion-quality feedback, incrementality test or cross-channel pacing evidence.",
        "effect_gate": "Human-approved sandbox then capped live canary with conversion integrity, holdout/incrementality, cost and brand-safety receipts.",
        "next_action": "P2: keep paid routes excluded in zero-budget mode; prepare one read-only campaign draft export, not autonomous activation.",
    },
    "gtm_lifecycle_orchestration": {
        "benchmark_axes": ["company-stage strategy", "B2B/B2C depth", "signal ingestion", "omnichannel assets", "journey orchestration", "experiment feedback", "revenue learning", "operator control"],
        "open_source_projects": ["pydantic_ai", "temporal", "dspy", "posthog", "growthbook", "meridian", "openlineage"],
        "algorithms": ["distribution-advantage frontier", "lifecycle state machine", "journey DAG", "causal feedback", "champion-challenger memory", "contribution-margin objective"],
        "candidate_models": ["local-first specialist portfolio", "cloud flagship critics", "Radeon-local key route"],
        "demonstrated_axes": ["company-stage strategy", "B2B/B2C depth", "signal ingestion", "omnichannel assets", "experiment feedback", "operator control"],
        "current_evidence": ["evidence/v10/gtm-lifecycle-closure-matrix-v1.json", "evidence/v10/gtm-distribution-advantage-matrix-v2.json"],
        "largest_gap": "The 456 lifecycle contracts and 1,976 feedback trajectories are synthetic, so real journey and revenue effects remain unproven.",
        "effect_gate": "One B2B and one B2C operator-run lifecycle with real approved assets, platform receipts, preregistered observations and reconciled revenue/cost.",
        "next_action": "P0: choose one B2B and one B2C lighthouse mission and complete the human-quality plus live-observation gates instead of adding more synthetic scenarios.",
    },
}


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_benchmark() -> dict[str, object]:
    radar = json.loads(RADAR.read_text(encoding="utf-8"))
    known_projects = set(radar["projects"])
    categories: list[dict[str, object]] = []
    for category_id, products in REFERENCE_PRODUCTS.items():
        if len(products) != 10:
            raise ValueError(f"{category_id} must contain exactly ten reference products")
        spec = CATEGORY_SPECS[category_id]
        unknown = set(spec["open_source_projects"]) - known_projects
        if unknown:
            raise ValueError(f"{category_id} contains unknown radar projects: {sorted(unknown)}")
        benchmark_axes = list(spec["benchmark_axes"])
        demonstrated_axes = list(spec["demonstrated_axes"])
        if not set(demonstrated_axes) <= set(benchmark_axes):
            raise ValueError(f"{category_id} demonstrated axes escape benchmark axes")
        categories.append(
            {
                "category_id": category_id,
                "reference_set_kind": "ten_leading_peer_products_not_an_ordinal_global_ranking",
                "reference_products": products,
                "benchmark_axes": benchmark_axes,
                "open_source_projects": list(spec["open_source_projects"]),
                "algorithms": list(spec["algorithms"]),
                "candidate_models": list(spec["candidate_models"]),
                "current_evidence": list(spec["current_evidence"]),
                "demonstrated_axes": demonstrated_axes,
                "mechanical_axis_coverage": {
                    "demonstrated": len(demonstrated_axes),
                    "required": len(benchmark_axes),
                },
                "last_mile_execution_quality_alignment_achieved": False,
                "business_outcome_observed": False,
                "effect_alignment_achieved": False,
                "largest_gap": spec["largest_gap"],
                "last_mile_quality_gate": (
                    "Run the same frozen brief or operator task against the candidate and a "
                    "rights-cleared peer baseline; hide system identity; collect at least five "
                    "qualified human judgments across the declared axes; require zero critical "
                    "defects, at least 60% candidate preference and a Wilson lower confidence "
                    "bound above 0.50. Model judges may diagnose but cannot promote."
                ),
                "business_outcome_gate": spec["effect_gate"],
                "effect_gate": spec["effect_gate"],
                "next_action": spec["next_action"],
            }
        )
    core: dict[str, object] = {
        "schema": "ProofLaunchGTMTenPeerEffectAlignmentBenchmarkV1",
        "observed_at": OBSERVED_AT,
        "category_count": len(categories),
        "reference_product_count": sum(len(row["reference_products"]) for row in categories),
        "open_source_radar_revision": radar["observed_at"],
        "open_source_lane_count": radar["selection_counts"]["capability_lanes"],
        "open_source_project_count": radar["selection_counts"]["pinned_projects"],
        "effect_definition": {
            "primary": "last_mile_generated_execution_quality",
            "secondary": "observed_business_outcome",
            "separation_rule": (
                "A missing business outcome does not erase a demonstrated production-quality "
                "result, and a business outcome cannot substitute for a same-brief craft review."
            ),
        },
        "categories": categories,
        "portfolio_last_mile_execution_quality_alignment_achieved": False,
        "portfolio_business_outcome_observed": False,
        "portfolio_effect_alignment_achieved": False,
        "last_mile_quality_blockers": [
            "0/270 frozen cross-scenario human creative reviews completed",
            "0/5 campaign-pack visual comparison reviews completed",
            "audio has no named listening review and video has no completed production-quality review",
            "not every strategy, email, landing, SEO, GEO and advertising output has a same-brief peer comparison",
        ],
        "business_outcome_blockers": [
            "no rights-cleared production outcome with causal revenue reconciliation",
            "no complete B2B and B2C operator-run lifecycle with external platform receipts",
        ],
        "portfolio_blockers": [
            "same-brief last-mile human comparisons remain incomplete",
            "no rights-cleared production outcome with causal revenue reconciliation",
            "no complete B2B and B2C operator-run lifecycle with external platform receipts",
            "latest readiness receipt does not establish qualifying Radeon-local key inference",
            "enterprise IdP, KMS, database RLS and distributed worker isolation remain incomplete",
        ],
        "three_day_convergence_rule": (
            "Stop adding broad features. Complete two lighthouse missions, expert blind/listening "
            "review, one observed campaign canary and exact evidence sealing. Cloud models are "
            "critics/challengers only; local Harness and held-out gates remain authoritative."
        ),
        "truth_boundary": (
            "The ten products in each category are a non-ordinal leading peer reference set "
            "assembled from official or primary product identities and current market research. "
            "This artifact does not prove a global ranking, feature parity, copied implementation, "
            "4A quality, campaign effect, revenue lift or production readiness. Last-mile quality "
            "and business outcome are independent axes; both remain false until their own gates pass."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def render_markdown(benchmark: dict[str, object]) -> str:
    lines = [
        "# GTM ten-peer effect-alignment benchmark V1",
        "",
        f"Observed: {benchmark['observed_at']}  ",
        f"Coverage: {benchmark['category_count']} categories / {benchmark['reference_product_count']} product references / {benchmark['open_source_project_count']} pinned open-source projects",
        "",
        "The ten products per category are a non-ordinal leading peer set, not a claimed global ranking. The primary audit asks whether ProofLaunch's final generated strategy and assets win same-brief production-quality comparison. Business outcome is a separate secondary axis. It does not copy proprietary workflows or training material.",
        "",
        "## Portfolio verdict",
        "",
        "**Last-mile execution-quality alignment is not yet achieved.** A mechanically complete output is not a 4A-quality output until the same-brief blind comparison passes. Business outcome remains an independent, secondary unobserved axis.",
        "",
        "| Category | Mechanical axes | Last-mile quality | Business outcome | Largest gap | Next action |",
        "|---|---:|---|---|---|---|",
    ]
    for row in benchmark["categories"]:
        coverage = row["mechanical_axis_coverage"]
        lines.append(
            f"| `{row['category_id']}` | {coverage['demonstrated']}/{coverage['required']} | not proven | unobserved | {row['largest_gap']} | {row['next_action']} |"
        )
    for row in benchmark["categories"]:
        lines.extend(["", f"## {row['category_id']}", "", "### Ten-product peer baseline", "", "| Product | Public reference capability |", "|---|---|"])
        for item in row["reference_products"]:
            lines.append(f"| [{item['name']}]({item['official_or_primary_url']}) | {item['reference_capability']} |")
        lines.extend(
            [
                "",
                f"- Benchmark axes: {', '.join(row['benchmark_axes'])}.",
                f"- Demonstrated now: {', '.join(row['demonstrated_axes'])}.",
                f"- Open-source leverage: {', '.join(row['open_source_projects'])}.",
                f"- Algorithms: {', '.join(row['algorithms'])}.",
                f"- Model routes: {', '.join(row['candidate_models'])}.",
                f"- Evidence: {', '.join(row['current_evidence'])}.",
                f"- Last-mile quality gate: {row['last_mile_quality_gate']}",
                f"- Business-outcome gate: {row['business_outcome_gate']}",
                f"- Verdict: **last-mile parity not proven; business outcome unobserved**. {row['largest_gap']}",
                f"- Action: {row['next_action']}",
            ]
        )
    lines.extend(["", "## Three-day convergence", "", benchmark["three_day_convergence_rule"], "", "## Truth boundary", "", benchmark["truth_boundary"], ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default=str(ROOT / "evidence/v10/gtm-ten-peer-effect-alignment-benchmark-v1.json"))
    parser.add_argument("--markdown-output", default=str(ROOT / "docs/product/GTM_TEN_PEER_EFFECT_ALIGNMENT_BENCHMARK_V1.md"))
    args = parser.parse_args()
    outputs = [Path(args.json_output).resolve(), Path(args.markdown_output).resolve()]
    for output in outputs:
        try:
            output.relative_to(ROOT.resolve())
        except ValueError as error:
            raise SystemExit("outputs must remain inside the project root") from error
    benchmark = build_benchmark()
    atomic_write_text(outputs[0], json.dumps(benchmark, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(outputs[1], render_markdown(benchmark))
    print(json.dumps({"category_count": benchmark["category_count"], "reference_product_count": benchmark["reference_product_count"], "effect_alignment_achieved": False, "content_sha256": benchmark["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
