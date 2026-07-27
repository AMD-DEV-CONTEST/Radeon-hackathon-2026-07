# Rocm Reproduce Steps


## 1. Install llama.cpp
Choose image: amd-oneclick-base:git-proxy-test-20260528-1125
```
apt update
apt install -y git cmake build-essential
cd /workspace
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
HIPCXX="$(hipconfig -l)/clang" HIP_PATH="$(hipconfig -R)" cmake -S . -B build  -DGGML_HIP=ON  -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(nproc)"

# Confirm that the HIP version has been compiled
./build/bin/llama-cli --list-devices

# Download vision model
./build/bin/llama cli -hf mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K

# Exit and start LLM service
/exit
./build/bin/llama serve \
  -hf mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K \
  --mmproj-url "https://hf-mirror.com/mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-GGUF/resolve/main/Qwen3.6-35B-A3B-Fable-5-Distill.mmproj-f16.gguf" \
  -ngl 999 \
  -c 32768 \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --host 0.0.0.0 \
  --port 8080
```

## 2. Install frp (optional)
```
/var/run/secrets/frp-self-service/install
# Open a new terminal
export PATH="$HOME/.local/bin:$PATH"
# Expose 8080 port
"$HOME/.local/bin/rc-tunnel" expose --port 8080
# Will display url like xxxxxx.radeon.firstdg.ai
```

