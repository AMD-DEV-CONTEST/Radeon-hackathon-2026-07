"""RationalVLA model with API-based LLM for instruction reasoning.

Architecture (API version):
    instruction text → DeepSeek API → <ACT> or <REJ>
                                        |
                                   learned_embedding (512-dim)
                                        |
                                   latent z → ACT policy

No local LLM needed. The API handles all instruction understanding.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Special tokens
# ---------------------------------------------------------------------------
ACT_TOKEN = "<ACT>"
REJ_TOKEN = "<REJ>"


@dataclass
class APIMLLMResponse:
    token: str  # "<ACT>" or "<REJ>"
    reasoning: str
    latency_ms: float
    raw_response: str

    @property
    def prediction(self) -> str:
        """Return 'ACT' or 'REJ' without angle brackets."""
        return self.token.strip("<>")


# ---------------------------------------------------------------------------
# Projection / embedding layer
# ---------------------------------------------------------------------------
class ACTEmbedding(nn.Module):
    """Learned embedding for ACT/REJ tokens → latent space z.

    ACT: learns a 512-dim vector that captures what it means to "execute"
    REJ: always outputs zeros (no action)
    """

    def __init__(self, latent_dim: int = 512):
        super().__init__()
        self.act_embedding = nn.Parameter(torch.randn(1, latent_dim) * 0.02)
        self.latent_dim = latent_dim

    def forward(self, is_act: torch.Tensor) -> torch.Tensor:
        """is_act: bool tensor [B], True=ACT, False=REJ"""
        B = is_act.shape[0]
        z = torch.zeros(B, self.latent_dim, device=is_act.device)
        # ACT samples get the learned embedding, REJ samples stay zero
        act_mask = is_act.to(torch.bool)
        if act_mask.any():
            z[act_mask] = self.act_embedding.expand(act_mask.sum(), -1)
        return z


# ---------------------------------------------------------------------------
# API-based MLLM (DeepSeek / OpenAI compatible)
# ---------------------------------------------------------------------------
class APIMLLM:
    """Calls an external LLM API to classify instructions.

    Prompt template follows RationalVLA paper:
      - Executable: responds with "Sure, I will ... <ACT>"
      - Defective:  responds with "Sorry, I cannot ... <REJ>"
    
    Supports dynamic scene description injection for improved accuracy.
    """

    # Base prompt template (scene description will be injected)
    SYSTEM_PROMPT_TEMPLATE = (
        "You are a robot arm instruction classifier. Reply with ONLY '<ACT>' or '<REJ>'.\n\n"
        "=== SCENE DESCRIPTION ===\n"
        "The scene contains a table with these objects: {scene_description}.\n"
        "The robot arm can only manipulate objects listed above.\n\n"
        "=== CLASSIFICATION RULES ===\n\n"
        "Reply with '<ACT>' if ALL conditions are met:\n"
        "  1. Object is in the scene\n"
        "  2. Action is physically possible (pick, place, push, stack)\n"
        "  3. Action is safe\n\n"
        "Reply with '<REJ>' if ANY condition is met:\n"
        "  - Object NOT in scene (common invalid: cucumber, avocado, apple, pear, grape, pineapple, coconut, cherry, peach)\n"
        "  - Invalid color modifier: purple, neon, glowing, transparent, mirror, rainbow, invisible, holographic\n"
        "  - Invalid physics: weightless, floating, levitating, stuck, frozen\n"
        "  - Invalid action: fly, teleport, shrink, explode, melt, duplicate\n"
        "  - Unsafe action: smash, destroy, crush, throw at person, break\n"
        "  - Unrelated task: sing, calculate, explain, translate, write code\n\n"
        "=== FEW-SHOT EXAMPLES ===\n"
        "  'pick the banana' -> <ACT>\n"
        "  'put the lemon in the bowl' -> <ACT>\n"
        "  'pick the cucumber' -> <REJ> (object not in scene)\n"
        "  'pick the purple banana' -> <REJ> (invalid color: purple)\n"
        "  'pick the neon lemon' -> <REJ> (invalid color: neon)\n"
        "  'smash the lemon' -> <REJ> (unsafe action)\n"
        "  'teleport the banana' -> <REJ> (impossible action)\n"
        "  'sing a song' -> <REJ> (unrelated task)\n"
        "  'place the avocado into the bowl' -> <REJ> (object not in scene)\n\n"
        "=== YOUR TASK ===\n"
        "Classify the following instruction. Reply with ONLY '<ACT>' or '<REJ>'."
    )

    # Default scene description (all scenes combined)
    DEFAULT_SCENE_DESCRIPTION = "Table with banana, lemon, plum, bowl, red block, blue block, green block, red box, blue box."

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_id: str = "DeepSeek-V4-Flash",
        max_retries: int = 3,
        timeout: float = 15.0,
        cache_path: str | None = None,
        scene_name: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model_id = model_id or os.environ.get("LLM_MODEL_ID", "DeepSeek-V4-Flash")
        self.max_retries = max_retries
        self.timeout = timeout
        self.scene_name = scene_name

        # Build scene description
        self.scene_description = self._build_scene_description(scene_name)
        self.SYSTEM_PROMPT = self.SYSTEM_PROMPT_TEMPLATE.format(
            scene_description=self.scene_description
        )

        # Response cache (avoid repeated API calls for same instruction)
        self._cache: dict[str, APIMLLMResponse] = {}
        self._cache_path = Path(cache_path) if cache_path else None
        self._load_cache()

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _build_scene_description(self, scene_name: str | None) -> str:
        """Build scene description from scene config."""
        try:
            from scene_configs import get_scene_objects_list, get_all_scene_objects
            
            if scene_name and scene_name in ['A', 'B', 'C', 'D']:
                # Specific scene
                objects = get_scene_objects_list(scene_name)
                return f"Table with {', '.join(objects)}"
            else:
                # All scenes combined
                all_objects = get_all_scene_objects()
                return f"Table with {', '.join(all_objects)}"
        except ImportError:
            return self.DEFAULT_SCENE_DESCRIPTION

    def _load_cache(self):
        if self._cache_path and self._cache_path.exists():
            with open(self._cache_path) as f:
                data = json.load(f)
                self._cache = {k: APIMLLMResponse(**v) for k, v in data.items()}

    def _save_cache(self):
        if self._cache_path:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(
                    {k: {"token": v.token, "reasoning": v.reasoning, "latency_ms": v.latency_ms, "raw_response": v.raw_response}
                     for k, v in self._cache.items()},
                    f,
                    indent=2,
                )

    def classify(self, instruction: str) -> APIMLLMResponse:
        """Classify a single instruction as ACT or REJ."""
        if instruction in self._cache:
            return self._cache[instruction]

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]

        for attempt in range(self.max_retries):
            try:
                t0 = time.time()
                response = self.client.chat.completions.create(
                    model=self.model_id,
                    messages=messages,
                    max_tokens=10,
                    temperature=0.0,
                )
                latency = (time.time() - t0) * 1000
                text = response.choices[0].message.content.strip()

                # Determine token
                if REJ_TOKEN in text or text == "REJ":
                    token = REJ_TOKEN
                elif ACT_TOKEN in text or text == "ACT":
                    token = ACT_TOKEN
                else:
                    # Heuristic: check for rejection keywords
                    lower = text.lower()
                    if any(w in lower for w in ["sorry", "cannot", "can't", "unable", "impossible"]):
                        token = REJ_TOKEN
                    else:
                        token = ACT_TOKEN

                result = APIMLLMResponse(
                    token=token,
                    reasoning=text,
                    latency_ms=latency,
                    raw_response=text,
                )
                self._cache[instruction] = result
                self._save_cache()
                return result

            except Exception as e:
                if attempt == self.max_retries - 1:
                    # Fallback: simple keyword matching
                    lower = instruction.lower()
                    dangerous = ["throw", "smash", "crush", "swing", "kill", "destroy"]
                    impossible = ["fly", "teleport", "shrink", "levitate", "phase through", "melt"]
                    ooc = ["sing", "poem", "weather", "calculate", "translate", "quantum"]
                    if any(w in lower for w in dangerous):
                        return APIMLLMResponse(REJ_TOKEN, "Safety violation (fallback)", 0, "")
                    if any(w in lower for w in impossible):
                        return APIMLLMResponse(REJ_TOKEN, "Motion defect (fallback)", 0, "")
                    if any(w in lower for w in ooc):
                        return APIMLLMResponse(REJ_TOKEN, "Out of context (fallback)", 0, "")
                    return APIMLLMResponse(ACT_TOKEN, "Executable (fallback)", 0, "")
                time.sleep(1.0 * (attempt + 1))

    def classify_batch(self, instructions: list[str]) -> list[APIMLLMResponse]:
        """Classify a batch of instructions."""
        return [self.classify(inst) for inst in instructions]


# ---------------------------------------------------------------------------
# ACT policy (unchanged)
# ---------------------------------------------------------------------------
class ACTPolicyHead(nn.Module):
    def __init__(
        self,
        state_dim: int = 9,
        action_dim: int = 9,
        latent_dim: int = 512,
        chunk_size: int = 20,
        transformer_layers: int = 4,
        transformer_heads: int = 8,
    ):
        super().__init__()
        self.chunk_size = chunk_size
        self.action_dim = action_dim

        self.visual_encoder = nn.Sequential(
            nn.Conv2d(3, 32, 7, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(64, 128, 3, stride=2, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((8, 8)),
            nn.Flatten(),
            nn.Linear(128 * 8 * 8, 256),
            nn.ReLU(),
        )

        self.state_encoder = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 256),
            nn.ReLU(),
        )

        self.latent_encoder = nn.Sequential(
            nn.Linear(latent_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, 256),
            nn.ReLU(),
        )

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=256,
            nhead=transformer_heads,
            dim_feedforward=1024,
            batch_first=True,
            dropout=0.1,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=transformer_layers)
        self.action_head = nn.Linear(256, chunk_size * action_dim)

    def forward(self, image: torch.Tensor, state: torch.Tensor, latent_z: torch.Tensor) -> torch.Tensor:
        B = image.shape[0]
        vis_feat = self.visual_encoder(image)
        state_feat = self.state_encoder(state)
        latent_feat = self.latent_encoder(latent_z)
        tokens = torch.stack([vis_feat, state_feat, latent_feat], dim=1)
        encoded = self.transformer(tokens)
        pooled = encoded.mean(dim=1)
        action = self.action_head(pooled)
        return action.view(B, self.chunk_size, self.action_dim)


# ---------------------------------------------------------------------------
# Full RationalVLA model (API version)
# ---------------------------------------------------------------------------
class RationalVLA(nn.Module):
    def __init__(
        self,
        api_mllm: APIMLLM,
        state_dim: int = 9,
        action_dim: int = 9,
        latent_dim: int = 512,
        chunk_size: int = 20,
        act_transformer_layers: int = 4,
    ):
        super().__init__()
        self.api_mllm = api_mllm
        self.act_embedding = ACTEmbedding(latent_dim)
        self.act_policy = ACTPolicyHead(
            state_dim=state_dim,
            action_dim=action_dim,
            latent_dim=latent_dim,
            chunk_size=chunk_size,
            transformer_layers=act_transformer_layers,
        )

    def forward(
        self,
        image: torch.Tensor,
        state: torch.Tensor,
        instruction: str | list[str] | None = None,
        is_act: torch.Tensor | None = None,
    ) -> dict:
        B = image.shape[0]

        if is_act is not None:
            # Pre-computed ACT/REJ labels (training mode)
            is_act_bool = is_act.to(torch.bool)
        elif instruction is not None:
            # Call API (inference mode)
            if isinstance(instruction, str):
                instruction = [instruction] * B
            responses = self.api_mllm.classify_batch(instruction)
            is_act_bool = torch.tensor(
                [r.token == ACT_TOKEN for r in responses],
                device=image.device,
            )
        else:
            is_act_bool = torch.ones(B, dtype=torch.bool, device=image.device)

        latent_z = self.act_embedding(is_act_bool)
        action = self.act_policy(image, state, latent_z)

        return {
            "action": action,
            "latent_z": latent_z,
            "is_rejected": ~is_act_bool,
            "is_act": is_act_bool,
        }

    def freeze_act(self):
        for param in self.act_policy.parameters():
            param.requires_grad = False

    def unfreeze_act(self):
        for param in self.act_policy.parameters():
            param.requires_grad = True

    def get_trainable_parameters(self):
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


def build_rationalvla(api_key: str | None = None, base_url: str | None = None, model_id: str | None = None, use_api: bool = True, act_transformer_layers: int = 4, scene_name: str | None = None) -> RationalVLA:
    if use_api:
        api_mllm = APIMLLM(
            api_key=api_key or os.environ.get("LLM_API_KEY"),
            base_url=base_url or os.environ.get("LLM_BASE_URL"),
            model_id=model_id or os.environ.get("LLM_MODEL_ID", "DeepSeek-V4-Flash"),
            cache_path="outputs/rationalvla/api_cache.json",
            scene_name=scene_name,
        )
        model = RationalVLA(api_mllm=api_mllm, act_transformer_layers=act_transformer_layers)
        print(f"RationalVLA (API) built: {sum(p.numel() for p in model.parameters()):,} params")
        print(f"  LLM: {api_mllm.model_id} @ {api_mllm.base_url}")
        print(f"  Scene: {api_mllm.scene_description}")
    else:
        model = RationalVLA(api_mllm=None, act_transformer_layers=act_transformer_layers)
        print(f"RationalVLA (no API) built: {sum(p.numel() for p in model.parameters()):,} params")
    return model


if __name__ == "__main__":
    model = build_rationalvla()
    print(f"Trainable: {model.get_trainable_parameters():,}")

    dummy_image = torch.randn(2, 3, 224, 224)
    dummy_state = torch.randn(2, 9)
    is_act = torch.tensor([True, False])

    output = model(dummy_image, dummy_state, is_act=is_act)
    print(f"Action: {output['action'].shape}")
    print(f"z: {output['latent_z'].shape}")
    print(f"Rejected: {output['is_rejected']}")
    print("OK")