#!/bin/bash

# Configuration for AMD MI300X qualification run
export QUAL_BASE_URL="http://127.0.0.1:8000"
export QUAL_API_KEY=""
export QUAL_MODEL="llama-3.3-nemotron-super-49b-v1"
export QUAL_PROVIDER="AMD"
export QUAL_RUNTIME="rocm"
export QUAL_HARDWARE="local_mi300x"

# Run the qualification suite against the new AMD card
cargo run --example run_qualification --manifest-path core/forge-qualification-lab/Cargo.toml -- "${QUAL_BASE_URL}" "${QUAL_MODEL}" "${QUAL_RUNTIME}" "fp16" "${QUAL_HARDWARE}"
