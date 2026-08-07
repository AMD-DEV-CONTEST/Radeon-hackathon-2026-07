use serde::{Deserialize, Serialize};
use sha2::{Sha256, Digest};
use hex;

pub fn deterministic_hash<T: Serialize>(obj: &T) -> String {
    let serialized = serde_json::to_string(obj).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    hex::encode(hasher.finalize())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResearchMission {
    pub mission_id: String,
    pub research_question: String,
    pub target_domain: String,
    pub known_positive_sites: Vec<String>,
    pub negative_control_strategy: String,
    pub allowed_sources: Vec<String>,
    pub allowed_tools: Vec<String>,
    pub evaluation_metrics: Vec<String>,
    pub stop_condition: String,
    pub human_constraints: String,
}

impl ResearchMission {
    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum CoordinatePrecision {
    ExactPublic,
    ApproximatePublic,
    BoundedAreaOnly,
    Withheld,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum EthicalUseStatus {
    ApprovedForFixture,
    ApprovedWithRestrictions,
    RequiresHumanReview,
    Excluded,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum VerificationState {
    Unverified,
    SingleSource,
    MultiSourceVerified,
    ConflictingSources,
    Rejected,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SiteQualificationRecord {
    pub site_id: String,
    pub display_name: String,
    pub aircraft_type: String,
    pub country_or_region: String,
    pub coordinate_representation: String,
    pub coordinate_precision: CoordinatePrecision,
    pub coordinate_publication_status: String,
    pub wreckage_present_status: String,
    pub terrain_class: String,
    pub access_or_protection_status: String,
    pub ethical_use_status: EthicalUseStatus,
    pub imagery_sources: Vec<String>,
    pub imagery_date_range: String,
    pub expected_evidence_contributions: Vec<String>,
    pub likely_confounders: Vec<String>,
    pub positive_fixture_radius: u64,
    pub negative_control_strategy: String,
    pub temporal_control_strategy: String,
    pub source_references: Vec<String>,
    pub verification_state: VerificationState,
    pub exclusion_reasons: String,
    pub reviewed_at: String,
    pub record_hash: String,
}

impl SiteQualificationRecord {
    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum OperationalRole {
    CandidateGeneration,
    GridWeighting,
    Corroboration,
    Exclusion,
    Localization,
    StandaloneDetector,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HypothesisProposal {
    pub hypothesis_id: String,
    pub source_domain: String,
    pub original_reference: String,
    pub transfer_hypothesis: String,
    pub why_promising: String,
    pub assumptions: Vec<String>,
    pub expected_signal: String,
    pub experiment_design: String,
    pub limitations: String,
    pub recommended_role: OperationalRole,
    #[serde(default)]
    pub standalone_detection_claim: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ValidationError(pub String);

impl HypothesisProposal {
    pub fn new(
        hypothesis_id: String,
        source_domain: String,
        original_reference: String,
        transfer_hypothesis: String,
        why_promising: String,
        assumptions: Vec<String>,
        expected_signal: String,
        experiment_design: String,
        limitations: String,
        recommended_role: OperationalRole,
    ) -> Result<Self, ValidationError> {
        if recommended_role == OperationalRole::StandaloneDetector {
            return Err(ValidationError("StandaloneDetector is forbidden in this mission class".to_string()));
        }

        Ok(Self {
            hypothesis_id,
            source_domain,
            original_reference,
            transfer_hypothesis,
            why_promising,
            assumptions,
            expected_signal,
            experiment_design,
            limitations,
            recommended_role,
            standalone_detection_claim: false,
        })
    }

    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TestContract {
    pub contract_id: String,
    pub mission_id: String,
    pub hypothesis_id: String,
    #[serde(default)]
    pub fixture_set_id: String,
    pub schema_version: String,
    pub hypothesis_statement: String,
    pub intended_operational_role: OperationalRole,
    pub standalone_detection_claim: bool,
    pub positive_fixture_ids: Vec<String>,
    pub negative_control_ids: Vec<String>,
    pub confounder_control_ids: Vec<String>,
    pub temporal_control_strategy: String,
    #[serde(default)]
    pub approved_inputs: Vec<String>,
    pub approved_tools: Vec<String>,
    pub forbidden_tools: Vec<String>,
    pub input_data_manifest: Vec<String>,
    pub evaluation_metrics: Vec<String>,
    pub success_criteria: String,
    pub failure_criteria: String,
    pub maximum_runtime: u64,
    pub maximum_data_volume: u64,
    #[serde(default)]
    pub deterministic_seed: u64,
    pub sandbox_policy: String,
    pub stop_condition: String,
    pub human_approval_state: String,
    pub provenance_refs: Vec<String>,
}

impl TestContract {
    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EvaluationMetrics {
    pub target_rank_before: Option<f64>,
    pub target_rank_after: Option<f64>,
    pub candidate_area_before: Option<f64>,
    pub candidate_area_after: Option<f64>,
    pub search_area_reduction_at_fixed_recall: Option<f64>,
    pub positive_site_coverage: Option<f64>,
    pub negative_control_rejection: Option<f64>,
    pub confounder_false_positive_rate: Option<f64>,
    pub repeatability_across_dates: Option<f64>,
    pub spatial_offset: Option<f64>,
    pub existing_layer_overlap: Option<f64>,
    pub evidence_independence: Option<f64>,
    pub runtime_milliseconds: Option<f64>,
    pub input_count: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum ExecutionMode {
    RealFixtureData,
    DerivedFixtureMetrics,
    PipelineValidationOnly,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum ExecutionStatus {
    Approved,
    Running,
    Completed,
    Failed,
    InvalidContract,
    ResourceLimitReached,
    Cancelled,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum IndependenceLevel {
    Low,
    Partial,
    High,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IndependenceAssessment {
    pub level: IndependenceLevel,
    pub likely_shared_causes: Vec<String>,
    pub overlapping_existing_layers: Vec<String>,
    pub safe_fusion_usage: String,
    pub supporting_metric_refs: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum ContributionToSearchGrid {
    NoDemonstratedContribution,
    CandidateRankingImproved,
    SearchAreaReduced,
    FalsePositiveBurdenReduced,
    ExclusionValueDemonstrated,
    CorroborationValueDemonstrated,
    LocalizationImproved,
    Inconclusive,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EvidenceReport {
    pub report_id: String,
    pub contract_id: String,
    pub mission_id: String,
    pub hypothesis_id: String,
    #[serde(default)]
    pub fixture_set_id: String,
    pub execution_mode: ExecutionMode,
    pub execution_status: ExecutionStatus,
    pub metric_results: EvaluationMetrics,
    pub observations: String,
    pub detected_signal: String,
    pub alternative_explanations: String,
    pub confounders_observed: String,
    pub why_promising_before_test: String,
    pub assumptions_supported: Vec<String>,
    pub assumptions_refuted: Vec<String>,
    pub why_succeeded: String,
    pub why_failed: String,
    pub salvageable_parts: String,
    pub independence_assessment: IndependenceAssessment,
    pub contribution_to_search_grid: ContributionToSearchGrid,
    pub strongest_supported_claim: String,
    pub limitations: String,
    pub provenance_refs: Vec<String>,
    pub executor_identity: String,
    pub runtime_metadata: String,
    pub input_hash: String,
}

impl EvidenceReport {
    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum DecisionType {
    AcceptForHumanReview,
    Revise,
    Defer,
    Reject,
    InsufficientEvidence,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct QualificationDecision {
    pub decision_id: String,
    pub report_id: String,
    pub decision: DecisionType,
    pub rationale: String,
    pub failed_criteria: Vec<String>,
    pub passed_criteria: Vec<String>,
    pub unresolved_risks: String,
    pub required_next_test: String,
    pub relevant_metric_ids: Vec<String>,
    pub relevant_source_ids: Vec<String>,
    pub recommended_next_step: String,
    pub decision_hash: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum CandidateStatus {
    AwaitingHumanReview,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EvidenceLayerCandidate {
    pub candidate_id: String,
    pub source_hypothesis_id: String,
    pub evidence_report_id: String,
    pub intended_operational_role: OperationalRole,
    pub compatible_terrain_or_mission_conditions: String,
    pub unsupported_conditions: String,
    pub known_confounders: String,
    pub expected_uncertainty: String,
    pub required_companion_layers: Vec<String>,
    pub independence_limitations: String,
    pub strongest_supported_claim: String,
    pub status: CandidateStatus,
    pub provenance_refs: Vec<String>,
    pub candidate_hash: String,
}

impl EvidenceLayerCandidate {
    pub fn deterministic_hash(&self) -> String {
        deterministic_hash(self)
    }
}

// Legacy Aliases for Sprint 2 Compatibility
pub type TheoryRecord = HypothesisProposal;
pub type ExperimentContract = TestContract;
pub type TheoryExperimentResult = EvidenceReport;
pub type TheoryLabResearchWorker = crate::worker::TestLabCoordinator;
