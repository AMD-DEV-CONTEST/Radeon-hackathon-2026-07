"""Quality Oracle — deterministic feedback loop for non-code benchmarks.

Converts preference/quality scores into grounded per-failure retry prompts
using the same architecture as the compiler oracle for code tasks.

Core flow:
  response → ClaimExtractor → RagVerifier → FeatureChecks → OracleResult
  OracleResult.feedback_block() → retry prompt (drop-in for EvalResult.feedback_block)
"""

from .claim_extractor import Claim, ClaimExtractor
from .feature_checks import FeatureChecker, FeatureResult
from .feedback_builder import build_feedback_block
from .oracle import OracleResult, QualityOracle
from .rag_verifier import ClaimVerification, RagVerifier
from .rubric_decomposer import RubricDecomposer

__all__ = [
    "QualityOracle",
    "OracleResult",
    "ClaimExtractor",
    "Claim",
    "RagVerifier",
    "ClaimVerification",
    "FeatureChecker",
    "FeatureResult",
    "RubricDecomposer",
    "build_feedback_block",
]
