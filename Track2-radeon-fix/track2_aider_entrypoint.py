#!/usr/bin/env python3
"""Run Aider with provider retries disabled for a fair fixed-call benchmark."""

from __future__ import annotations

import sys

import litellm
from aider import models, sendchat
from aider.coders import base_coder
from aider.main import main


# mini-SWE's OpenAI client uses max_retries=0.  Match that policy so one
# semantic Aider attempt cannot silently turn into many provider requests.
litellm.num_retries = 0
models.RETRY_TIMEOUT = 0
sendchat.RETRY_TIMEOUT = 0
base_coder.RETRY_TIMEOUT = 0


if __name__ == "__main__":
    result = main()
    raise SystemExit(result if isinstance(result, int) else 0)
