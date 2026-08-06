"""Frozen domain enum values from the approved L3 contract."""

from enum import StrEnum


class AssetLifecycle(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ROUTE_REVIEW = "ROUTE_REVIEW"
    EXPORT_READY = "EXPORT_READY"
    DELETION_PENDING = "DELETION_PENDING"
    DELETED = "DELETED"


class Milestone(StrEnum):
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"
    M5 = "M5"


class MilestoneState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_INPUT = "NEEDS_INPUT"
    REVIEW_READY = "REVIEW_READY"
    CONFIRMED = "CONFIRMED"
    COMPLETE_WITH_GAPS = "COMPLETE_WITH_GAPS"
    INVALIDATED = "INVALIDATED"
    FAILED = "FAILED"


class StatementStatus(StrEnum):
    SOURCE_FACT = "SOURCE_FACT"
    USER_JUDGMENT = "USER_JUDGMENT"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    UNRESOLVED = "UNRESOLVED"


class ConfirmationState(StrEnum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class EvidenceStrength(StrEnum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    SELF_REPORTED = "SELF_REPORTED"
    NONE = "NONE"


class SourceKind(StrEnum):
    CONVERSATION = "CONVERSATION"
    PASTED_TEXT = "PASTED_TEXT"
    TXT_FILE = "TXT_FILE"
    MD_FILE = "MD_FILE"
    ADAPTED_PUBLIC_FIXTURE = "ADAPTED_PUBLIC_FIXTURE"


class SourceAuthorship(StrEnum):
    USER_AUTHORED = "USER_AUTHORED"
    THIRD_PARTY = "THIRD_PARTY"
    ADAPTED_RESEARCH = "ADAPTED_RESEARCH"


class QuestionState(StrEnum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    SKIPPED = "SKIPPED"
    DEFERRED = "DEFERRED"


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_GAPS = "ACCEPTED_WITH_GAPS"
    REJECTED = "REJECTED"


class RouteType(StrEnum):
    PRIVATE_SELF = "PRIVATE_SELF"
    BEGINNER = "BEGINNER"
    PEER = "PEER"
    CUSTOMER_EVALUATOR = "CUSTOMER_EVALUATOR"
    PUBLIC = "PUBLIC"


class RouteEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE_AFTER_PRIVACY_APPROVAL = "ELIGIBLE_AFTER_PRIVACY_APPROVAL"
    BLOCKED = "BLOCKED"


class PrivacyResolution(StrEnum):
    OPEN = "OPEN"
    KEEP = "KEEP"
    GENERALIZE = "GENERALIZE"
    REMOVE = "REMOVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class FindingSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalScope(StrEnum):
    SHAREABLE_EXPORT = "SHAREABLE_EXPORT"


class ExportFormat(StrEnum):
    HTML = "HTML"
    MARKDOWN = "MARKDOWN"
    JSON = "JSON"


class ExportState(StrEnum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class TerminalState(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_OOM = "MODEL_OOM"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"
    STORAGE_ERROR = "STORAGE_ERROR"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    DELETION_FAILED = "DELETION_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProgressState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    TERMINAL = "TERMINAL"


class PlanStepKind(StrEnum):
    RETRIEVE = "RETRIEVE"
    ASK = "ASK"
    EXTRACT = "EXTRACT"
    CLASSIFY = "CLASSIFY"
    UPDATE_ARTIFACT = "UPDATE_ARTIFACT"
    VERIFY = "VERIFY"
    EVALUATE_ROUTE = "EVALUATE_ROUTE"
    PRIVACY_REVIEW = "PRIVACY_REVIEW"
    RENDER = "RENDER"


class PlanStepStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    DENIED = "DENIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RetrievalScope(StrEnum):
    CURRENT_SOURCE = "CURRENT_SOURCE"
    CROSS_ASSET_SUMMARY = "CROSS_ASSET_SUMMARY"
    CROSS_ASSET_DETAIL = "CROSS_ASSET_DETAIL"


class RelationType(StrEnum):
    """Closed vocabulary for cross-asset relations.

    The vocabulary is closed so a relation label means the same thing in a
    session weeks later. A model-invented synonym would read as a distinct
    relation to the user while carrying no admissibility rule behind it, so
    abstention preserves meaning better than an unmapped label.
    """

    SAME_THEME = "SAME_THEME"
    METHOD_REUSE = "METHOD_REUSE"
    COUNTEREXAMPLE = "COUNTEREXAMPLE"
    SUPPLEMENT = "SUPPLEMENT"
    PREREQUISITE = "PREREQUISITE"
    FOLLOW_UP = "FOLLOW_UP"


class DiscoveryOutcome(StrEnum):
    """Discriminated outcomes of one cross-asset discovery request.

    `NO_MATCH` is a semantic claim and is cached; `TECHNICAL_FAILURE` is not.
    Collapsing the two would make a temporary outage indistinguishable from a
    proven absence of relation, and the cache would then preserve the outage
    permanently.
    """

    NOT_READY = "NOT_READY"
    RUNNING = "RUNNING"
    CANDIDATE = "CANDIDATE"
    NO_MATCH = "NO_MATCH"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    STALE = "STALE"


class ProjectionRootKind(StrEnum):
    """Canonical record kinds a role graph may be projected from."""

    CRITICAL_MOMENT = "CRITICAL_MOMENT"
    DECISION_RECORD = "DECISION_RECORD"
    INSIGHT_RECORD = "INSIGHT_RECORD"


class ProjectionEdgeType(StrEnum):
    """Membership edges only.

    Every edge means "this canonical record has this member in this role".
    Statement order, temporal proximity and semantic similarity cannot prove
    causation, so no edge asserts it; a causal label would present the system's
    guess with the same authority as the user's own confirmed account.
    """

    HAS_CUE = "HAS_CUE"
    HAS_CHANGE = "HAS_CHANGE"
    HAS_SURPRISE = "HAS_SURPRISE"
    HAS_CONFLICT = "HAS_CONFLICT"
    HAS_ALTERNATIVE = "HAS_ALTERNATIVE"
    HAS_REASON = "HAS_REASON"
    HAS_ACTION = "HAS_ACTION"
    HAS_RESULT = "HAS_RESULT"
    HAS_EVIDENCE = "HAS_EVIDENCE"
    HAS_SUPPORT = "HAS_SUPPORT"
    HAS_COUNTERFACTUAL = "HAS_COUNTERFACTUAL"
    HAS_LIMITATION = "HAS_LIMITATION"
    HAS_COUNTEREXAMPLE = "HAS_COUNTEREXAMPLE"
    HAS_APPLICABILITY = "HAS_APPLICABILITY"


class ProjectionLifecycle(StrEnum):
    """Projection eligibility state.

    `BUILDING` exists so a partially written projection is never eligible for
    comparison: a projection compared before its provenance rows are complete
    would yield a candidate that cannot be explained.
    """

    BUILDING = "BUILDING"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


class ReadinessLifecycle(StrEnum):
    """Lifecycle of a readiness record.

    Deliberately not `ProjectionLifecycle`: a projection is built incrementally
    and only becomes eligible when complete, but readiness is minted whole by
    one explicit user action. Reusing the projection enum let a readiness record
    claim `CONFIRMED` while sitting in `BUILDING`, which two consumers could
    reasonably read as opposite answers to "is this card ready".
    """

    ACTIVE = "ACTIVE"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


class RelationLifecycle(StrEnum):
    """Lifecycle of a validated candidate or a confirmed relation.

    Records are append-only; invalidation moves state here rather than deleting
    the row, because deleting it would make an invalidated relation
    indistinguishable from one that never existed.
    """

    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


class DiscoveryFailureClass(StrEnum):
    """Safe failure classes retained for audit.

    None of these is reusable as a semantic result. Reusing one would let a
    five-minute outage permanently erase a relation that may well exist.
    """

    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_TIMED_OUT = "MODEL_TIMED_OUT"
    MALFORMED_MODEL_OUTPUT = "MALFORMED_MODEL_OUTPUT"
    RUNTIME_VALIDATION_REJECTED = "RUNTIME_VALIDATION_REJECTED"
    STORAGE_CONFLICT = "STORAGE_CONFLICT"
    STALE_BINDING = "STALE_BINDING"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    """A reservation whose holder never reported an outcome.

    Distinct from `MODEL_TIMED_OUT`, which is a model that was asked and did not
    answer in time. Here nothing is known about the call: the process holding
    the lease disappeared, so it may never have been made, may have succeeded
    without recording it, or may still be running. Recording it as a model
    timeout attributes a killed worker to the inference server, and the two need
    different investigation — one is a capacity question, the other a
    process-lifecycle one.
    """


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    DENIED = "DENIED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class VerificationOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_INPUT = "NEEDS_INPUT"
    REPLAN = "REPLAN"
    REJECTED = "REJECTED"


class EvidenceCardRefusalReason(StrEnum):
    """Why a confirmed relation produced no evidence card.

    Each value is a whole-card refusal rather than a gap inside a rendered one.
    A card missing half its provenance still looks authoritative, and the user
    has no way to see what was dropped — so the failure has to be the answer,
    not a hole in one.
    """

    RELATION_NOT_LIVE = "RELATION_NOT_LIVE"
    BINDING_MISMATCH = "BINDING_MISMATCH"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    PARTIAL_PROVENANCE = "PARTIAL_PROVENANCE"
    MISSING_REFERENCES = "MISSING_REFERENCES"
