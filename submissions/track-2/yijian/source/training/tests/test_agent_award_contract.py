# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path


TRAINING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING_ROOT))

import agent_multitask_corpus as corpus  # noqa: E402
import build_agent_source_cases as support  # noqa: E402


def creator(case_id: str, video: str, fingerprint: str) -> dict:
    evidence = {
        "positionHash": f"position-{case_id}",
        "boardFingerprint": fingerprint,
        "gameIdentity": f"game-{case_id}",
        "pedagogy": {"mechanism": ["先说明机制"], "boundary": "不外推整盘。"},
        "katagoFacts": {
            "trustedArtifactRef": {"artifactSha256": "c" * 64},
        },
    }
    return {
        "messages": [
            {"role": "system", "content": "只依据证据回答。"},
            {"role": "user", "content": "证据：" + json.dumps(evidence, ensure_ascii=False) + "\n问题：为什么？"},
            {"role": "assistant", "content": '{"answer":"说明机制与边界。","followUps":["继续看具体次序吗？"]}'},
        ],
        "metadata": {
            "id": case_id,
            "license": "creator-authorized",
            "commercialDeployment": False,
            "splitGroup": f"video:{video}",
            "videoId": video,
            "target": "actual",
            "authorizationId": "auth-mingyue-tanqi-20260801",
            "reviewApprovalId": f"approval-{case_id}",
            "reviewerId": "reviewer-alimoqi-go-v1",
            "sourceChainBindingSha256": "a" * 64,
            "reviewInputHashes": {"unitContentSha256": "b" * 64},
        },
    }


def test_exact_720_award_projection() -> None:
    project = support.build_project_rows()
    public = support.build_public_rows(TRAINING_ROOT / "data" / "classical_sft_train.jsonl")
    creator_train = [creator(f"creator-train-{i}", f"BVTRAIN{i:03d}", f"train-{i}") for i in range(48)]
    creator_dev = [creator(f"creator-dev-{i}", f"BVDEV{i:03d}", f"dev-{i}") for i in range(8)]
    creator_test = [creator(f"creator-test-{i}", f"BVTEST{i:03d}", f"test-{i}") for i in range(8)]
    by_split, manifest = corpus.compile_corpus(
        creator_train=creator_train,
        creator_dev=creator_dev,
        creator_test=creator_test,
        project_rows=project,
        public_rows=public,
        required_train_rows=720,
        required_task_counts={"planner": 216, "answer": 288, "followup": 144, "memory_privacy": 72},
        required_train_source_cases={"creator_authorized": 48, "project_original": 96, "public_domain": 64},
    )
    assert len(by_split["train"]) == 720
    assert manifest["passed"] is True
    assert manifest["taskCounts"] == {"planner": 216, "answer": 288, "followup": 144, "memory_privacy": 72}
    assert manifest["trainSourceCaseCounts"] == {
        "creator_authorized": 48,
        "project_original": 96,
        "public_domain": 64,
    }
