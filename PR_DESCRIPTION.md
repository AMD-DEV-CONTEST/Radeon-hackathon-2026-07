## Summary
This PR introduces Forge V3 - a complete rewrite of the Forge fleet management system with comprehensive multi-vendor GPU support and stress testing capabilities.

## Major Features

### 1. Multi-Vendor GPU Monitoring (`all_smi.rs`)
- **NVIDIA**: Direct NVML API (no nvidia-smi binary required)
- **AMD**: amdgpu sysfs support (works without ROCm)
- **Intel**: i915/xe driver support
- **IBM**: Telum/Spyre accelerator support (s390x via lszcrypt)
- Concurrent GPU probes with SSH-based remote node querying

### 2. GPU Stress & Health Lab (`/gpu-stress`)
- **Real-time monitoring**: GPU util, temperature, VRAM (updates every 2s)
- **4 Stress Modes**:
  - Compute stress (LLM workload simulation)
  - Memory bandwidth testing
  - Thermal soak testing
  - Overclock stability analysis
- **Health Grading**: S/A/B/C/D grades based on temp, stability, power
- **Run History**: Tracks degradation over time
- **Overclock Assessment**: Clock variance and headroom estimation

### 3. Unified V3 Admin Interface
- Fleet auto-discovery across local + remote nodes
- 3 deployment profiles (NIM+Ornith, Ornith+Gemma, Ornith Full)
- Lane configuration & seat management
- Consolidated Chat, Wall, Qual Lab tabs
- Modern responsive design

## Technical Improvements
- Eliminated dependency on nvidia-smi binary (direct NVML API)
- AMD GPU support without ROCm installation
- Multi-vendor GPU detection runs concurrently
- Remote node SSH querying with inline Python scripts
- Consolidated legacy V2 interfaces into single V3 admin

## Testing
- ✅ Verified on 2x Tesla P100-PCIE-16GB
- ✅ Release build successful
- ✅ All API endpoints operational
- ✅ Service tested on port 9100

## Documentation
- `FORGE_V3_STATUS.md`: Complete operational guide
- `FORGE_BENCHMARK_POSTER.md`: Performance benchmarks
- `SESSION_SUMMARY_2026-08-07.md`: Development notes

## Breaking Changes
- Removed legacy V2 HTML files (chat.html, dispatch.html, wall.html)
- All functionality now in unified V3 admin interface
- Service runs on port 9100 by default

## Access URLs (when deployed)
- Main Admin: `http://host:9100/`
- GPU Stress Lab: `http://host:9100/gpu-stress`
- Health Check: `http://host:9100/health`
- Fleet API: `http://host:9100/fleet/all-smi`

## Code Statistics
- **Files Changed**: 17
- **Lines Added**: ~2,921
- **Lines Removed**: ~2,492
- **New Files**: 7 (all_smi.rs, stress.html, admin UI)
- **Removed Files**: 5 (legacy V2 interfaces)

## Checklist
- [x] Code compiles successfully
- [x] All new code follows project conventions
- [x] Documentation added/updated
- [x] Tested locally on real hardware
- [x] No security vulnerabilities introduced
- [x] Legacy code properly migrated/removed
