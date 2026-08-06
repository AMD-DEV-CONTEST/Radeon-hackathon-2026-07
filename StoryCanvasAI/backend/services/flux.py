import torch
from diffusers import FluxPipeline

from StoryCanvasAI.backend.utils.t5_patch import patch_t5_layernorm


class FluxService:

    def __init__(self, model_name):
        self.model_name = model_name
        self.pipeline = None

    def load(self):
        """
        Load the FLUX pipeline.
        Apply the T5 LayerNorm patch BEFORE the model is constructed.
        """

        # Patch T5 LayerNorm before loading the model
        patch_t5_layernorm()

        print("Current T5LayerNorm patched successfully.")

        print(f"Loading {self.model_name}...")

        self.pipeline = FluxPipeline.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16
        )

        self.pipeline.to("cuda")

        print("✅ FLUX Loaded Successfully")

    def generate_image(
        self,
        visual_prompt,
        detail_prompt,
        output_path,
        width=1024,
        height=1024,
        steps=4,
        guidance_scale=0.0
    ):
        """
        Generate an image from a text prompt.
        """

        if self.pipeline is None:
            raise RuntimeError(
                "FLUX model is not loaded. Call load() first."
            )

        image = self.pipeline(
            prompt=visual_prompt,
            prompt_2=detail_prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            guidance_scale=guidance_scale
        ).images[0]

        image.save(output_path)

        print(f"✅ Image saved to: {output_path}")

        return image