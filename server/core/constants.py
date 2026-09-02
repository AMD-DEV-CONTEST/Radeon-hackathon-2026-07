"""Application-wide constants (non-secret, non-env values)."""

API_V1_PREFIX = "/api/v1"

HEALTH_PATH = "/health"

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

UPLOAD_MAX_SIZE_MB = 10
ALLOWED_RESUME_EXTENSIONS = (".pdf", ".doc", ".docx", ".txt")

TOKEN_TYPE_BEARER = "bearer"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72
