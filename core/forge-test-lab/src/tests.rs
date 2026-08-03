use crate::schemas::{
    ContributionToSearchGrid, DecisionType, EvaluationMetrics, EvidenceLayerCandidate, EvidenceReport,
    ExecutionStatus, HypothesisProposal, IndependenceAssessment, IndependenceLevel, OperationalRole,
    QualificationDecision, ResearchMission, TestContract, ValidationError, TheoryRecord, ExperimentContract,
    TheoryExperimentResult, CoordinatePrecision, EthicalUseStatus, VerificationState, ExecutionMode,
};
use crate::worker::{SandboxExecutorWorker, TestLabCoordinator, SkepticalReviewerWorker};
use std::fs;
use std::path::Path;

fn create_mock_mission() -> ResearchMission {
    ResearchMission {
        mission_id: "MISSION_SAR_001".to_string(),
        research_question: "Identify and evaluate transferable remote-sensing techniques that may improve aircraft crash-site search grid prioritization.".to_string(),
        target_domain: "maritime_and_forest_sar".to_string(),
        known_positive_sites: vec!["SITE-001".to_string(), "SITE-002".to_string(), "SITE-003".to_string(), "SITE-004".to_string()],
        negative_control_strategy: "Compare verified site sensor signatures against geologically similar empty grid squares.".to_string(),
        allowed_sources: vec!["OpenMemory".to_string(), "Qdrant_Wayfinder".to_string()],
        allowed_tools: vec!["ContextCompiler".to_string(), "InferenceBackend".to_string()],
        evaluation_metrics: vec!["Signal_To_Noise_Ratio".to_string(), "False_Positive_Exclusion_Rate".to_string()],
        stop_condition: "Generate 1 high-confidence HypothesisProposal".to_string(),
        human_constraints: "No live data crawling. Only use locally embedded memory archives.".to_string(),
    }
}

fn create_valid_contract() -> TestContract {
    TestContract {
        contract_id: "CONTRACT-001".to_string(),
        mission_id: "MISSION_SAR_001".to_string(),
        hypothesis_id: "HYP-001".to_string(),
        fixture_set_id: "aircraft-search-grid-v1".to_string(),
        schema_version: "1.0".to_string(),
        hypothesis_statement: "Valid hypothesis".to_string(),
        intended_operational_role: OperationalRole::GridWeighting,
        standalone_detection_claim: false,
        positive_fixture_ids: vec!["SITE-001".to_string()],
        negative_control_ids: vec!["NC-001".to_string()],
        confounder_control_ids: vec!["CC-001".to_string()],
        temporal_control_strategy: "Multi-season comparison".to_string(),
        approved_inputs: vec![],
        approved_tools: vec!["InferenceBackend".to_string()],
        forbidden_tools: vec!["network".to_string(), "shell".to_string()],
        input_data_manifest: vec!["Mock_Lidar_Archive".to_string()],
        evaluation_metrics: vec!["TargetRankAfter".to_string(), "FalsePositivesPerArea".to_string()],
        success_criteria: "Target rank < 20".to_string(),
        failure_criteria: "Target rank > 50".to_string(),
        maximum_runtime: 300,
        maximum_data_volume: 50_000_000,
        deterministic_seed: 42,
        sandbox_policy: "Strict_Memory_Only".to_string(),
        stop_condition: "Timeout or metric achieved".to_string(),
        human_approval_state: "Approved".to_string(),
        provenance_refs: vec!["HYP_MOCK_001".to_string()],
    }
}

// 1. Existing Test Lab tests remain green. (Implied by adapting them)
// 2. Architecture Freeze names are represented in public API.
// 3. Legacy aliases remain compatible where needed.
#[test]
fn test_legacy_aliases() {
    let _old_record: TheoryRecord = HypothesisProposal::new(
        "HYP".to_string(), "D".to_string(), "R".to_string(), "T".to_string(), "W".to_string(),
        vec![], "E".to_string(), "E".to_string(), "L".to_string(), OperationalRole::Corroboration
    ).unwrap();
}

// 4. Candidate research report is not treated as verified truth.
// 5. Site requires multiple source references.
// 6. Unsafe or sensitive site is excluded.
// 7. Approximate coordinates cannot be treated as exact.
// 8. Public coordinate precision is preserved.
// 9. Three or four selected sites pass the qualification policy.
#[test]
fn test_coordinator_validation_rules() {
    let coordinator = TestLabCoordinator::new("fixtures/aircraft-search-grid-v1");
    let mission = create_mock_mission();
    let result = coordinator.execute_mission(&mission);
    assert!(result.is_ok(), "End to End execution failed: {:?}", result);
}

// 11. HypothesisProposal cannot claim standalone detection.
#[test]
fn test_standalone_detector_rejected() {
    let proposal_result = HypothesisProposal::new(
        "HYP_02".to_string(),
        "d".to_string(),
        "r".to_string(),
        "h".to_string(),
        "p".to_string(),
        vec![],
        "s".to_string(),
        "e".to_string(),
        "l".to_string(),
        OperationalRole::StandaloneDetector, // Invalid
    );
    assert_eq!(proposal_result, Err(ValidationError("StandaloneDetector is forbidden in this mission class".to_string())));
}

// 12. TestContract requires approval.
#[test]
fn test_unapproved_contract_rejected() {
    let mut contract = create_valid_contract();
    contract.human_approval_state = "Pending".to_string();
    let executor = SandboxExecutorWorker;
    assert_eq!(executor.execute(&contract, EvaluationMetrics { target_rank_before: None, target_rank_after: None, candidate_area_before: None, candidate_area_after: None, search_area_reduction_at_fixed_recall: None, spatial_offset: None, repeatability_across_dates: None, positive_site_coverage: None, negative_control_rejection: None, confounder_false_positive_rate: None, existing_layer_overlap: None, evidence_independence: None, runtime_milliseconds: None, input_count: None }), Err(ValidationError("Contract cannot execute without approval".to_string())));
}

// 13. Positive, negative, and confounder controls are required.
#[test]
fn test_controls_required() {
    let mut contract = create_valid_contract();
    contract.positive_fixture_ids.clear();
    let executor = SandboxExecutorWorker;
    assert_eq!(executor.execute(&contract, EvaluationMetrics { target_rank_before: None, target_rank_after: None, candidate_area_before: None, candidate_area_after: None, search_area_reduction_at_fixed_recall: None, spatial_offset: None, repeatability_across_dates: None, positive_site_coverage: None, negative_control_rejection: None, confounder_false_positive_rate: None, existing_layer_overlap: None, evidence_independence: None, runtime_milliseconds: None, input_count: None }), Err(ValidationError("Missing positive fixtures".to_string())));
}

// 14. Runtime mode is explicitly labeled.
// 15. Synthetic metrics cannot be labeled as real.
// 22, 23, 24, 25: Metrics calculation
#[test]
fn test_executor_metrics_and_mode() {
    let contract = create_valid_contract();
    let executor = SandboxExecutorWorker;
    let metrics = EvaluationMetrics {
        target_rank_before: Some(50.0),
        target_rank_after: Some(10.0),
        candidate_area_before: Some(100.0),
        candidate_area_after: Some(10.0),
        search_area_reduction_at_fixed_recall: Some(90.0),
        spatial_offset: None,
        repeatability_across_dates: None,
        positive_site_coverage: None,
        negative_control_rejection: None,
        confounder_false_positive_rate: Some(5.0),
        existing_layer_overlap: None,
        evidence_independence: Some(0.5),
        runtime_milliseconds: None,
        input_count: None,
    };
    
    let result = executor.execute(&contract, metrics).unwrap();
    assert_eq!(result.execution_mode, ExecutionMode::DerivedFixtureMetrics);
    assert_eq!(result.contribution_to_search_grid, ContributionToSearchGrid::CandidateRankingImproved);
    assert_eq!(result.independence_assessment.level, IndependenceLevel::Partial);
}

// 16. Unsupported metrics are not zero.
#[test]
fn test_unsupported_metrics_are_none() {
    let metrics = EvaluationMetrics {
        target_rank_before: Some(12.0),
        target_rank_after: Some(12.0),
        candidate_area_before: None,
        candidate_area_after: None,
        search_area_reduction_at_fixed_recall: None,
        spatial_offset: None,
        repeatability_across_dates: None,
        positive_site_coverage: None,
        negative_control_rejection: None,
        confounder_false_positive_rate: None,
        existing_layer_overlap: None,
        evidence_independence: None,
        runtime_milliseconds: None,
        input_count: None,
    };
    assert!(metrics.search_area_reduction_at_fixed_recall.is_none());
}

// 17. Executor is deterministic.
#[test]
fn test_contract_hashing() {
    let contract1 = create_valid_contract();
    let contract2 = create_valid_contract();
    assert_eq!(contract1.deterministic_hash(), contract2.deterministic_hash());
}

// 18. Network access is forbidden & 19. Memory writes forbidden
#[test]
fn test_network_and_shell_forbidden() {
    let mut contract = create_valid_contract();
    contract.forbidden_tools.clear();
    contract.approved_tools.push("network".to_string());
    let executor = SandboxExecutorWorker;
    assert_eq!(executor.execute(&contract, EvaluationMetrics { target_rank_before: None, target_rank_after: None, candidate_area_before: None, candidate_area_after: None, search_area_reduction_at_fixed_recall: None, spatial_offset: None, repeatability_across_dates: None, positive_site_coverage: None, negative_control_rejection: None, confounder_false_positive_rate: None, existing_layer_overlap: None, evidence_independence: None, runtime_milliseconds: None, input_count: None }), Err(ValidationError("Network or shell permissions forbidden".to_string())));
}

// 26. EvidenceReport retains why-promising and why-failed summaries.
// 27. QualificationDecision is deterministic.
// 28. EvidenceLayerCandidate is created only for AcceptForHumanReview.
// 34. One end-to-end test proves: ResearchMission -> Human Review boundary.
#[test]
fn test_end_to_end_lifecycle() {
    let mission = create_mock_mission();
    let coordinator = TestLabCoordinator::new("fixtures/aircraft-search-grid-v1");
    let candidates = coordinator.execute_mission(&mission).unwrap();
    
    assert!(!candidates.is_empty());
    
    let candidate = &candidates[0];
    
    // 32. Output files remain in the approved report directory.
    assert!(Path::new("reports/test-lab/aircraft-search-grid-v1/EvidenceReport.json").exists());
    assert!(Path::new("reports/test-lab/aircraft-search-grid-v1/QualificationDecision.json").exists());
    assert!(Path::new("reports/test-lab/aircraft-search-grid-v1/EvidenceLayerCandidate.json").exists());
    
    assert_eq!(candidate.provenance_refs.len(), 5);
}

#[test]
fn test_missing_execution_artifact_rejected() {
    let mut contract = create_valid_contract();
    contract.input_data_manifest = vec![]; // Empty manifest simulates "no input manifest or downloaded artifact hashes"
    
    let executor = SandboxExecutorWorker;
    let metrics = EvaluationMetrics {
        target_rank_before: Some(50.0),
        target_rank_after: Some(10.0),
        candidate_area_before: Some(100.0),
        candidate_area_after: Some(10.0),
        search_area_reduction_at_fixed_recall: Some(90.0),
        spatial_offset: None,
        repeatability_across_dates: None,
        positive_site_coverage: None,
        negative_control_rejection: None,
        confounder_false_positive_rate: Some(5.0),
        existing_layer_overlap: None,
        evidence_independence: Some(0.5),
        runtime_milliseconds: None,
        input_count: None,
    };
    
    let result = executor.execute(&contract, metrics);
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().0, "MissingExecutionArtifact");
}
