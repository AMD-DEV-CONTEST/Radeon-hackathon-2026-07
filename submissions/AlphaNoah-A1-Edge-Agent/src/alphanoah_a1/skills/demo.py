"""Synthetic declarative Skills for the bounded demonstration."""

from ..skill import SkillDefinition, SkillStatus

RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL = SkillDefinition(
    skill_id="restaurant-aircon-troubleshooting",
    version="1.0-demo",
    status=SkillStatus.ACTIVE,
    supported_event_types=("equipment_fault_report",),
    supported_asset_types=("air_conditioner",),
    analysis_instructions=(
        "Analyze the synthetic air-conditioner fault report. Consider "
        "cooling or temperature abnormalities, noise or vibration, water "
        "leakage or condensation, airflow or fan problems, odor or smoke, "
        "and power or start-stop abnormalities. Recommend only safe triage "
        "and escalation for authorized human review. Never claim a confirmed "
        "diagnosis or direct an unqualified person to repair, open, energize, "
        "isolate, or control equipment."
    ),
    escalation_rules=(
        "Escalate unresolved or safety-relevant faults to authorized maintenance.",
        "Require human review before inspection, repair, or electrical action.",
    ),
    knowledge_query_hints=(
        "air conditioner troubleshooting",
        "safe fault triage",
        "maintenance escalation",
        "cooling noise leak airflow odor power",
    ),
)

INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL = SkillDefinition(
    skill_id="industrial-equipment-shutdown",
    version="1.0-demo",
    status=SkillStatus.ACTIVE,
    supported_event_types=("device_not_shutdown",),
    supported_asset_types=("industrial_machine",),
    analysis_instructions=(
        "Analyze the synthetic industrial-machine shutdown report. "
        "Prioritize personnel safety, equipment wear, residual energy, "
        "the approved shutdown SOP, lockout/tagout guidance when applicable, "
        "and escalation to authorized maintenance. Never direct an "
        "unauthorized person to operate or isolate equipment."
    ),
    escalation_rules=(
        "Escalate uncertain equipment state to authorized maintenance.",
        "Require human confirmation before shutdown or isolation activity.",
    ),
    knowledge_query_hints=(
        "equipment shutdown",
        "lockout tagout",
        "maintenance escalation",
        "safety inspection",
    ),
)

DEMO_SKILL_DEFINITIONS = (
    INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL,
    RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL,
)

__all__ = [
    "DEMO_SKILL_DEFINITIONS",
    "INDUSTRIAL_EQUIPMENT_SHUTDOWN_SKILL",
    "RESTAURANT_AIRCON_TROUBLESHOOTING_SKILL",
]
