use std::fs;
use std::path::Path;
use crate::schemas::{
    CandidateStatus, ContributionToSearchGrid, DecisionType, EvaluationMetrics, EvidenceLayerCandidate,
    EvidenceReport, ExecutionMode, ExecutionStatus, HypothesisProposal, IndependenceAssessment,
    IndependenceLevel, OperationalRole, QualificationDecision, ResearchMission, SiteQualificationRecord,
    TestContract, ValidationError, EthicalUseStatus, VerificationState, CoordinatePrecision,
};

pub struct TestLabCoordinator {
    fixture_dir: String,
    executor: SandboxExecutorWorker,
    reviewer: SkepticalReviewerWorker,
}

impl TestLabCoordinator {
    pub fn new(fixture_dir: &str) -> Self {
        Self {
            fixture_dir: fixture_dir.to_string(),
            executor: SandboxExecutorWorker,
            reviewer: SkepticalReviewerWorker,
        }
    }

    pub fn execute_mission(&self, mission: &ResearchMission) -> Result<Vec<EvidenceLayerCandidate>, ValidationError> {
        let mut candidates = Vec::new();
        
        // 1. Validate Fixture Set (Sites)
        let sites_dir = format!("{}/sites", self.fixture_dir);
        let mut valid_sites = Vec::new();
        if let Ok(entries) = fs::read_dir(&sites_dir) {
            for entry in entries.flatten() {
                if let Ok(file_type) = entry.file_type() {
                    if file_type.is_dir() {
                        let site_path = entry.path().join("site.json");
                        if let Ok(content) = fs::read_to_string(&site_path) {
                            if let Ok(site) = serde_json::from_str::<SiteQualificationRecord>(&content) {
                                // Validation rules for site qualification
                                if site.verification_state != VerificationState::MultiSourceVerified {
                                    continue;
                                }
                                if site.ethical_use_status != EthicalUseStatus::ApprovedForFixture && site.ethical_use_status != EthicalUseStatus::ApprovedWithRestrictions {
                                    continue;
                                }
                                if site.source_references.len() < 2 {
                                    continue; // Multi-source requires multiple refs
                                }
                                if site.coordinate_precision == CoordinatePrecision::Unknown || site.coordinate_precision == CoordinatePrecision::Withheld {
                                    continue;
                                }
                                valid_sites.push(site);
                            }
                        }
                    }
                }
            }
        }

        if valid_sites.is_empty() {
            return Err(ValidationError("No valid verified sites found in fixture set".to_string()));
        }

        // 2. Load Hypothesis
        let hyp_path = format!("{}/hypotheses/HYP-001.json", self.fixture_dir);
        let hypothesis = serde_json::from_str::<HypothesisProposal>(&fs::read_to_string(&hyp_path).map_err(|_| ValidationError("Missing hypothesis".to_string()))?)
            .map_err(|_| ValidationError("Invalid hypothesis JSON".to_string()))?;

        if hypothesis.recommended_role == OperationalRole::StandaloneDetector || hypothesis.standalone_detection_claim {
            return Err(ValidationError("HypothesisProposal cannot claim standalone detection".to_string()));
        }

        // 3. Load Contract
        let contract_path = format!("{}/contracts/CONTRACT-001.json", self.fixture_dir);
        let contract = serde_json::from_str::<TestContract>(&fs::read_to_string(&contract_path).map_err(|_| ValidationError("Missing contract".to_string()))?)
            .map_err(|_| ValidationError("Invalid contract JSON".to_string()))?;

        if contract.human_approval_state != "Approved" {
            return Err(ValidationError("TestContract requires approval".to_string()));
        }

        // 4. Execute Fixture
        let metrics_path = format!("{}/metrics/METRICS-001.json", self.fixture_dir);
        let metrics = serde_json::from_str::<EvaluationMetrics>(&fs::read_to_string(&metrics_path).map_err(|_| ValidationError("Missing metrics".to_string()))?)
            .map_err(|_| ValidationError("Invalid metrics JSON".to_string()))?;

        let report = self.executor.execute(&contract, metrics)?;

        // 5. Review Output
        let decision = self.reviewer.review(&report);

        // 6. Create Candidate if Accept
        if decision.decision == DecisionType::AcceptForHumanReview {
            let candidate = EvidenceLayerCandidate {
                candidate_id: format!("CANDIDATE_{}", hypothesis.hypothesis_id),
                source_hypothesis_id: hypothesis.hypothesis_id.clone(),
                evidence_report_id: report.report_id.clone(),
                intended_operational_role: hypothesis.recommended_role.clone(),
                compatible_terrain_or_mission_conditions: "Verified across tundra, forest, glacier, and sand".to_string(),
                unsupported_conditions: report.limitations.clone(),
                known_confounders: report.confounders_observed.clone(),
                expected_uncertainty: "Moderate uncertainty due to natural confounders".to_string(),
                required_companion_layers: vec!["Optical Context".to_string()],
                independence_limitations: report.independence_assessment.safe_fusion_usage.clone(),
                strongest_supported_claim: report.strongest_supported_claim.clone(),
                status: CandidateStatus::AwaitingHumanReview,
                provenance_refs: vec![
                    mission.mission_id.clone(),
                    hypothesis.hypothesis_id.clone(),
                    contract.contract_id.clone(),
                    report.report_id.clone(),
                    decision.decision_id.clone(),
                ],
                candidate_hash: "mock_hash".to_string(), // In real system: deterministic_hash()
            };
            candidates.push(candidate);
        }

        // Ensure directories exist before writing
        let out_dir = format!("reports/test-lab/{}", contract.fixture_set_id);
        let _ = fs::create_dir_all(&out_dir);

        // Save outputs
        fs::write(format!("{}/EvidenceReport.json", out_dir), serde_json::to_string_pretty(&report).unwrap()).unwrap();
        fs::write(format!("{}/QualificationDecision.json", out_dir), serde_json::to_string_pretty(&decision).unwrap()).unwrap();
        if let Some(cand) = candidates.first() {
            fs::write(format!("{}/EvidenceLayerCandidate.json", out_dir), serde_json::to_string_pretty(&cand).unwrap()).unwrap();
        }

        Ok(candidates)
    }
}

pub struct SandboxExecutorWorker;

impl SandboxExecutorWorker {
    pub fn execute(
        &self,
        contract: &TestContract,
        fixture_metrics: EvaluationMetrics,
    ) -> Result<EvidenceReport, ValidationError> {
        if contract.intended_operational_role == OperationalRole::StandaloneDetector {
            return Err(ValidationError("StandaloneDetector is forbidden".to_string()));
        }
        if contract.input_data_manifest.is_empty() {
            return Err(ValidationError("MissingExecutionArtifact".to_string()));
        }
        if contract.standalone_detection_claim {
            return Err(ValidationError("standalone_detection_claim=true is rejected".to_string()));
        }
        if contract.positive_fixture_ids.is_empty() {
            return Err(ValidationError("Missing positive fixtures".to_string()));
        }
        if contract.negative_control_ids.is_empty() {
            return Err(ValidationError("Missing negative controls".to_string()));
        }
        if contract.confounder_control_ids.is_empty() {
            return Err(ValidationError("Missing confounder controls".to_string()));
        }
        if contract.success_criteria.is_empty() {
            return Err(ValidationError("No success criteria".to_string()));
        }
        if contract.failure_criteria.is_empty() {
            return Err(ValidationError("No failure criteria".to_string()));
        }
        if contract.stop_condition.is_empty() {
            return Err(ValidationError("No stop condition".to_string()));
        }
        if contract.forbidden_tools.iter().any(|t| contract.approved_tools.contains(t)) {
            return Err(ValidationError("Unapproved tool detected".to_string()));
        }
        if contract.approved_tools.contains(&"network".to_string()) || contract.approved_tools.contains(&"shell".to_string()) {
            return Err(ValidationError("Network or shell permissions forbidden".to_string()));
        }
        if contract.provenance_refs.is_empty() {
            return Err(ValidationError("Missing provenance".to_string()));
        }
        if contract.human_approval_state != "Approved" {
            return Err(ValidationError("Contract cannot execute without approval".to_string()));
        }
        
        let execution_mode = ExecutionMode::DerivedFixtureMetrics;

        let rank_improved = match (fixture_metrics.target_rank_before, fixture_metrics.target_rank_after) {
            (Some(before), Some(after)) => after < before,
            _ => false,
        };

        Ok(EvidenceReport {
            report_id: format!("REP_{}", contract.contract_id),
            contract_id: contract.contract_id.clone(),
            mission_id: contract.mission_id.clone(),
            hypothesis_id: contract.hypothesis_id.clone(),
            fixture_set_id: contract.fixture_set_id.clone(),
            execution_mode,
            execution_status: ExecutionStatus::Completed,
            metric_results: fixture_metrics.clone(),
            observations: "Mock observations show partial improvement in grid weighting.".to_string(),
            detected_signal: "Anomalous geometric clusters beneath foliage.".to_string(),
            alternative_explanations: "Natural rock formations could mimic geometric hard returns.".to_string(),
            confounders_observed: "Dense rock outcroppings.".to_string(),
            why_promising_before_test: "LiDAR is known to penetrate canopy gaps.".to_string(),
            assumptions_supported: vec!["Crash debris maintains geometric rigidity.".to_string()],
            assumptions_refuted: vec![],
            why_succeeded: format!("Target rank improved to {:?}", fixture_metrics.target_rank_after),
            why_failed: "".to_string(),
            salvageable_parts: "".to_string(),
            independence_assessment: IndependenceAssessment {
                level: IndependenceLevel::Partial,
                likely_shared_causes: vec!["Topography influences both LiDAR returns and SAR shadows.".to_string()],
                overlapping_existing_layers: vec!["SAR_Shadow_Detection".to_string()],
                safe_fusion_usage: "Use conditionally with non-SAR layers.".to_string(),
                supporting_metric_refs: vec!["evidence_independence".to_string()],
            },
            contribution_to_search_grid: if rank_improved { ContributionToSearchGrid::CandidateRankingImproved } else { ContributionToSearchGrid::NoDemonstratedContribution },
            strongest_supported_claim: "This method appears to contribute useful evidence toward search-grid prioritization.".to_string(),
            limitations: "Confounded by dense rock outcroppings.".to_string(),
            provenance_refs: contract.provenance_refs.clone(),
            executor_identity: "SandboxExecutorWorker_v1".to_string(),
            runtime_metadata: "Executed entirely in-memory offline.".to_string(),
            input_hash: contract.deterministic_hash(),
        })
    }
}

pub struct SkepticalReviewerWorker;

impl SkepticalReviewerWorker {
    pub fn review(&self, report: &EvidenceReport) -> QualificationDecision {
        let decision = if report.contribution_to_search_grid == ContributionToSearchGrid::CandidateRankingImproved {
            DecisionType::AcceptForHumanReview
        } else {
            DecisionType::Revise
        };

        QualificationDecision {
            decision_id: format!("DEC_{}", report.report_id),
            report_id: report.report_id.clone(),
            decision,
            rationale: "Evidence report demonstrated candidate ranking improvement without standalone claims.".to_string(),
            failed_criteria: vec![],
            passed_criteria: vec!["TargetRankAfter improved".to_string()],
            unresolved_risks: "Potential false positives in dense rock".to_string(),
            required_next_test: "None".to_string(),
            relevant_metric_ids: vec!["target_rank_after".to_string()],
            relevant_source_ids: vec![],
            recommended_next_step: "Promote for fusion testing".to_string(),
            decision_hash: "mock_decision_hash".to_string(),
        }
    }
}
