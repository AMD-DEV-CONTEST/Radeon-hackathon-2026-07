"""Validated Gaussian observation likelihoods; no sampler is included."""
import math

def _finite(x, name):
    if isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(float(x)): raise ValueError(f"{name} must be finite")
    return float(x)

def gaussian_loglikelihood(observed, predicted, uncertainty):
    y=_finite(observed,"observed"); mu=_finite(predicted,"predicted"); sigma=_finite(uncertainty,"uncertainty")
    if sigma <= 0: raise ValueError("uncertainty must be positive")
    z=(y-mu)/sigma
    return -0.5*z*z - math.log(sigma) - 0.5*math.log(2*math.pi)

def left_censored_gaussian_loglikelihood(limit, predicted, uncertainty):
    c=_finite(limit,"detection limit"); mu=_finite(predicted,"predicted"); sigma=_finite(uncertainty,"uncertainty")
    if sigma <= 0: raise ValueError("uncertainty must be positive")
    cdf=0.5*(1+math.erf((c-mu)/(sigma*math.sqrt(2))))
    if cdf <= 0: return -math.inf
    return math.log(cdf)
