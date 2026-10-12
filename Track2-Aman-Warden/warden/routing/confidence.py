import numpy as np

class PlattScaler:
    """
    Platt Scaling for confidence calibration.
    
    Transforms raw model output (logits or uncalibrated softmax probabilities)
    into calibrated probabilities that better represent true confidence.
    
    Formula: P(y=1|x) = 1 / (1 + exp(A * f(x) + B))
    where f(x) is the uncalibrated probability or logit.
    """
    def __init__(self, A: float = -1.5, B: float = 0.5):
        # Default A and B values chosen to slightly penalize 
        # overconfident predictions around the 0.6 to 0.9 range.
        self.A = A
        self.B = B

    def calibrate(self, raw_prob: float) -> float:
        """Calibrate a raw probability between 0 and 1."""
        # Convert raw probability to a pseudo-logit to avoid log(0)
        eps = 1e-7
        p = max(eps, min(1 - eps, raw_prob))
        f_x = np.log(p / (1 - p))
        
        calibrated = 1.0 / (1.0 + np.exp(self.A * f_x + self.B))
        return float(calibrated)

class ConfidenceCalibrator:
    """
    Main calibrator that routes different models to their respective scaling functions.
    """
    def __init__(self):
        # PlattScaler tailored for Prompt Guard 2's tendency to be overconfident on short prompts
        self.tier1_scaler = PlattScaler(A=-1.2, B=0.3)

    def calibrate_tier1(self, raw_prob: float) -> float:
        return self.tier1_scaler.calibrate(raw_prob)
