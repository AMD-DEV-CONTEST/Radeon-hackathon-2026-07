#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

VLLM_URL="http://localhost:8000"
if [ "${1:-}" == "--vllm-url" ] && [ -n "${2:-}" ]; then
    VLLM_URL="$2"
fi

echo -e "${GREEN}Running Bunker Benchmarks against ${VLLM_URL}...${NC}"

# 1. TTFT (Time to First Token)
echo -e "\n${YELLOW}--- 1. TTFT (Time to First Token) ---${NC}"
TTFT=$(curl -o /dev/null -s -w "%{time_starttransfer}\n" -X POST "${VLLM_URL}/v1/completions" \
    -H "Content-Type: application/json" \
    -d '{"model": "Qwen/Qwen3-30B-A3B", "prompt": "Hello", "max_tokens": 1}')
echo "TTFT: ${TTFT}s"

# 2. Throughput
echo -e "\n${YELLOW}--- 2. Throughput ---${NC}"
start_time=$(date +%s.%N)
curl -s -X POST "${VLLM_URL}/v1/completions" \
    -H "Content-Type: application/json" \
    -d '{"model": "Qwen/Qwen3-30B-A3B", "prompt": "Write a long story about ROCm on AMD", "max_tokens": 256}' > /dev/null
end_time=$(date +%s.%N)
total_time=$(echo "$end_time - $start_time" | bc)
tps=$(echo "256 / $total_time" | bc -l)
echo "Throughput: ~${tps} tokens/s"

# 3. GPU Memory
echo -e "\n${YELLOW}--- 3. GPU Memory ---${NC}"
if command -v rocm-smi &> /dev/null; then
    rocm-smi --showmeminfo vram
else
    echo -e "${YELLOW}rocm-smi not found. Skipping memory check.${NC}"
fi

# 4. RAG Performance
echo -e "\n${YELLOW}--- 4. RAG Performance ---${NC}"
python3 << 'EOF'
import time
try:
    from sentence_transformers import SentenceTransformer
    print("Loading embedding model...")
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    
    start = time.time()
    embeddings = model.encode("This is a benchmark query for RAG performance on ROCm.")
    end = time.time()
    
    print(f"Embedding time: {(end - start)*1000:.2f} ms")
except ImportError:
    print("sentence_transformers not installed. Skipping RAG benchmark.")
EOF

echo -e "\n${GREEN}====================================${NC}"
echo -e "${GREEN}      Benchmark Complete            ${NC}"
echo -e "${GREEN}====================================${NC}"
