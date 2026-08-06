"""config.py - Endpoint configuration & global prompts
Centralized configuration for EduCopilot system.
"""

import os

# --- OpenAI-compatible LLM Endpoint Configuration ---
# The Ollama names remain supported so existing local setups keep working.
OPENAI_BASE_URL: str = os.getenv(
    "OPENAI_BASE_URL",
    os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
)
OPENAI_API_KEY: str = os.getenv(
    "OPENAI_API_KEY",
    os.getenv("OLLAMA_API_KEY", "ollama"),
)
MODEL_NAME: str = os.getenv(
    "OPENAI_MODEL",
    os.getenv("MODEL_NAME", "gemma4"),
)

# --- Database Configuration ---
SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", "educopilot.db")
CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")

# --- Thresholds & Business Rules ---
COHORT_THRESHOLDS = {
    "remedial_max": 50.0,      # Below 50% → Remedial
    "average_min": 50.0,       # 50% - 75% → Average
    "average_max": 75.0,       # Above 75% → Advanced
    "advanced_min": 75.0,
}

NBA_ATTAINMENT_BENCHMARK: float = 60.0  # Target CO attainment %

# Bloom's Taxonomy reference for validation
BLOOMS_LEVELS: list[str] = [
    "Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"
]

# Valid action verbs per Bloom's level (used for CO auditing)
BLOOMS_VERBS: dict[str, list[str]] = {
    "Remember": ["define", "list", "recall", "identify", "describe", "recognize", "state"],
    "Understand": ["explain", "summarize", "interpret", "classify", "compare", "discuss"],
    "Apply": ["demonstrate", "calculate", "use", "implement", "solve", "apply"],
    "Analyze": ["analyze", "differentiate", "examine", "compare", "contrast", "investigate"],
    "Evaluate": ["evaluate", "justify", "assess", "critique", "judge", "defend"],
    "Create": ["design", "construct", "develop", "formulate", "create", "propose"],
}

# --- System Prompts ---
SYSTEM_PROMPT_OBE_AUDITOR: str = (
    "You are an expert Outcomes-Based Education (OBE) academic auditor. "
    "You extract structured data from syllabi, validate Course Outcomes against Bloom's Taxonomy, "
    "and generate lesson plans aligned with accreditation standards."
)

SYSTEM_PROMPT_EXAM_CONTROLLER: str = (
    "You are an expert university exam controller specializing in Outcome-Based Education. "
    "You generate question papers with rubrics and answer keys aligned to specific cognitive levels."
)

SYSTEM_PROMPT_CONTENT_CREATOR: str = (
    "You are an expert academic content creator and instructional designer. "
    "You create clear, engaging, and pedagogically sound educational materials including "
    "lecture slides (in markdown), handouts, and teacher notes. "
    "You tailor content to the student level and incorporate feedback from previous classes."
)

SYSTEM_PROMPT_EVALUATOR: str = (
    "You are an expert academic evaluator. You analyze student assignments and quizzes, "
    "evaluate answers against marking rubrics, and provide fair, constructive feedback. "
    "You assign marks proportional to the quality and completeness of answers."
)

SYSTEM_PROMPT_STUDENT_ADVISOR: str = (
    "You are an expert student performance advisor. You analyze assessment data, "
    "identify at-risk students, recognize strengths and weaknesses, "
    "and recommend actionable interventions for both individual students and the class as a whole."
)

SERVER_PORT: int = int(os.getenv("PORT", "7860"))
GRADIO_SERVER_PORT: int = SERVER_PORT
