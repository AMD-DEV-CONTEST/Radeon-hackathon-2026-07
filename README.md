# SentinelDesk: ROCm-Accelerated Autonomous Copilot

SentinelDesk is a local, autonomous desktop AI agent designed for the AMD AI DevMaster Hackathon (Track 2: Agentic AI).

## Features
- **Local Inference Engine:** Modular LLM class explicitly built to use PyTorch with AMD ROCm for local inference, ensuring high performance on AMD GPUs while avoiding external APIs.
- **Quantization Support:** Seamless integration with `bitsandbytes` to load powerful models like `Meta-Llama-3-8B-Instruct` in 4-bit or 8-bit precision on consumer-grade AMD Radeon GPUs without hitting VRAM bottlenecks.
- **Memory Management:** Lightweight local vector database (ChromaDB) to remember past interactions and user persona settings.
- **Tool Use:** Capable of executing local system commands (e.g., system diagnostics and file management) autonomously.

## Environment Configuration (ROCm)

To run SentinelDesk with AMD ROCm acceleration, follow these steps:

1. **Install AMD ROCm:** Follow the official [AMD ROCm installation guide](https://rocm.docs.amd.com/en/latest/deploy/linux/index.html) for your specific OS.
2. **Create a virtual environment (optional but recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Or `venv\Scripts\activate` on Windows
   ```
3. **Install dependencies:**
   The `requirements.txt` includes the PyTorch index URL for ROCm 6.0 and quantization libraries.
   ```bash
   pip install -r requirements.txt
   ```

## Startup Guide

Run the agent directly via the command line. By default, it will load Llama-3-8B in 4-bit quantization to save memory:

```bash
python main.py --model "meta-llama/Meta-Llama-3-8B-Instruct" --persona "helpful companion" --quantization "4bit"
```

### Arguments:
- `--model`: HuggingFace model ID to load. Default is `meta-llama/Meta-Llama-3-8B-Instruct`. Note: Ensure you have accepted the Llama 3 license and logged in via `huggingface-cli` or set your `HF_TOKEN`.
- `--persona`: Define the agent's behavior (e.g., "helpful companion", "system administrator", "grumpy family member").
- `--quantization`: Set quantization level to reduce VRAM usage. Options are `4bit`, `8bit`, and `none`. Defaults to `4bit`.

## Usage
Once running, SentinelDesk provides an interactive prompt.
- Try asking: `"What is my system status?"` to trigger the system diagnostics tool.
- Try asking: `"List files in my directory"` to trigger the directory listing tool.
