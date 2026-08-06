import torch
import json
from transformers import (
    AutoProcessor,
    Qwen2_5_VLForConditionalGeneration
)


class QwenService:

    def __init__(self, model_name):

        self.model_name = model_name

        self.model = None
        self.processor = None

    def load(self):

        print(f"Loading {self.model_name}...")

        self.processor = AutoProcessor.from_pretrained(
            self.model_name
        )

        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_name,
            dtype=torch.float16,
            device_map="cuda"
        )

        print("✅ Qwen Loaded")
    def generate(self, prompt):

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ]

        text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        inputs = self.processor(
            text=[text],
            return_tensors="pt"
        ).to(self.model.device)

        output = self.model.generate(
            **inputs,
            max_new_tokens=2500
        )

        generated_ids = output[:, inputs.input_ids.shape[1]:]

        response = self.processor.batch_decode(
        generated_ids,
        skip_special_tokens=True
        )[0].strip()
        response = response.replace("```json", "").replace("```", "").strip()
        return json.loads(response)