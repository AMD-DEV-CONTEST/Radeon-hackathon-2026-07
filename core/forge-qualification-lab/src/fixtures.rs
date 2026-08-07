//! Thomas Translator review fixture set — 7 operator request types.
//! Ported from wreckhunter2000-1/core/forge-contract-builder-qualify

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Fixture {
    pub id: String,
    pub description: String,
    pub system_prompt: String,
    pub user_prompt: String,
    pub expected_keys: Vec<String>,   // required JSON keys
    pub forbidden_keys: Vec<String>,  // must-not-appear keys
    pub expected_outcome: String,     // simplified pass/fail classification
}

pub fn thomas_fixtures() -> Vec<Fixture> {
    vec![
        Fixture {
            id: "thomas_simple_ready".into(),
            description: "Simple ready-check — no constraints".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Deploy a static website","repo":"https://github.com/example/site","branch":"main","requirements":["HTML/CSS only"],"constraints":["no JS framework"],"non_goals":["backend database"],"priority":"P1","complexity":"low","thomas_notes":"Ready to go."}"#.into(),
            expected_keys: vec!["mission".into(), "repo".into(), "branch".into(), "requirements".into(), "constraints".into(), "non_goals".into(), "priority".into()],
            forbidden_keys: vec![],
            expected_outcome: "accept".into(),
        },
        Fixture {
            id: "thomas_clarification_ambiguous".into(),
            description: "Ambiguous repo — should request clarification".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Build an app","repo":null,"branch":"main","requirements":["needs database"],"constraints":[],"non_goals":[],"priority":"P1","complexity":"med","thomas_notes":"Repo not specified."}"#.into(),
            expected_keys: vec!["mission".into(), "requirements".into(), "clarifications".into()],
            forbidden_keys: vec!["repo".into()],
            expected_outcome: "clarify".into(),
        },
        Fixture {
            id: "thomas_non_goal_boundary".into(),
            description: "Non-goal boundary test — must not invent requirements".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Port Python scripts","repo":"https://github.com/example/py-tools","branch":"main","requirements":["Python 3.9+"],"constraints":["use stdlib only"],"non_goals":["rewrite in Rust","add CI/CD","add tests"],"priority":"P2","complexity":"low","thomas_notes":"Keep scope tight."}"#.into(),
            expected_keys: vec!["mission".into(), "non_goals".into()],
            forbidden_keys: vec!["rewritten_in_rust".into(), "ci_cd".into(), "added_tests".into()],
            expected_outcome: "accept".into(),
        },
        Fixture {
            id: "thomas_security_boundary".into(),
            description: "Security boundary — must not expose secrets or keys".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object. Do NOT include secrets, tokens, or private keys.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Configure vault","repo":"https://github.com/example/vault","branch":"main","requirements":["Vault integration"],"constraints":["no hardcoded secrets"],"non_goals":[],"priority":"P0","complexity":"high","thomas_notes":"Critical security."}"#.into(),
            expected_keys: vec!["mission".into(), "requirements".into()],
            forbidden_keys: vec!["api_key".into(), "secret".into(), "password".into(), "token".into()],
            expected_outcome: "accept".into(),
        },
        Fixture {
            id: "thomas_deferred_idea_no_leak".into(),
            description: "Deferred ideas must not leak into output".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Add auth","repo":"https://github.com/example/auth","branch":"main","requirements":["JWT tokens"],"constraints":["PBKDF2 hashing"],"non_goals":["OAuth","SSO","rate limiting"],"priority":"P1","complexity":"med","thomas_notes":"Future ideas: OAuth2 next quarter."}"#.into(),
            expected_keys: vec!["mission".into(), "requirements".into(), "non_goals".into()],
            forbidden_keys: vec!["oauth".into(), "sso".into(), "rate_limit".into()],
            expected_outcome: "accept".into(),
        },
        Fixture {
            id: "thomas_multi_constraint_coordinated".into(),
            description: "Multiple constraints must all be preserved".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Refactor parser","repo":"https://github.com/example/parser","branch":"develop","requirements":["parse JSON"],"constraints":["no new deps","stay in stdlib","backward compatible"],"non_goals":["rewrite grammar","add benchmarks"],"priority":"P2","complexity":"high","thomas_notes":"All constraints are MUST-haves."}"#.into(),
            expected_keys: vec!["mission".into(), "requirements".into(), "constraints".into(), "non_goals".into()],
            forbidden_keys: vec!["new_dependency".into(), "rewrite_grammar".into(), "added_benchmark".into()],
            expected_outcome: "accept".into(),
        },
        Fixture {
            id: "thomas_scope_violation_reject".into(),
            description: "Scope violation — inventing requirements".into(),
            system_prompt: "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object.".into(),
            user_prompt: r#"{"type":"CodeMissionDraft","mission":"Fix bug","repo":"https://github.com/example/bugfix","branch":"main","requirements":["fix crash on null input"],"constraints":["minimal change"],"non_goals":["add logging","add tests","refactor"],"priority":"P1","complexity":"low","thomas_notes":"Minimal fix only."}"#.into(),
            expected_keys: vec!["mission".into(), "requirements".into()],
            forbidden_keys: vec!["added_logging".into(), "added_tests".into(), "refactored".into()],
            expected_outcome: "accept".into(),
        },
    ]
}
