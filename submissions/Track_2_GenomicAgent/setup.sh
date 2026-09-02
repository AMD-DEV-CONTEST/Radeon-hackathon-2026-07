#!/bin/bash
# Setup script for Genomic Research Agent
# Runs on both local machine and Radeon Cloud instance

set -e

echo "╔════════════════════════════════════════════════════════════╗"
echo "║   Genomic Research Agent - Setup Script                   ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Detect platform
OS=$(uname -s)
if [[ "$OS" == "Linux" ]]; then
    echo "✓ Detected Linux system"
elif [[ "$OS" == "Darwin" ]]; then
    echo "✓ Detected macOS system"
elif [[ "$OS" == "MINGW64_NT"* ]]; then
    echo "✓ Detected Windows (Git Bash) system"
else
    echo "⚠ Unknown OS: $OS (may not work)"
fi

# Check Rust installation
if ! command -v rustc &> /dev/null; then
    echo ""
    echo "❌ Rust is not installed. Install from: https://rustup.rs/"
    exit 1
fi
echo "✓ Rust $(rustc --version)"

# Check Cargo
echo "✓ Cargo $(cargo --version)"

# GPU acceleration in this project uses wgpu/Vulkan, not ROCm/HIP --
# see README_PROFESSIONAL.md section 5 for exactly why. ROCm presence
# is irrelevant to whether the GPU code path works; this is just an
# informational check, not a requirement either way.
if command -v rocm-smi &> /dev/null; then
    echo "✓ ROCm also detected (not required or used by this build):"
    rocm-smi --version
else
    echo "i ROCm not found -- not needed; GPU acceleration here uses wgpu/Vulkan"
fi

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Building project..."
echo "────────────────────────────────────────────────────────────"
echo ""

# Build release binary
cargo build --release

echo ""
echo "✓ Build complete!"
echo ""
echo "────────────────────────────────────────────────────────────"
echo "Setup complete! Ready to run."
echo "────────────────────────────────────────────────────────────"
echo ""
echo "Quick start commands:"
echo "  1. Run demo (synthetic data):        cargo run --release"
echo "  2. Run demo (real 1000 Genomes data): GENOMIC_AGENT_REAL_DATA=1 cargo run --release"
echo "  3. Run benchmarks:                    cargo run --release -- bench"
echo "  4. Run GPU benchmark + cross-check:   cargo run --release -- gpu-bench"
echo ""
echo "This build has real GPU acceleration (wgpu/Vulkan, explicitly AMD-"
echo "adapter-targeted) for LD, PCA, and tool-planning compute -- not the"
echo "literal ROCm/HIP API, and not RADEON_API_KEY, which is not read"
echo "anywhere in src/. See README_PROFESSIONAL.md section 5 for exactly"
echo "what that means and doesn't mean."
echo ""
