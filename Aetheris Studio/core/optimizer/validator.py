"""
Byte-Identical Correctness & Entropy Validation Suite.
Validates a kernel candidate against the official kernel by generating from two isolated vte-server instances (one per template variant, both running the same fixed reference model) and comparing output byte-for-byte at temperature=0.
"""

import math
from typing import Dict, Tuple

from core.optimizer.isolated_runner import REFERENCE_MODEL, IsolatedInstancePair, generate_at


class CandidateValidator:
    @staticmethod
    def calculate_entropy(text: str) -> float:
        if not text:
            return 0.0
        frequencies: Dict[str, int] = {}
        for char in text:
            frequencies[char] = frequencies.get(char, 0) + 1
        entropy = 0.0
        length = len(text)
        for count in frequencies.values():
            p = count / length
            entropy -= p * math.log2(p)
        return entropy

    def validate_urls(
        self, official_base_url: str, candidate_base_url: str, reference_model: str = REFERENCE_MODEL
    ) -> Tuple[bool, str]:
        """Compares two already-running isolated vte-server instances --
        one serving the official kernel template, one serving the
        candidate -- both loaded with the same reference_model. This is
        the only way a kernel-level change can actually be validated:
        comparing two different MODEL names (the previous version of this
        method) can never test a template edit, since neither model's
        weights or templates would differ because of it."""
        messages = [
            {"role": "system", "content": "You are a precise software validator."},
            {"role": "user", "content": "Write a 60 token technical description of GPU execution loops."}
        ]

        try:
            resp_ref = generate_at(official_base_url, reference_model, messages, temperature=0.0, max_tokens=60)
            resp_cand = generate_at(candidate_base_url, reference_model, messages, temperature=0.0, max_tokens=60)
        except Exception as e:
            return False, f"EXECUTION_ERROR: {e}"

        output_ref = resp_ref["choices"][0]["message"]["content"]
        output_cand = resp_cand["choices"][0]["message"]["content"]

        if self.calculate_entropy(output_cand) < 2.0:
            return False, "LOW_ENTROPY_REPETITIVE_OUTPUT"

        if output_ref.strip() != output_cand.strip():
            return False, f"BYTE_DIVERGENCE: ref_len={len(output_ref)}, cand_len={len(output_cand)}"

        return True, "BYTE_IDENTICAL_VERIFIED"

    def validate_pair(self, pair: IsolatedInstancePair, reference_model: str = REFERENCE_MODEL) -> Tuple[bool, str]:
        """Convenience wrapper for the common case: an already-entered
        IsolatedInstancePair for the kernel/candidate under test."""
        return self.validate_urls(pair.official_base_url, pair.candidate_base_url, reference_model)
