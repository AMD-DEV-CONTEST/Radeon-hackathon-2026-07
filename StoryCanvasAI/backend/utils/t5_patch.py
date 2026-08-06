import torch
from torch import nn
import transformers.models.t5.modeling_t5 as t5_modeling


class PlainT5LayerNorm(nn.Module):
    def __init__(self, hidden_size, eps=1e-6):
        super().__init__()

        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.variance_epsilon = eps

    def forward(self, hidden_states):

        # Compute variance in fp32 for numerical stability
        variance = (
            hidden_states.to(torch.float32)
            .pow(2)
            .mean(dim=-1, keepdim=True)
        )

        hidden_states = hidden_states * torch.rsqrt(
            variance + self.variance_epsilon
        )

        # Cast back to original dtype (fp16/bf16)
        hidden_states = hidden_states.to(self.weight.dtype)

        return self.weight * hidden_states


def patch_t5_layernorm():
    """
    Replace Apex FusedRMSNorm with a plain PyTorch implementation.
    Call BEFORE loading FluxPipeline.
    """

    t5_modeling.T5LayerNorm = PlainT5LayerNorm

    print("✅ T5 LayerNorm patched (Apex disabled for T5)")