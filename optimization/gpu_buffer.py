"""Preallocated, CUDA-compatible GPU replay buffer for ROCm PyTorch."""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class ReplayBatch:
    states: torch.Tensor
    actions: torch.Tensor
    rewards: torch.Tensor
    next_states: torch.Tensor
    dones: torch.Tensor


class GPUReplayBuffer:
    """Avoid host copies by storing and sampling every transition on the GPU."""

    def __init__(self, capacity: int, state_dim: int, action_dim: int, *, device: str = "cuda") -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity, self.device = capacity, torch.device(device)
        self.states = torch.empty((capacity, state_dim), dtype=torch.float32, device=self.device)
        self.actions = torch.empty((capacity, action_dim), dtype=torch.float32, device=self.device)
        self.rewards = torch.empty(capacity, dtype=torch.float32, device=self.device)
        self.next_states = torch.empty((capacity, state_dim), dtype=torch.float32, device=self.device)
        self.dones = torch.empty(capacity, dtype=torch.float32, device=self.device)
        self.position = self.size = 0

    def add(self, states: torch.Tensor, actions: torch.Tensor, rewards: torch.Tensor, next_states: torch.Tensor, dones: torch.Tensor) -> None:
        """Insert a batch, wrapping around the preallocated device tensors."""
        states = states.to(self.device)
        count = states.shape[0]
        if count > self.capacity:
            states, actions, rewards, next_states, dones = (x[-self.capacity :] for x in (states, actions, rewards, next_states, dones))
            count = self.capacity
        indices = (torch.arange(count, device=self.device) + self.position) % self.capacity
        self.states[indices], self.actions[indices] = states, actions.to(self.device)
        self.rewards[indices], self.next_states[indices], self.dones[indices] = rewards.to(self.device), next_states.to(self.device), dones.to(self.device)
        self.position = (self.position + count) % self.capacity
        self.size = min(self.capacity, self.size + count)

    def sample(self, batch_size: int) -> ReplayBatch:
        if batch_size > self.size:
            raise ValueError("not enough transitions in replay buffer")
        indices = torch.randint(self.size, (batch_size,), device=self.device)
        return ReplayBatch(self.states[indices], self.actions[indices], self.rewards[indices], self.next_states[indices], self.dones[indices])
