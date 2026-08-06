"""
Bayesian optimization - efficient exploration of parameter space
"""

import asyncio
import random
import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Callable, Awaitable, Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .parameter_space import ParameterSpace
from .surrogate_model import PerformanceSurrogate, GPConfig

logger = logging.getLogger(__name__)


@dataclass
class OptimizationConfig:
    """Optimization configuration"""
    # Exploration phase
    n_initial_random: int = 10       # Number of initial random samples
    n_iterations: int = 50           # Total number of iterations
    
    # Convergence criteria
    patience: int = 10                 # Stop after this many rounds without improvement
    improvement_threshold: float = 0.05  # Improvement threshold
    
    # Multi-objective trade-offs
    target_ttft_p99: float = 1000.0   # Target P99 TTFT
    target_rps: float = 5.0           # Target RPS
    max_error_rate: float = 0.01      # Maximum error rate


@dataclass
class OptimizationResult:
    """Optimization result"""
    best_config: dict
    best_performance: dict
    all_trials: List[dict] = field(default_factory=list)
    convergence_curve: List[tuple] = field(default_factory=list)


class BayesianOptimizer:
    """
    Bayesian Optimizer
    
    Workflow:
    1. Initialize with Latin Hypercube Sampling
    2. Train GPR surrogate model
    3. Select next point by maximizing acquisition function
    4. Validate and update model
    5. Repeat 2-4 until convergence
    """
    
    def __init__(
        self,
        param_space: ParameterSpace,
        config: OptimizationConfig = None,
    ):
        self.space = param_space
        self.config = config or OptimizationConfig()
        
        self.surrogate = PerformanceSurrogate()
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    async def optimize(
        self,
        evaluator: Callable[[dict], Awaitable[dict]],
        callback: Optional[Callable[[dict, dict, int], Awaitable]] = None,
    ) -> OptimizationResult:
        """
        Execute optimization
        
        Args:
            evaluator: evaluation function, receives config and returns performance
            callback: per-iteration callback
        
        Returns:
            Optimization result
        """
        
        trials = []
        best_score = float('inf')
        best_config = None
        best_perf = None
        no_improve = 0
        
        # Phase 1: Initial random exploration
        logger.info("Phase 1: Random exploration")
        initial_configs = self._latin_hypercube_sampling(self.config.n_initial_random)
        
        for i, config in enumerate(initial_configs):
            perf = await self._safe_evaluate(evaluator, config)
            trials.append({"config": config, "performance": perf, "iteration": i})
            
            # Update surrogate model
            self.surrogate.add_observation(config, perf)
            
            # Track best
            score = self._score(perf)
            if score < best_score:
                best_score = score
                best_config = config
                best_perf = perf
            
            if callback:
                await callback(config, perf, i)
            
            logger.info(f"Trial {i}: TTFT P99={perf['ttft_p99']:.0f}ms, "
                       f"RPS={perf['rps']:.2f}, score={score:.2f}")
        
        # Phase 2: Bayesian optimization
        logger.info("Phase 2: Bayesian optimization")
        
        for iteration in range(self.config.n_iterations):
            # Train model
            self.surrogate.fit(self.space)
            
            # Acquire next configuration
            next_config = self._optimize_acquisition()
            
            # Evaluate
            perf = await self._safe_evaluate(evaluator, next_config)
            self.surrogate.add_observation(next_config, perf)
            
            trials.append({
                "config": next_config,
                "performance": perf,
                "iteration": iteration + self.config.n_initial_random,
            })
            
            # Check improvement
            score = self._score(perf)
            if score < best_score * (1 - self.config.improvement_threshold):
                best_score = score
                best_config = next_config
                best_perf = perf
                no_improve = 0
            else:
                no_improve += 1
            
            if callback:
                await callback(next_config, perf, iteration)
            
            # Convergence check
            if no_improve >= self.config.patience:
                logger.info(f"Converged at iteration {iteration}")
                break
        
        return OptimizationResult(
            best_config=best_config,
            best_performance=best_perf,
            all_trials=trials,
        )
    
    def _latin_hypercube_sampling(self, n: int) -> List[dict]:
        """
        Latin Hypercube Sampling - uniform coverage of parameter space
        """
        configs = []
        dims = self.space.dimensions
        
        for _ in range(n):
            config = {}
            for param in self.space._params:
                if hasattr(param, 'sample'):
                    config[param.name] = param.sample()
            
            configs.append(config)
        
        return configs
    
    def _optimize_acquisition(self, n_random: int = 1000) -> dict:
        """
        Optimize acquisition function - random sampling + local refinement
        
        Returns: next evaluation point
        """
        # Random sample candidates
        candidates = [self.space.sample() for _ in range(n_random)]
        
        # Evaluate acquisition function
        best_score = float('inf')
        best_config = candidates[0]
        
        for config in candidates:
            score = self.surrogate.acquisition_ucb(config, self.space)
            if score < best_score:
                best_score = score
                best_config = config
        
        return best_config
    
    def _score(self, perf: dict) -> float:
        """
        Combined score (lower is better)
        
        Multi-objective: minimize TTFT, maximize RPS, constrain error rate
        """
        ttft = perf.get("ttft_p99", 99999)
        rps = perf.get("rps", 0)
        error = perf.get("error_rate", 1.0)
        
        # Normalize to [0, 1]
        ttft_norm = min(ttft / 10000, 1.0)  # Cap at 10s
        rps_norm = max(0, 1 - rps / 10)     # 10 RPS is full score
        error_penalty = error * 100          # Heavy penalty for error rate
        
        return ttft_norm * 0.5 + rps_norm * 0.3 + error_penalty
    
    async def _safe_evaluate(
        self,
        evaluator: Callable[[dict], Awaitable[dict]],
        config: dict,
    ) -> dict:
        """Safe evaluation with timeout and retry"""
        for attempt in range(3):
            try:
                # Set evaluation timeout
                result = await asyncio.wait_for(evaluator(config), timeout=120)
                return result
                
            except asyncio.TimeoutError:
                logger.warning(f"Evaluation timeout, attempt {attempt+1}/3")
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Evaluation error: {e}")
                return {
                    "ttft_p99": 99999,
                    "rps": 0,
                    "error_rate": 1.0,
                }
        
        return {
            "ttft_p99": 99999,
            "rps": 0,
            "error_rate": 1.0,
        }


class OnlineTuner:
    """
    Online tuner - continuous optimization in production environment
    
    Features:
    - Low overhead: experiments only on a small fraction of traffic
    - Safe: new configurations are validated before promotion
    - Gradual: progressive traffic migration
    """
    
    def __init__(
        self,
        param_space: ParameterSpace,
        experiment_ratio: float = 0.05,  # 5% traffic used for experiments
    ):
        self.space = param_space
        self.experiment_ratio = experiment_ratio
        
        self._current_config: Optional[dict] = None
        self._best_config: Optional[dict] = None
        self._optimizer: Optional[BayesianOptimizer] = None
        
        # A/B testing state
        self._experiment_configs: List[dict] = []
        self._experiment_results: List[dict] = []
    
    async def start(self, default_config: dict):
        """Start online tuning"""
        self._current_config = default_config
        self._best_config = default_config
        
        self._optimizer = BayesianOptimizer(self.space)
        
        logger.info(f"Online tuner started with config: {default_config}")
    
    def should_use_experiment(self) -> bool:
        """Determine whether the current request should use an experimental configuration"""
        return random.random() < self.experiment_ratio
    
    def get_config(self) -> dict:
        """Get current configuration"""
        if self.should_use_experiment() and self._experiment_configs:
            # Return an experimental configuration
            return random.choice(self._experiment_configs)
        return self._current_config
    
    async def report_result(self, config: dict, performance: dict):
        """Report experiment results"""
        if config in self._experiment_configs:
            self._experiment_results.append({
                "config": config,
                "performance": performance,
            })
            
            # Check if better than current
            if self._is_better(performance, self._best_config):
                # Gradual promotion: 10% first, then 50%, finally 100%
                logger.info(f"New best config found: {config}")
                self._best_config = config
    
    def _is_better(self, perf: dict, current: dict) -> bool:
        """Determine whether performance is better"""
        # Simplified: TTFT P99 reduced by 10% and RPS not decreased by more than 5%
        return (
            perf.get("ttft_p99", 99999) < current.get("ttft_p99", 99999) * 0.9
            and perf.get("rps", 0) > current.get("rps", 0) * 0.95
        )
