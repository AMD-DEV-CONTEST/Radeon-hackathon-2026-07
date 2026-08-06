#!/usr/bin/env bash
export BG_ROOT=/persistent/BuildGuard-Radeon-backup
export LLAMA_SERVER=/persistent/buildguard/runtime/llama.cpp/rocm-7.2.1/llama-b8407-ubuntu-24.04-rocm-7.2.1-gfx110X-gfx115X-gfx120X-x64/llama-server

export BG_PVC=$BG_ROOT
export BG_REPO=$BG_ROOT
export BG_VENV=$BG_ROOT/envs/app-py312-rocm721
export BG_MODELS=$BG_ROOT/models
export BG_WORKSPACE=$BG_ROOT/workspace
export BG_RUNTIME=$BG_ROOT/runtime
export BG_LOGS=$BG_ROOT/logs
export BG_RUN=$BG_ROOT/run

# Path overrides for competition config
export BUILDGUARD_APP__DATA_DIR=$BG_ROOT/data
export BUILDGUARD_APP__WORKSPACE_DIR=$BG_ROOT/workspace
export BUILDGUARD_APP__DATABASE_PATH=$BG_ROOT/workspace/database/buildguard.db

export BUILDGUARD_MONITORING__OUTPUT_PATH=$BG_ROOT/data/hardware.jsonl
export BUILDGUARD_MONITORING__DASHBOARD_LOG_PATH=$BG_ROOT/workspace/logs/performance/dashboard.jsonl
export BUILDGUARD_MONITORING__EXPORT_DIR=$BG_ROOT/workspace/logs/performance/exports

export BUILDGUARD_RAG__EMBEDDING_MODEL_PATH=$BG_ROOT/models/embedding/qwen3-embedding-0.6b
export BUILDGUARD_RAG__EMBEDDING_MANIFEST_PATH=$BG_ROOT/models/embedding/qwen3-embedding-0.6b/model-manifest.json
export BUILDGUARD_RAG__RERANKER_MODEL_PATH=$BG_ROOT/models/reranker/qwen3-reranker-0.6b
export BUILDGUARD_RAG__RERANKER_MANIFEST_PATH=$BG_ROOT/models/reranker/qwen3-reranker-0.6b/model-manifest.json
export BUILDGUARD_RAG__INDEX_DIR=$BG_ROOT/workspace/indexes/construction_standards
export BUILDGUARD_RAG__ALLOWED_SOURCE_ROOTS="[\"$BG_ROOT/workspace/knowledge\"]"

export BUILDGUARD_VISION__ALLOWED_IMAGE_ROOTS="[\"$BG_ROOT/workspace/uploads\"]"
export BUILDGUARD_VISION__VISUALIZATION_DIR=$BG_ROOT/workspace/events/images
export BUILDGUARD_VISION__SEGMENTATION__OUTPUT_DIR=$BG_ROOT/workspace/events/masks

export BUILDGUARD_REALTIME__ALLOWED_VIDEO_ROOTS="[\"$BG_ROOT/workspace/cameras\"]"
export BUILDGUARD_REALTIME__EVENT_IMAGE_DIR=$BG_ROOT/workspace/events/images
export BUILDGUARD_REALTIME__EVENT_CLIP_DIR=$BG_ROOT/workspace/events/clips

export BUILDGUARD_REPORTING__OUTPUT_DIR=$BG_ROOT/reports

export BUILDGUARD_RUNTIME__STATE_PATH=$BG_ROOT/workspace/runtime/runtime-mode.json
export BUILDGUARD_RUNTIME__LOCK_PATH=$BG_ROOT/workspace/runtime/runtime-mode.lock
export BUILDGUARD_RUNTIME__AUDIT_PATH=$BG_ROOT/workspace/logs/audit/runtime-mode.jsonl

export BUILDGUARD_EVALUATION__OUTPUT_DIR=$BG_ROOT/reports/evaluation
export BUILDGUARD_EVALUATION__AGENT_DATASET_PATH=$BG_ROOT/data/evaluation/agent-evaluation.json
export BUILDGUARD_EVALUATION__RAG_DATASET_PATH=$BG_ROOT/data/evaluation/rag-evaluation.json
export BUILDGUARD_EVALUATION__VISION_DATASET_PATH=$BG_ROOT/data/evaluation/vision-evaluation.json
export BUILDGUARD_EVALUATION__REALTIME_DATASET_PATH=$BG_ROOT/data/evaluation/realtime-evaluation.json
export BUILDGUARD_EVALUATION__SECURITY_DATASET_PATH=$BG_ROOT/data/evaluation/security-evaluation.json
export BUILDGUARD_EVALUATION__STABILITY_MANIFEST_PATH=$BG_ROOT/data/evaluation/stability-manifest.json

export BUILDGUARD_COMPETITION__PPE_DATASET_DIR=$BG_ROOT/data/ppe/sh17-buildguard
export BUILDGUARD_COMPETITION__KNOWLEDGE_DIR=$BG_ROOT/workspace/knowledge
export BUILDGUARD_COMPETITION__RAG_MANIFEST_PATH=$BG_ROOT/workspace/indexes/construction_standards/corpus_manifest.json

export BUILDGUARD_CONFIG=$BG_ROOT/configs/competition/app.yaml

# Offline mode
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1
export NO_PROXY=127.0.0.1,localhost,::1

export PATH="$BG_VENV/bin:$PATH"
