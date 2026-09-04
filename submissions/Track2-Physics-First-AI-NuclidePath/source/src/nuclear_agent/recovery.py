"""Deterministic bounded-grid recovery, explicitly not Bayesian inference."""
from dataclasses import dataclass
from itertools import product
from typing import Callable, Mapping, Sequence
from types import MappingProxyType
from .likelihood import gaussian_loglikelihood, left_censored_gaussian_loglikelihood

@dataclass(frozen=True, slots=True)
class RecoveryResult:
    best_parameters: Mapping
    best_loglikelihood: float
    objective_values: tuple[tuple[Mapping, float], ...]
    identifiable: bool
    diagnostics: tuple[str, ...]
    def __post_init__(self):
        object.__setattr__(self,"best_parameters",MappingProxyType(dict(self.best_parameters)))
        object.__setattr__(self,"objective_values",tuple((MappingProxyType(dict(p)),float(v)) for p,v in self.objective_values))

def bounded_grid_recovery(observations: Sequence[tuple[object, object]], predictor: Callable[[Mapping, object], float], parameter_grid: Mapping[str, Sequence], uncertainty: float = 1.0, censored: bool = False) -> RecoveryResult:
    if not parameter_grid or any(not values for values in parameter_grid.values()): raise ValueError("parameter grid must be non-empty")
    if not observations: raise ValueError("observations must be non-empty")
    if isinstance(uncertainty,bool) or not isinstance(uncertainty,(int,float)) or uncertainty <= 0: raise ValueError("uncertainty must be positive")
    names=tuple(parameter_grid); results=[]
    for vals in product(*(parameter_grid[n] for n in names)):
        params=dict(zip(names, vals)); score=0.0
        for t,y in observations:
            pred=predictor(params,t)
            score += left_censored_gaussian_loglikelihood(y,pred,uncertainty) if censored else gaussian_loglikelihood(y,pred,uncertainty)
        results.append((params,score))
    results.sort(key=lambda x: (-x[1], tuple(repr(x[0][n]) for n in names)))
    best=results[0][1]; ties=[r for r in results if abs(r[1]-best) <= 1e-12]
    spread=max(r[1] for r in results)-min(r[1] for r in results)
    diagnostics=[]
    if len(ties)>1: diagnostics.append(f"tie between {len(ties)} grid points")
    if spread <= 1e-12: diagnostics.append("flat objective across bounded grid")
    return RecoveryResult(dict(results[0][0]), best, tuple(results), not diagnostics, tuple(diagnostics))
