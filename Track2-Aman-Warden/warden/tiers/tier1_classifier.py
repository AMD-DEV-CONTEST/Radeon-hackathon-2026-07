"""
Tier 1: Prompt Guard 2 classifier (~20ms on CPU).

Uses HuggingFace transformers to load Prompt Guard 2 (86M params).
Falls back gracefully if the model isn't downloaded yet.

Note: pytector was considered but is not widely available.
Loading directly via transformers is the primary path.
"""

from __future__ import annotations

import time
import logging
from typing import Optional

from warden.config import Decision, ModelConfig
from warden.tiers.base import CheckResult, TierChecker
from warden.routing.confidence import ConfidenceCalibrator

logger = logging.getLogger(__name__)


class Tier1Classifier(TierChecker):
    """
    Tier 1 — DeBERTa-v3 classifier for injection detection.

    Runs on CPU by default (~86M params, ~210ms), or GPU (ROCm/CUDA via
    PyTorch HIP backend, ~18-35ms) when classifier_device='auto' detects
    a compatible GPU at load time. Returns calibrated probability of injection.
    Fast enough to run on every untrusted input before deciding whether to
    escalate to Tier 2.
    """

    def __init__(self, model_config: Optional[ModelConfig] = None):
        self._config = model_config or ModelConfig()
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._device = "cpu"  # resolved at load() time (OPT-4 auto-detect)
        self._calibrator = ConfidenceCalibrator()

    def load(self) -> bool:
        """Load the Prompt Guard 2 model. Call once at startup."""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch

            model_name = self._config.classifier_model_name
            import os
            for lp in ["/root/models/deberta", "/workspace/models/deberta", "models/deberta"]:
                if os.path.exists(lp):
                    model_name = lp
                    break

            logger.info(f"Loading Tier 1 classifier: {model_name}")

            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            if not self._tokenizer.pad_token:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self._model.eval()

            # OPT-4: Auto-device resolution.
            # "auto" → prefer GPU (ROCm/CUDA via torch HIP backend) for ~6-12x
            # faster DeBERTa inference (~210ms CPU → ~18-35ms on AMD W7900).
            # Gracefully falls back to CPU if GPU load raises any exception.
            device = getattr(self._config, "classifier_device", "auto")
            if device == "auto":
                if torch.cuda.is_available():
                    device = "cuda"
                    logger.info("[OPT-4] ROCm/CUDA GPU detected — loading Tier 1 classifier onto GPU")
                else:
                    device = "cpu"
                    logger.info("[OPT-4] No GPU detected — Tier 1 classifier running on CPU")

            try:
                self._model.to(device)
                self._device = device
            except Exception as gpu_err:
                logger.warning(f"[OPT-4] Failed to move Tier 1 model to {device!r}: {gpu_err} — falling back to CPU")
                self._model.to("cpu")
                self._device = "cpu"

            self._loaded = True
            logger.info(f"Tier 1 classifier loaded on {self._device}")
            return True

        except Exception as e:
            logger.warning(f"Failed to load Tier 1 classifier: {e}")
            self._loaded = False
            return False

    @property
    def tier_number(self) -> int:
        return 1

    def check(self, text: str, context: str = "") -> CheckResult:
        """Classify input text for injection probability."""
        if not self._loaded:
            return CheckResult(
                decision=Decision.UNCERTAIN,
                confidence=0.5,
                tier=1,
                explanation="Tier 1 model not loaded — escalating to next tier",
            )

        start = time.perf_counter()

        try:
            import torch

            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits

            # Softmax to get probabilities
            probs = torch.softmax(logits, dim=-1)

            # Map to probability
            if hasattr(self._model.config, "id2label") and self._model.config.id2label:
                id2label = self._model.config.id2label
                # Find the index for injection
                injection_idx = 1
                for idx, label in id2label.items():
                    if "injection" in label.lower():
                        injection_idx = int(idx)
                        break
                injection_prob = probs[0, injection_idx].item()
            else:
                # Fallback to simple binary assumption
                injection_prob = probs[0, 1].item() if probs.shape[-1] > 1 else probs[0, 0].item()

            # Calibrate confidence using Platt scaling
            injection_prob = self._calibrator.calibrate_tier1(injection_prob)

            latency = (time.perf_counter() - start) * 1000

            # Map probability to decision
            decision = self._prob_to_decision(injection_prob)

            return CheckResult(
                decision=decision,
                confidence=injection_prob,
                tier=1,
                latency_ms=latency,
                explanation=f"Tier 1 injection probability: {injection_prob:.3f}",
                raw_output={"logits": logits.tolist(), "probs": probs.tolist()},
            )

        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(f"Tier 1 check failed: {e}")
            return CheckResult(
                decision=Decision.UNCERTAIN,
                confidence=0.5,
                tier=1,
                latency_ms=latency,
                explanation=f"Tier 1 error: {str(e)} — escalating",
            )

    def _prob_to_decision(self, prob: float) -> Decision:
        """Map injection probability to a routing decision."""
        if prob >= self._config.classifier_threshold_block:
            return Decision.BLOCK
        elif prob <= getattr(self._config, "classifier_threshold_allow", 0.05):
            return Decision.ALLOW
        else:
            return Decision.UNCERTAIN  # Needs Tier 2

    def is_available(self) -> bool:
        return self._loaded
