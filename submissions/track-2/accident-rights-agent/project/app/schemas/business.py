"""Strict contracts for the three traffic-accident business agents.

These models deliberately separate observations, technical-standard checks,
accident responsibility, civil compensation allocation, and insurance payment.
Free-form model text is confined to explanation fields.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.legal import LegalCitation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class MaterialCategory(str, Enum):
    ACCIDENT_DETERMINATION = "accident_determination"
    DELIVERY_INFORMATION = "delivery_information"
    DASHCAM_VIDEO = "dashcam_video"
    SCENE_PHOTOS = "scene_photos"
    ROAD_SIGNAL_EVIDENCE = "road_signal_evidence"
    VEHICLE_REGISTRATION_PLATE = "vehicle_registration_plate"
    VEHICLE_CERTIFICATE_CCC = "vehicle_certificate_ccc"
    VEHICLE_TECHNICAL_PARAMETERS = "vehicle_technical_parameters"
    VEHICLE_NATURE_APPRAISAL = "vehicle_nature_appraisal"
    INQUIRY_RECORD = "inquiry_record"
    MEDICAL_REPAIR_MATERIALS = "medical_repair_materials"
    INSURANCE_POLICY_TERMS = "insurance_policy_terms"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class UploadedMaterial(StrictModel):
    category: MaterialCategory
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    description: str


class EvidenceGap(StrictModel):
    category: MaterialCategory | str
    reason: str
    required_for: list[str] = Field(min_length=1)
    priority: Priority
    collection_method: str
    related_agent: str
    blocks_conclusions: list[str] = Field(default_factory=list)


class QualityIssue(StrictModel):
    code: str
    message: str
    severity: IssueSeverity
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class BlockingIssue(StrictModel):
    code: str
    message: str
    blocked_outputs: list[str] = Field(min_length=1)
    related_missing_categories: list[MaterialCategory | str] = Field(
        default_factory=list
    )


class CaseIntakeResult(StrictModel):
    case_type: str
    uploaded_materials: list[UploadedMaterial]
    missing_required_materials: list[EvidenceGap]
    missing_optional_materials: list[EvidenceGap]
    quality_issues: list[QualityIssue]
    blocking_issues: list[BlockingIssue]
    next_collection_actions: list[EvidenceGap]
    can_continue_analysis: bool
    route_hint: str = Field(pattern=r"^(evidence_ready|missing_evidence)$")


class EvidenceReference(StrictModel):
    fact_id: str
    statement: str
    evidence_ids: list[str] = Field(min_length=1)
    status: str
    confidence: float = Field(ge=0.0, le=1.0)


class TechnicalComparisonStatus(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    NOT_APPLICABLE = "not_applicable"


class ParameterComparison(StrictModel):
    parameter: str
    display_name: str
    observed_value: str | float | int | bool | None = None
    standard_requirement: str
    status: TechnicalComparisonStatus
    explanation: str
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    jurisdiction: str
    effective_date: str
    expiry_date: str | None = None
    source_law_id: str
    source_article: str | None = None


class FactorStatus(str, Enum):
    SUPPORTS_NON_MOTOR = "supports_non_motor_vehicle"
    SUPPORTS_MOTOR = "supports_motor_vehicle"
    NEUTRAL = "neutral"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class VehicleFactor(StrictModel):
    factor: str
    status: FactorStatus
    explanation: str
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class VehicleNatureClassification(str, Enum):
    NON_MOTOR_VEHICLE = "non_motor_vehicle"
    SUSPECTED_MOTOR_VEHICLE = "suspected_motor_vehicle"
    MOTOR_VEHICLE = "motor_vehicle"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class VehicleNatureHypothesis(StrictModel):
    hypothesis_id: str
    classification: VehicleNatureClassification
    probability: float = Field(ge=0.0, le=1.0)
    supporting_fact_ids: list[str] = Field(default_factory=list)
    contradicting_fact_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    compensation_regime_impact: str
    explanation: str


class VehicleNatureResult(StrictModel):
    classification: VehicleNatureClassification
    confidence: float = Field(ge=0.0, le=1.0)
    conclusion_status: str = Field(pattern=r"^(qualified|disputed|blocked)$")
    supporting_facts: list[EvidenceReference]
    contradicting_facts: list[EvidenceReference]
    missing_evidence: list[EvidenceGap]
    parameter_comparison: list[ParameterComparison]
    registration_and_management_factors: list[VehicleFactor]
    appraisal_factors: list[VehicleFactor]
    legal_basis: list[LegalCitation]
    alternative_hypotheses: list[VehicleNatureHypothesis] = Field(min_length=2)
    warning: str
    explanation: str = ""

    @model_validator(mode="after")
    def validate_high_risk_classification(self) -> "VehicleNatureResult":
        if (
            self.classification
            in {
                VehicleNatureClassification.MOTOR_VEHICLE,
                VehicleNatureClassification.NON_MOTOR_VEHICLE,
            }
            and not self.legal_basis
        ):
            raise ValueError(
                "A definite vehicle classification requires LegalCitation."
            )
        if len({item.hypothesis_id for item in self.alternative_hypotheses}) != len(
            self.alternative_hypotheses
        ):
            raise ValueError("Vehicle hypothesis IDs must be unique.")
        return self


class Party(str, Enum):
    MOTOR_VEHICLE = "motor_vehicle"
    TWO_WHEELER = "two_wheeler"
    UNKNOWN = "unknown"


class ViolationStatus(str, Enum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    REFUTED = "refuted"
    UNKNOWN = "unknown"


class ViolationFinding(StrictModel):
    behavior_id: str
    party: Party
    category: str
    behavior: str
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    law_citations: list[LegalCitation] = Field(default_factory=list)
    status: ViolationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str = ""

    @model_validator(mode="after")
    def confirmed_requires_fact_and_law(self) -> "ViolationFinding":
        if self.status is ViolationStatus.CONFIRMED and not (
            self.fact_ids and self.evidence_ids and self.law_citations
        ):
            raise ValueError(
                "A confirmed violation requires fact, evidence, and legal citations."
            )
        return self


class CausalRole(str, Enum):
    TRIGGERING = "triggering_cause"
    PRIMARY = "primary_cause"
    SECONDARY = "secondary_cause"
    CONDITIONAL = "conditional_factor"
    NO_CAUSAL_RELATION = "no_causal_relation"


class CausationFinding(StrictModel):
    behavior_id: str
    causal_role: CausalRole
    causal_strength: float = Field(ge=0.0, le=1.0)
    reasoning: str
    counterfactual_effect: str


class ResponsibilityLevel(str, Enum):
    FULL = "full"
    MAJOR = "major"
    EQUAL = "equal"
    MINOR = "minor"
    NONE = "none"


class LiabilityHypothesis(StrictModel):
    hypothesis_id: str
    label: str
    probability: float = Field(ge=0.0, le=1.0)
    party_responsibility: dict[Party, ResponsibilityLevel]
    supporting_findings: list[str]
    contradicting_findings: list[str]
    assumptions: list[str]
    missing_evidence: list[str]
    explanation: str = ""


class CompensationRegime(str, Enum):
    MOTOR_VS_MOTOR = "motor_vs_motor"
    MOTOR_VS_NON_MOTOR_OR_PEDESTRIAN = "motor_vs_non_motor_or_pedestrian"
    PENDING_VEHICLE_CLASSIFICATION = "pending_vehicle_classification"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AccidentResponsibility(StrictModel):
    status: str = Field(
        pattern=r"^(qualified_distribution|multiple_hypotheses_only|blocked)$"
    )
    selected_hypothesis_id: str | None = None
    levels_allowed: list[ResponsibilityLevel]
    explanation: str


class ShareRange(StrictModel):
    party: Party
    minimum: float = Field(ge=0.0, le=1.0)
    maximum: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def range_is_ordered(self) -> "ShareRange":
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self


class CivilCompensationAllocation(StrictModel):
    status: str = Field(pattern=r"^(range_only|insufficient_evidence)$")
    regime: CompensationRegime
    share_ranges: list[ShareRange]
    assumptions: list[str]
    legal_basis: list[LegalCitation]
    explanation: str


class InsurancePaymentEstimate(StrictModel):
    status: str = Field(pattern=r"^(available|insufficient_data)$")
    currency: str = "CNY"
    estimated_amount: float | None = Field(default=None, ge=0)
    required_inputs: list[str] = Field(default_factory=list)
    explanation: str

    @model_validator(mode="after")
    def amount_matches_status(self) -> "InsurancePaymentEstimate":
        if self.status == "insufficient_data" and self.estimated_amount is not None:
            raise ValueError("Insufficient-data estimates cannot contain an amount.")
        if self.status == "available" and self.estimated_amount is None:
            raise ValueError("Available estimates require an amount.")
        return self


class CounterfactualBranch(StrictModel):
    condition: str
    increases_hypotheses: list[str]
    decreases_hypotheses: list[str]
    explanation: str


class CounterfactualFinding(StrictModel):
    evidence_type: str
    current_status: str
    branches: list[CounterfactualBranch] = Field(min_length=2)
    collection_action: str


class UncertaintyAssessment(StrictModel):
    unique_conclusion_blocked: bool
    critical_missing_evidence: list[str]
    disputed_fact_ids: list[str]
    confidence_note: str


class LiabilityResult(StrictModel):
    violation_matrix: list[ViolationFinding]
    causation_matrix: list[CausationFinding]
    liability_hypotheses: list[LiabilityHypothesis] = Field(min_length=2)
    responsibility_probabilities: dict[str, float]
    accident_responsibility: AccidentResponsibility
    civil_compensation_allocation: CivilCompensationAllocation
    insurance_payment_estimate: InsurancePaymentEstimate
    compensation_regime: CompensationRegime
    key_evidence: list[EvidenceReference]
    missing_evidence: list[EvidenceGap]
    counterfactual_analysis: list[CounterfactualFinding]
    uncertainty: UncertaintyAssessment
    legal_basis: list[LegalCitation]
    explanation: str = ""
    scoring_trace: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_probability_distribution(self) -> "LiabilityResult":
        total = sum(self.responsibility_probabilities.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"Responsibility probabilities must sum to 1, got {total}."
            )
        hypothesis_total = sum(item.probability for item in self.liability_hypotheses)
        if abs(hypothesis_total - 1.0) > 1e-6:
            raise ValueError(
                f"Liability hypothesis probabilities must sum to 1, got {hypothesis_total}."
            )
        if set(self.responsibility_probabilities) != {
            item.label for item in self.liability_hypotheses
        }:
            raise ValueError(
                "Probability keys must exactly match liability hypothesis labels."
            )
        return self
