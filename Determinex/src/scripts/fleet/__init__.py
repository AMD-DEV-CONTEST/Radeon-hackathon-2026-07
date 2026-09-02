"""
Determinex Fleet Learning -- opt-in, consent-first, oracle-verified corpus contribution.
=====================================================================================
v1 trust model (shipped): contributed (error -> fix) work is **Cloak-obfuscated**
(every real identifier replaced by an opaque token) AND **sealed** to the node's
public key (X25519 + ChaCha20Poly1305), so it is encrypted in transit and at rest
and only the node operator can open it. The contributor sees the exact payload before
it sends (consent gate). Nothing leaves a machine without an explicit opt-in.

v2 roadmap (documented, not yet built): never-sees-plaintext federation -- clients
train local LoRA deltas and upload only adapter deltas / DP-noised signals.

The keystone (`ingest_verify`): every contributed pair is **re-verified against the
compiler/test oracle on the node before it enters the corpus**. Contributed data is
never trusted; it is re-proven by the same deterministic gate that built the corpus.
This makes the fleet poisoning-resistant -- a bad contribution cannot compile/pass,
so it is dropped, never trained on.

See docs/fleet/ for the protocol spec, contributor terms, privacy policy, and the
HF + Cloudflare hosting setup checklist.
"""

from __future__ import annotations

PROTOCOL_VERSION = 1
SEAL_ALG = "x25519-hkdf-sha256-chacha20poly1305"

__all__ = ["PROTOCOL_VERSION", "SEAL_ALG"]
