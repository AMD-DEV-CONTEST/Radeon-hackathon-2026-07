import json
import os
import subprocess

git_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd='/home/cesarops/cesarops_push').decode().strip()

identity = {
    "suite_id": "thomas-translator",
    "suite_version": "v1.0.0",
    "fixture_count": 7,
    "fixture_names": [
        "thomas_simple_ready",
        "thomas_clarification_ambiguous",
        "thomas_non_goal_boundary",
        "thomas_security_boundary",
        "thomas_deferred_idea_no_leak",
        "thomas_multi_constraint_coordinated",
        "thomas_scope_violation_reject"
    ],
    "fixture_hashes": {},
    "prompt_hashes": {},
    "policy_version": "v1",
    "validator_version": "v1",
    "scoring_version": "v1",
    "thresholds": {
        "hard_constraint_recall": 1.0,
        "non_goal_recall": 1.0
    },
    "repair_pass_rules": "re-run on invalid json",
    "repeat_count": 10,
    "expected_schema": "CodeMissionDraft",
    "current_git_commit": git_commit
}

os.makedirs('reports/qualification/thomas-translator', exist_ok=True)
with open('reports/qualification/thomas-translator/suite_identity.json', 'w') as f:
    json.dump(identity, f, indent=4)

print("Generated suite_identity.json")
