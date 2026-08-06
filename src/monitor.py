import requests
import time

METRICS_URL = "https://radeon-global.anruicloud.com/spaces/u-14563-bb95df49/8000/metrics"

def get_vllm_stats():
    try:
        response = requests.get(METRICS_URL)
        lines = response.text.split('\n')
        
        stats = {}
        for line in lines:
            # Skip comments and empty lines
            if line.startswith('#') or not line.strip():
                continue
                
            # Extract active requests
            if line.startswith('vllm:num_requests_running'):
                stats['Active Requests'] = int(float(line.split(' ')[1]))
            
            # Extract GPU Cache Usage
            elif line.startswith('vllm:kv_cache_usage_perc'):
                stats['GPU KV Cache Usage'] = f"{float(line.split(' ')[1]) * 100:.1f}%"
                
            # Extract Total Tokens
            elif line.startswith('vllm:prompt_tokens_total'):
                stats['Total Prompt Tokens'] = int(float(line.split(' ')[1]))
            elif line.startswith('vllm:generation_tokens_total'):
                stats['Total Gen Tokens'] = int(float(line.split(' ')[1]))

        print("\n" + "="*30)
        print("🚀 AMD GPU vLLM Telemetry")
        print("="*30)
        for key, value in stats.items():
            print(f"{key:<22}: {value}")
        print("="*30)

    except Exception as e:
        print(f"Failed to connect to GPU monitor: {e}")

# Run this in a loop to update every 2 seconds
if __name__ == "__main__":
    while True:
        get_vllm_stats()
        time.sleep(2)
