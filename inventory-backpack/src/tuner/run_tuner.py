#!/usr/bin/env python3
"""
Adaptive parameter tuning main entry point

Usage:
    python run_tuner.py --mode=offline --iterations=50
    python run_tuner.py --mode=online --experiment-ratio=0.05
"""

import asyncio
import argparse
import logging
import json

from src.tuner.parameter_space import create_vllm_space, create_client_space
from src.tuner.bayesian_optimizer import BayesianOptimizer, OptimizationConfig, OnlineTuner
from src.tuner.vllm_adapter import VLLMPerformanceEvaluator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_offline_tuning():
    """Offline tuning - find the optimal static configuration"""
    
    # Parameter space
    space = create_vllm_space()
    
    # Evaluator
    evaluator = VLLMPerformanceEvaluator("http://localhost:8000")
    
    # Optimizer
    config = OptimizationConfig(
        n_initial_random=15,
        n_iterations=50,
        target_ttft_p99=1000,
        target_rps=5.0,
    )
    
    optimizer = BayesianOptimizer(space, config)
    
    # Execute optimization
    result = await optimizer.optimize(evaluator.evaluate)
    
    # Output results
    print("\n" + "="*60)
    print("OPTIMIZATION RESULT")
    print("="*60)
    print(f"Best config: {json.dumps(result.best_config, indent=2)}")
    print(f"Best performance: {json.dumps(result.best_performance, indent=2)}")
    
    # Save results
    with open("tuning_result.json", "w") as f:
        json.dump({
            "best_config": result.best_config,
            "best_performance": result.best_performance,
            "trials": result.all_trials,
        }, f, indent=2)
    
    return result


async def run_online_tuning():
    """Online tuning - continuous optimization in production environment"""
    
    space = create_vllm_space()
    
    tuner = OnlineTuner(space, experiment_ratio=0.05)
    
    # Default configuration
    default_config = {
        "max_num_seqs": 16,
        "gpu_memory_utilization": 0.85,
        "max_num_batched_tokens": 2048,
    }
    
    await tuner.start(default_config)
    
    # Simulate production environment
    logger.info("Online tuner running, press Ctrl+C to stop")
    
    try:
        while True:
            # Get configuration
            config = tuner.get_config()
            
            # Simulate processing requests
            # In practice: process real requests and report performance
            
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Stopping online tuner")


def main():
    parser = argparse.ArgumentParser(description="Adaptive Parameter Tuner")
    parser.add_argument(
        "--mode",
        choices=["offline", "online"],
        default="offline",
        help="Tuning mode",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of optimization iterations",
    )
    
    args = parser.parse_args()
    
    if args.mode == "offline":
        asyncio.run(run_offline_tuning())
    else:
        asyncio.run(run_online_tuning())


if __name__ == "__main__":
    main()
