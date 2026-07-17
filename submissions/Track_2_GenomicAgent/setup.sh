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

# Check for Radeon GPU tools (optional)
if command -v rocm-smi &> /dev/null; then
    echo "✓ ROCm detected:"
    rocm-smi --version
else
    echo "⚠ ROCm not found (OK for CPU mode, required for GPU optimization)"
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
echo "  1. Run demo:        cargo run --release"
echo "  2. Run benchmarks:  cargo run --release -- bench"
echo ""
echo "For Radeon GPU optimization:"
echo "  1. Create Radeon Cloud account: https://radeon-global.anruicloud.com/"
echo "  2. Set RADEON_API_KEY environment variable"
echo "  3. Run: RADEON_API_KEY=xxx cargo run --release"
echo ""
