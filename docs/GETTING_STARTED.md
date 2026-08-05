## Getting Started with NEXUS

### Prerequisites

**Hardware:**
- AMD Radeon GPU (RDNA2 or RDNA3 recommended)
- 16GB+ VRAM (for int4 quantization)
- 32GB+ system RAM

**Software:**
- Python 3.11 or later
- ROCm 6.2+ (for GPU acceleration)
- Git

### Installation

#### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/nexus-ai.git
cd nexus-ai
```

#### 2. Run Setup

```bash
python scripts/setup.py
```

This will:
- Check Python version
- Verify ROCm installation
- Install dependencies
- Create necessary directories
- Set up configuration files

#### 3. Install PyTorch with ROCm (if not already installed)

```bash
# For ROCm 6.2
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
```

### Quick Start

#### 1. Initialize NEXUS in Your Project

```bash
cd /path/to/your/project
nexus init
```

#### 2. Verify Installation

```bash
nexus check
```

This shows:
- GPU availability
- ROCm version
- Memory available
- System configuration

#### 3. Run Your First Debug

```bash
nexus debug "My API tests are failing with timeout errors"
```

NEXUS will:
1. Analyze the causal history
2. Find root causes
3. Simulate fix strategies
4. Provide recommendations

### Example Workflows

#### Time Travel Debugging

```bash
# Run the demo
python examples/demo_time_travel_debug.py
```

This demonstrates:
- Creating a causal timeline
- Recording events (config changes, commits, deployments)
- Tracing backward to find root causes
- Generating fix recommendations

**Output:**
```
🕐 CAUSAL CHAIN DISCOVERED:
--------------------------------------------------
Root causes found: 1

🎯 ROOT CAUSE:
- CONFIG_CHANGE: Updated API timeout from 30s to 5s
  Time: 2026-08-06 14:23:15

🔧 SIMULATED FIX STRATEGIES:
1. Revert timeout to 30s
   Confidence: 95%
   Risk: low

2. Increase timeout to 10s
   Confidence: 85%
   Risk: low
```

#### Performance Benchmarking

```bash
# Run ROCm benchmarks
python scripts/benchmark_rocm.py
```

This tests:
- Single model inference latency
- Parallel agent execution
- Tokens per second
- GPU utilization
- Memory efficiency

**Expected Output (RDNA3):**
```
Single Inference (HIP)
┌────────────┬─────────────────┬────────────┬──────────────┐
│ Model Type │ Avg Latency (ms)│ Tokens/sec │ Success Rate │
├────────────┼─────────────────┼────────────┼──────────────┤
│ fast       │ 87.3            │ 52.4       │ 100%         │
│ code       │ 423.1           │ 28.1       │ 100%         │
└────────────┴─────────────────┴────────────┴──────────────┘

Parallel Agents (HIP)
┌──────────┬──────────────────┬────────────────────┬──────────────────┐
│ # Agents │ Total Time (ms)  │ Avg per Agent (ms) │ Aggregate tok/s  │
├──────────┼──────────────────┼────────────────────┼──────────────────┤
│ 2        │ 912.4            │ 456.2              │ 98.7             │
│ 4        │ 1024.8           │ 256.2              │ 187.3            │
│ 8        │ 1834.2           │ 229.3              │ 312.8            │
└──────────┴──────────────────┴────────────────────┴──────────────────┘
```

### Configuration

#### Environment Variables

Create a `.env` file in your project root:

```bash
# Inference device
NEXUS_INFERENCE_DEVICE=hip  # hip=ROCm, cuda=NVIDIA, cpu=fallback

# Model quantization
NEXUS_INFERENCE_REASONING_QUANTIZATION=int4
NEXUS_INFERENCE_CODE_QUANTIZATION=fp16
NEXUS_INFERENCE_FAST_QUANTIZATION=int4

# Performance
NEXUS_INFERENCE_MAX_PARALLEL_AGENTS=8
NEXUS_INFERENCE_USE_FLASH_ATTENTION=true

# Logging
NEXUS_LOG_LEVEL=INFO
```

#### Custom Configuration File

`.nexus/config.yaml`:

```yaml
inference:
  device: hip
  reasoning_model: "meta-llama/Llama-3.3-70B-Instruct"
  code_model: "Qwen/Qwen2.5-Coder-32B-Instruct"
  fast_model: "microsoft/phi-4"
  
  reasoning_quantization: int4
  code_quantization: fp16
  fast_quantization: int4
  
  max_parallel_agents: 8
  use_flash_attention: true

agents:
  max_agents: 16
  enable_temporal_analyst: true
  enable_code_archaeologist: true
  enable_fix_simulator: true
  max_simulation_branches: 4

graph:
  storage_backend: rocksdb
  max_nodes: 100000
  enable_gpu_acceleration: true
```

### Usage Examples

#### 1. Debug a Test Failure

```bash
nexus debug "Integration tests failing after dependency update"
```

#### 2. Analyze API Performance

```bash
nexus debug "API latency increased by 2x after last deploy"
```

#### 3. Find Root Cause of Bug

```bash
nexus debug "Users reporting authentication errors in production"
```

### Using NEXUS Programmatically

```python
import asyncio
from nexus.core.orchestrator import Orchestrator
from nexus.core.config import NexusConfig

async def debug_my_problem():
    # Initialize
    config = NexusConfig()
    orchestrator = Orchestrator(config)
    await orchestrator.initialize()
    
    # Debug
    result = await orchestrator.debug_problem(
        "My API endpoints are returning 500 errors"
    )
    
    # Access results
    print("Root causes:", result["temporal_analysis"]["root_causes_found"])
    print("Recommendation:", result["recommendation"])
    
    # Cleanup
    await orchestrator.shutdown()

# Run
asyncio.run(debug_my_problem())
```

### Recording Events

To get the most out of NEXUS, record events in your development workflow:

```python
from nexus.graph import NodeType, EdgeType

# Record a config change
config_node_id = await orchestrator.record_event(
    NodeType.CONFIG_CHANGE,
    "Updated database connection pool size",
    data={"old": 10, "new": 50},
)

# Record a deployment
deploy_node_id = await orchestrator.record_event(
    NodeType.BUILD_EVENT,
    "Deployed to production",
)

# Link them
await orchestrator.link_events(
    config_node_id,
    deploy_node_id,
    EdgeType.TRIGGERS,
)
```

### Troubleshooting

#### ROCm Not Detected

```bash
# Check ROCm installation
rocminfo

# Verify PyTorch can see GPU
python -c "import torch; print(torch.cuda.is_available())"

# Check ROCm version
python -c "import torch; print(torch.version.hip)"
```

#### Out of Memory

Reduce model sizes or increase quantization:

```bash
# Use more aggressive quantization
export NEXUS_INFERENCE_REASONING_QUANTIZATION=int4
export NEXUS_INFERENCE_CODE_QUANTIZATION=int8
```

Or reduce parallel agents:

```bash
export NEXUS_INFERENCE_MAX_PARALLEL_AGENTS=4
```

#### Slow Inference

1. Check GPU utilization: `rocm-smi`
2. Enable Flash Attention: `NEXUS_INFERENCE_USE_FLASH_ATTENTION=true`
3. Use smaller models for fast agents

### Performance Tuning

#### For Maximum Speed (Lower Quality)
```bash
NEXUS_INFERENCE_REASONING_QUANTIZATION=int4
NEXUS_INFERENCE_CODE_QUANTIZATION=int4
NEXUS_INFERENCE_FAST_QUANTIZATION=int4
NEXUS_INFERENCE_MAX_PARALLEL_AGENTS=16
```

#### For Maximum Quality (Slower)
```bash
NEXUS_INFERENCE_REASONING_QUANTIZATION=fp16
NEXUS_INFERENCE_CODE_QUANTIZATION=fp16
NEXUS_INFERENCE_FAST_QUANTIZATION=fp16
NEXUS_INFERENCE_MAX_PARALLEL_AGENTS=4
```

#### Balanced (Recommended)
```bash
NEXUS_INFERENCE_REASONING_QUANTIZATION=int4
NEXUS_INFERENCE_CODE_QUANTIZATION=fp16
NEXUS_INFERENCE_FAST_QUANTIZATION=int4
NEXUS_INFERENCE_MAX_PARALLEL_AGENTS=8
```

### Next Steps

1. **Read the Architecture**: See `docs/ARCHITECTURE.md` for deep dive
2. **Explore Examples**: Check `examples/` directory
3. **Run Benchmarks**: Test performance on your GPU
4. **Integrate with Your Workflow**: Add event recording to your CI/CD
5. **Customize Agents**: Create your own specialized agents

### Getting Help

- **Documentation**: See `docs/` directory
- **Issues**: GitHub Issues
- **Examples**: `examples/` directory
- **Architecture**: `docs/ARCHITECTURE.md`

### Contributing

We welcome contributions! See `CONTRIBUTING.md` for guidelines.

### License

MIT License - see `LICENSE` file.
