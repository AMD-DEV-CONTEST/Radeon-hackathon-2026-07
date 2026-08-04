from enum import StrEnum


class ActorRole(StrEnum):
    REQUESTER = "requester"
    POLICY_REVIEWER = "policy_reviewer"


class FileKind(StrEnum):
    XLSX = "xlsx"
    DOCX = "docx"
    PDF = "pdf"


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    STRICTLY_CONFIDENTIAL = "strictly_confidential"

    @property
    def rank(self) -> int:
        return list(type(self)).index(self)


class RecipientProfile(StrEnum):
    INTERNAL_PROCUREMENT_LEAD = "internal_procurement_lead"
    EXTERNAL_FINANCIAL_AUDITOR = "external_financial_auditor"
    SUPPLIER_BIDDER_A = "supplier_bidder_a"
    EXTERNAL_INCIDENT_RESPONDER = "external_incident_responder"
    CANDIDATE_SUPPLIER = "candidate_supplier"
    AFFECTED_CUSTOMER = "affected_customer"
    REGULATOR = "regulator"
    PUBLIC_AUDIENCE = "public_audience"


class Purpose(StrEnum):
    PROCUREMENT_DECISION = "procurement_decision"
    ANNUAL_FINANCIAL_AUDIT = "annual_financial_audit"
    SECURITY_CONTROL_AUDIT = "security_control_audit"
    SUPPLIER_BID_FEEDBACK = "supplier_bid_feedback"
    INCIDENT_RESPONSE_INVESTIGATION = "incident_response_investigation"
    CUSTOMER_INCIDENT_NOTIFICATION = "customer_incident_notification"
    REGULATORY_INCIDENT_REPORT = "regulatory_incident_report"
    CONTRACT_TERMS_PREVIEW = "contract_terms_preview"
    LEGAL_REVIEW = "legal_review"


class Channel(StrEnum):
    CORPORATE_EMAIL = "corporate_email"
    SECURE_FILE_EXCHANGE = "secure_file_exchange"
    COLLABORATION_PLATFORM = "collaboration_platform"
    PERSONAL_EMAIL = "personal_email"
    PUBLIC_RELEASE = "public_release"


class OwnerRelation(StrEnum):
    RECIPIENT = "recipient"
    OTHER = "other"
    NONE = "none"
    UNKNOWN = "unknown"


class ContentCategory(StrEnum):
    UNCLASSIFIED = "unclassified"
    GENERAL_BUSINESS = "general_business"
    SUPPLIER_IDENTITY = "supplier_identity"
    CONTACT_PERSONAL = "contact_personal"
    BANK_PAYMENT = "bank_payment"
    QUOTE_COMMERCIAL_TERMS = "quote_commercial_terms"
    INTERNAL_COST_BUDGET = "internal_cost_budget"
    SCORE_RANKING = "score_ranking"
    INTERNAL_OPINION_APPROVAL = "internal_opinion_approval"
    INCIDENT_FACT_TIMELINE = "incident_fact_timeline"
    EXTERNAL_THREAT_INDICATOR = "external_threat_indicator"
    INTERNAL_INFRASTRUCTURE = "internal_infrastructure"
    NETWORK_LOG = "network_log"
    CREDENTIAL_SECRET = "credential_secret"
    VULNERABILITY_FACT = "vulnerability_fact"
    EXPLOIT_PAYLOAD = "exploit_payload"
    PERSON_IDENTITY = "person_identity"
    INTERNAL_ACCOUNT = "internal_account"
    ORGANIZATIONAL_ROLE = "organizational_role"
    CONTACT_DETAIL = "contact_detail"
    INTERNAL_ATTRIBUTION = "internal_attribution"
    REMEDIATION = "remediation"
    REMEDIATION_OWNER = "remediation_owner"
    REMEDIATION_BUDGET_COMMENT = "remediation_budget_comment"
    CONTRACT_BUYER = "contract_buyer"
    CONTRACT_SUPPLIER = "contract_supplier"
    CORPORATE_IDENTIFIER = "corporate_identifier"
    CONTRACT_DATE_IDENTIFIER = "contract_date_identifier"
    RELATIVE_PERFORMANCE_TERM = "relative_performance_term"
    HISTORICAL_PRICING = "historical_pricing"
    STANDARD_LEGAL_TERM = "standard_legal_term"
    NONSTANDARD_OBLIGATION = "nonstandard_obligation"
    SIGNATURE = "signature"
    SOURCE_METADATA = "source_metadata"


class Action(StrEnum):
    KEEP = "keep"
    MASK = "mask"
    REMOVE = "remove"
    FILTER = "filter"
    GENERALIZE = "generalize"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class RevisionStatus(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXPORTABLE = "exportable"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    PROCESSING_FAILED = "processing_failed"


class DecisionOrigin(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model_assisted"
    HUMAN_CONFIRMED = "human_confirmed"
    FAIL_CLOSED = "fail_closed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
