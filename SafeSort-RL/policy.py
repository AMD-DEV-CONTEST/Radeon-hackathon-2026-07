"""
Language-conditioned policy for waste sorting.
Day 2 implementation - train policy with instruction conditioning.
"""

import torch
import torch.nn as nn
import clip
import numpy as np


class SimpleCNN(nn.Module):
    """Encode image to embedding"""
    
    def __init__(self, output_dim=512):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.fc = nn.Sequential(
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, output_dim),
        )
    
    def forward(self, x):
        """x: (B, 3, H, W)"""
        x = self.conv(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x


class LanguageConditionedPolicy(nn.Module):
    """Policy: image + instruction -> action"""
    
    def __init__(self, image_dim=512, instruction_dim=512, action_dim=5, device="cuda"):
        super().__init__()
        self.device = device
        self.image_dim = image_dim
        self.instruction_dim = instruction_dim
        
        # Vision encoder (trainable)
        self.vision_encoder = SimpleCNN(output_dim=image_dim)
        
        # Language encoder (CLIP, frozen)
        self.clip_model, _ = clip.load("ViT-B/32", device=device)
        for param in self.clip_model.parameters():
            param.requires_grad = False
        
        # Fusion head (trainable)
        fused_dim = image_dim + instruction_dim
        self.fusion = nn.Sequential(
            nn.Linear(fused_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
        )
        
        # Policy head: action
        self.policy_head = nn.Linear(128, action_dim)
        
        # Value head (for PPO)
        self.value_head = nn.Linear(128, 1)
    
    def encode_image(self, image):
        """image: (B, 3, H, W) tensor"""
        return self.vision_encoder(image)
    
    def encode_instruction(self, instruction_text):
        """
        instruction_text: list of strings or single string
        Returns: (B, 512) tensor
        """
        if isinstance(instruction_text, str):
            instruction_text = [instruction_text]
        
        with torch.no_grad():
            text_tokens = clip.tokenize(instruction_text).to(self.device)
            instruction_embeddings = self.clip_model.encode_text(text_tokens)
            instruction_embeddings = instruction_embeddings / instruction_embeddings.norm(dim=-1, keepdim=True)
        
        return instruction_embeddings
    
    def forward(self, image, instruction_embedding):
        """
        Args:
            image: (B, 3, H, W) tensor
            instruction_embedding: (B, 512) tensor
        
        Returns:
            action: (B, 5) tensor
            value: (B, 1) tensor
        """
        # Encode image
        image_emb = self.encode_image(image)
        
        # Fuse
        fused = torch.cat([image_emb, instruction_embedding], dim=-1)
        hidden = self.fusion(fused)
        
        # Predict
        action = self.policy_head(hidden)
        value = self.value_head(hidden)
        
        return action, value
    
    def get_action_and_value(self, image, instruction_embedding):
        """Used by SB3"""
        action, value = self.forward(image, instruction_embedding)
        return action, value


def test_policy():
    """Quick test"""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    policy = LanguageConditionedPolicy(device=device)
    
    # Dummy inputs
    dummy_image = torch.randn(2, 3, 64, 64).to(device)
    dummy_instruction = policy.encode_instruction(["Dispose of hazardous waste.", "Recycle batteries."])
    
    # Forward pass
    action, value = policy.forward(dummy_image, dummy_instruction)
    
    print(f"Action shape: {action.shape}")
    print(f"Value shape: {value.shape}")
    print("✓ Policy works!")


if __name__ == "__main__":
    test_policy()
