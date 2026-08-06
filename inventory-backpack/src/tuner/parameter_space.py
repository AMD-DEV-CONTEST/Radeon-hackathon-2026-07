"""
Parameter space definition - configurable, constrainable, discretizable
"""

from dataclasses import dataclass, field
from typing import List, Union, Callable, Optional
import random
import math


@dataclass(frozen=True)
class ContinuousParam:
    """Continuous parameter"""
    name: str
    low: float
    high: float
    log_scale: bool = False  # Log-scale sampling (e.g. learning rate)
    
    def sample(self) -> float:
        if self.log_scale:
            log_low, log_high = math.log(self.low), math.log(self.high)
            return math.exp(random.uniform(log_low, log_high))
        return random.uniform(self.low, self.high)
    
    def normalize(self, value: float) -> float:
        """Normalize to [0, 1]"""
        if self.log_scale:
            log_low, log_high = math.log(self.low), math.log(self.high)
            return (math.log(value) - log_low) / (log_high - log_low)
        return (value - self.low) / (self.high - self.low)
    
    def denormalize(self, normalized: float) -> float:
        """Denormalize from [0, 1]"""
        if self.log_scale:
            log_low, log_high = math.log(self.low), math.log(self.high)
            return math.exp(log_low + normalized * (log_high - log_low))
        return self.low + normalized * (self.high - self.low)


@dataclass(frozen=True)
class DiscreteParam:
    """Discrete parameter"""
    name: str
    choices: List[Union[int, str, bool]]
    
    def sample(self) -> Union[int, str, bool]:
        return random.choice(self.choices)
    
    def encode(self, value) -> int:
        """Encode as integer index"""
        return self.choices.index(value)
    
    def decode(self, index: int):
        """Decode from index"""
        return self.choices[index]


@dataclass(frozen=True)
class IntegerParam:
    """Integer parameter (discretization of continuous integers)"""
    name: str
    low: int
    high: int
    
    def sample(self) -> int:
        return random.randint(self.low, self.high)
    
    def normalize(self, value: int) -> float:
        return (value - self.low) / (self.high - self.low)
    
    def denormalize(self, normalized: float) -> int:
        return int(self.low + normalized * (self.high - self.low))


class ParameterSpace:
    """
    Parameter space - supports mixed-type parameters
    """
    
    def __init__(self):
        self._params: List[Union[ContinuousParam, DiscreteParam, IntegerParam]] = []
        self._param_map: dict = {}
    
    def add_continuous(
        self,
        name: str,
        low: float,
        high: float,
        log_scale: bool = False,
    ) -> "ParameterSpace":
        p = ContinuousParam(name, low, high, log_scale)
        self._params.append(p)
        self._param_map[name] = p
        return self
    
    def add_discrete(
        self,
        name: str,
        choices: List[Union[int, str, bool]],
    ) -> "ParameterSpace":
        p = DiscreteParam(name, choices)
        self._params.append(p)
        self._param_map[name] = p
        return self
    
    def add_integer(
        self,
        name: str,
        low: int,
        high: int,
    ) -> "ParameterSpace":
        p = IntegerParam(name, low, high)
        self._params.append(p)
        self._param_map[name] = p
        return self
    
    def sample(self) -> dict:
        """Randomly sample a set of parameters"""
        return {p.name: p.sample() for p in self._params}
    
    def encode(self, config: dict) -> List[float]:
        """Encode as a numeric vector (for GPR)"""
        encoded = []
        for p in self._params:
            value = config[p.name]
            if isinstance(p, ContinuousParam):
                encoded.append(p.normalize(value))
            elif isinstance(p, IntegerParam):
                encoded.append(p.normalize(value))
            elif isinstance(p, DiscreteParam):
                encoded.append(p.encode(value) / len(p.choices))
        return encoded
    
    @property
    def param_names(self) -> List[str]:
        return [p.name for p in self._params]
    
    @property
    def dimensions(self) -> int:
        return len(self._params)
    
    def get_param(self, name: str):
        return self._param_map[name]


# vLLM parameter space definition
def create_vllm_space() -> ParameterSpace:
    """
    vLLM parameter optimization space
    
    Defined based on actual constraints
    """
    return (
        ParameterSpace()
        # Key: concurrency control
        .add_integer("max_num_seqs", 4, 64)
        
        # Key: GPU memory utilization
        .add_continuous("gpu_memory_utilization", 0.70, 0.95)
        
        # Batch size
        .add_integer("max_num_batched_tokens", 512, 8192, log_scale=True)
        
        # Scheduling strategy
        .add_discrete("scheduling_strategy", ["fcfs", "priority"])
        
        # Preemption
        .add_discrete("preemption_mode", ["swap", "recompute"])
        
        # Chunked prefill
        .add_discrete("enable_chunked_prefill", [True, False])
        
        # Swap space
        .add_integer("swap_space", 1, 16)
        
        # Pipeline parallelism
        .add_integer("pipeline_parallel_size", 1, 2)
    )


# Client parameter space
def create_client_space() -> ParameterSpace:
    """Client parameter optimization space"""
    return (
        ParameterSpace()
        .add_integer("concurrency", 3, 30)
        .add_continuous("timeout_connect", 1.0, 10.0)
        .add_continuous("timeout_read", 10.0, 120.0)
        .add_integer("retry_count", 0, 3)
        .add_continuous("backoff_base", 1.0, 3.0)
    )
