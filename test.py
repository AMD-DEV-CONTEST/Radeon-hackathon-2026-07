import sys
from main import SentinelDesk

def run_test():
    try:
        print("Testing SentinelDesk Initialization (using TinyLlama for quick testing)...")
        # Using TinyLlama and no quantization for a fast test without large downloads
        agent = SentinelDesk(model_name="TinyLlama/TinyLlama-1.1B-Chat-v1.0", persona="helpful test agent", quantization="none")
        print("Initialization Successful.")
        
        print("\nTesting Tool Execution (System Diagnostics)...")
        response = agent.process_input("What is my system status?")
        print(f"\n--- Agent Response ---\n{response}\n----------------------")
        print("\nTest Complete.")
    except Exception as e:
        print(f"Error during test: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_test()
