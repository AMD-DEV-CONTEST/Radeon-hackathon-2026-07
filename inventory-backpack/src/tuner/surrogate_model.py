"""
Gaussian Process Regression (GPR) - performance surrogate model

Goal: predict performance in unexplored regions using a small number of observations
"""

import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class GPConfig:
    """Gaussian process configuration"""
    kernel: str = "matern52"  # or "rbf"
    noise_variance: float = 1e-5
    length_scale: Optional[float] = None


class GaussianProcessRegressor:
    """
    Gaussian Process Regression - lightweight implementation
    
    Uses Matern 5/2 kernel, suitable for non-smooth response surfaces
    """
    
    def __init__(self, config: GPConfig = None):
        self.config = config or GPConfig()
        
        self._X: List[np.ndarray] = []  # Training inputs
        self._y: List[float] = []        # Training outputs (standardized)
        
        self._mean_y = 0.0
        self._std_y = 1.0
        
        # Kernel function parameters
        self._length_scale = None
        self._signal_variance = 1.0
    
    def _kernel(self, x1: np.ndarray, x2: np.ndarray) -> float:
        """Matern 5/2 kernel"""
        r = np.linalg.norm(x1 - x2)
        
        if self._length_scale is None:
            # Auto-estimate
            self._length_scale = max(0.1, np.std(self._X) * 0.5) if len(self._X) > 1 else 0.5
        
        scaled = r * np.sqrt(5) / self._length_scale
        
        return self._signal_variance * (1 + scaled + scaled**2 / 3) * np.exp(-scaled)
    
    def _build_kernel_matrix(self, X: List[np.ndarray]) -> np.ndarray:
        """Build the kernel matrix"""
        n = len(X)
        K = np.zeros((n, n))
        
        for i in range(n):
            for j in range(i, n):
                k = self._kernel(X[i], X[j])
                K[i, j] = k
                K[j, i] = k
        
        # Add noise
        K += self.config.noise_variance * np.eye(n)
        
        return K
    
    def fit(self, X: List[np.ndarray], y: List[float]):
        """
        Train the model
        
        Args:
            X: list of parameter vectors
            y: performance metrics (e.g. P99 TTFT)
        """
        if len(X) < 2:
            raise ValueError("Need at least 2 samples")
        
        self._X = X
        
        # Standardize y
        self._mean_y = np.mean(y)
        self._std_y = max(np.std(y), 1e-6)
        self._y = [(yi - self._mean_y) / self._std_y for yi in y]
        
        # Estimate length scale
        if len(X) > 1:
            distances = []
            for i in range(len(X)):
                for j in range(i+1, len(X)):
                    distances.append(np.linalg.norm(X[i] - X[j]))
            self._length_scale = np.median(distances) * 0.5
        
        logger.info(f"GPR fitted: {len(X)} samples, length_scale={self._length_scale:.4f}")
    
    def predict(self, x: np.ndarray, return_std: bool = True) -> Tuple[float, float]:
        """
        Predict performance and uncertainty at a new point
        
        Returns:
            (predicted value, standard deviation)
        """
        if not self._X:
            return 0.0, 1.0  # No information
        
        # Build kernel matrix
        K = self._build_kernel_matrix(self._X)
        
        # Compute kernel between new point and training points
        k_star = np.array([self._kernel(x, xi) for xi in self._X])
        
        try:
            # Solve using Cholesky decomposition
            L = np.linalg.cholesky(K)
            alpha = np.linalg.solve(L.T, np.linalg.solve(L, self._y))
            
            # Prediction
            mu = np.dot(k_star, alpha)
            
            # Variance
            v = np.linalg.solve(L, k_star)
            k_star_star = self._kernel(x, x)
            var = k_star_star - np.dot(v, v)
            var = max(var, 1e-10)  # Ensure non-negative
            
            # De-standardize
            mu_orig = mu * self._std_y + self._mean_y
            std_orig = np.sqrt(var) * self._std_y
            
            return mu_orig, std_orig
            
        except np.linalg.LinAlgError:
            # Matrix is singular, return mean
            return self._mean_y, self._std_y


class PerformanceSurrogate:
    """
    Performance surrogate - wraps GPR, handles multiple objectives
    """
    
    def __init__(self):
        # Multi-objective GPR
        self._ttft_model = GaussianProcessRegressor()
        self._rps_model = GaussianProcessRegressor()
        self._error_model = GaussianProcessRegressor()
        
        # Raw data
        self._configs: List[dict] = []
        self._performances: List[dict] = []
    
    def add_observation(self, config: dict, performance: dict):
        """Add an observation"""
        self._configs.append(config)
        self._performances.append(performance)
    
    def fit(self, param_space: "ParameterSpace"):
        """Train all models"""
        if len(self._configs) < 3:
            logger.warning("Too few observations, using random")
            return
        
        # Encode parameters
        X = [np.array(param_space.encode(c)) for c in self._configs]
        
        # Train each objective
        self._ttft_model.fit(X, [p["ttft_p99"] for p in self._performances])
        self._rps_model.fit(X, [p["rps"] for p in self._performances])
        self._error_model.fit(X, [p["error_rate"] for p in self._performances])
    
    def predict(self, config: dict, param_space: "ParameterSpace") -> dict:
        """Predict performance"""
        x = np.array(param_space.encode(config))
        
        ttft, ttft_std = self._ttft_model.predict(x)
        rps, rps_std = self._rps_model.predict(x)
        error, error_std = self._error_model.predict(x)
        
        return {
            "ttft_p99": {"mean": ttft, "std": ttft_std},
            "rps": {"mean": rps, "std": rps_std},
            "error_rate": {"mean": error, "std": error_std},
        }
    
    def acquisition_ucb(self, config: dict, param_space: "ParameterSpace", kappa: float = 2.0) -> float:
        """
        Upper Confidence Bound acquisition function
        
        Returns: score (lower is better, since we minimize TTFT)
        """
        pred = self.predict(config, param_space)
        
        # Combined score: minimize TTFT, constrain RPS and Error
        ttft_score = pred["ttft_p99"]["mean"] - kappa * pred["ttft_p99"]["std"]
        
        # Penalty terms
        rps_penalty = max(0, 5.0 - pred["rps"]["mean"]) * 1000  # Penalty when RPS < 5
        error_penalty = pred["error_rate"]["mean"] * 10000  # Error rate penalty
        
        return ttft_score + rps_penalty + error_penalty
