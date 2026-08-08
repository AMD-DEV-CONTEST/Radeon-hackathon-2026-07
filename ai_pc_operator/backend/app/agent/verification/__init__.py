"""Verification Engine — verifies the results of executed actions.

Provides 7 specialized verifiers:
  - StateVerifier: system state (process, window, service, awake, network)
  - UIVerifier: UI elements (exists, text, enabled, visible, screenshot hash)
  - DOMVerifier: web page DOM state (selectors, text, attributes, login state)
  - OCRVerifier: text via OCR (visible, coordinates, count, similarity)
  - FileVerifier: file system state (exists, size, hash, content, modified)
  - APIVerifier: HTTP API responses (status, body, latency, headers)
  - ProcessVerifier: process execution (exit code, stdout, duration, running)

Plus:
  - VerificationEngine: orchestrator that runs checks across all domains
  - VerificationReport: aggregated report dataclass
"""

from .state_verification import StateVerifier, StateCheck
from .ui_verification import UIVerifier, UICheck
from .dom_verification import DOMVerifier, DOMCheck
from .ocr_verification import OCRVerifier, OCRCheck
from .file_verification import FileVerifier, FileCheck
from .api_verification import APIVerifier, APICheck
from .process_verification import ProcessVerifier, ProcessCheck
from .engine import VerificationEngine, VerificationReport

__all__ = [
    # Verifiers
    "StateVerifier",
    "UIVerifier",
    "DOMVerifier",
    "OCRVerifier",
    "FileVerifier",
    "APIVerifier",
    "ProcessVerifier",
    # Check result dataclasses
    "StateCheck",
    "UICheck",
    "DOMCheck",
    "OCRCheck",
    "FileCheck",
    "APICheck",
    "ProcessCheck",
    # Orchestrator
    "VerificationEngine",
    "VerificationReport",
]
