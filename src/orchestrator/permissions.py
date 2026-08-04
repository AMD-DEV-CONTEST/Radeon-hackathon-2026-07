"""Role-based access control / privacy protection.

Minimal placeholder — extend with your actual role model. Track 2 rubric
counts this as one of the 5 core capabilities if implemented meaningfully
(not just a stub).
"""

ROLE_FIELD_REDACTIONS = {
    "analyst": [],                 # sees everything relevant to triage
    "trainee": ["src_ip", "user"],  # example: redact identifying fields
}


class PermissionManager:
    def redact(self, data: dict, role: str) -> dict:
        redacted = dict(data)
        for field in ROLE_FIELD_REDACTIONS.get(role, []):
            if field in redacted:
                redacted[field] = "[redacted]"
        return redacted
