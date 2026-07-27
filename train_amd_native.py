import torch
import os
import json
from PIL import Image
from datasets import load_dataset
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, TrainingArguments, Trainer
from peft import LoraConfig, get_peft_model

def main():
    MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
    DATASET_PATH = "./data/processed/wafer_train_ready.json"
    OUTPUT_DIR = "./models/wafer_map_qwen_lora"

    print("=" * 60)
    print("🚀 STARTING NATIVE WAFER MAP VLM FINE-TUNING PIPELINE")
    print(f"Base Model: {MODEL_ID}")
    print(f"Dataset: {DATASET_PATH}")
    print("=" * 60)

    # 1. Load the native Qwen2.5-VL Processor
    processor = AutoProcessor.from_pretrained(MODEL_ID)

    # 2. Load base model layers onto your active device
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID,
        torch_dtype=torch.bfloat16,
        device_map="cuda:0", 
        attn_implementation="sdpa"
    )

    # 3. Enable gradient checkpointing to safeguard VRAM boundaries
    model.gradient_checkpointing_enable()

    # 4. Configure LoRA targeted to Qwen's attention & multi-modal projections
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 5. Load the locally processed wafer dataset
    dataset = load_dataset("json", data_files=DATASET_PATH, split="train")

    # 6. Define a custom data collator for Qwen2.5-VL multi-modal dicts
    def collate_fn(batch):
        texts = []
        images = []
        for sample in batch:
            messages = sample["messages"]
            
            # Extract image paths and open images using PIL
            sample_images = []
            for message in messages:
                for content in message.get("content", []):
                    if content.get("type") == "image":
                        image_path = content.get("image")
                        if os.path.exists(image_path):
                            sample_images.append(Image.open(image_path).convert("RGB"))
            
            images.append(sample_images if sample_images else None)
            
            # Apply chat template to generate text inputs
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False
            )
            texts.append(text)

        # Flatten list of images if needed or pass directly depending on sample structure
        # Filter out empty lists if samples don't have images
        flat_images = [img for sublist in images if sublist for img in sublist]
        
        batch_inputs = processor(
            text=texts,
            images=flat_images if flat_images else None,
            padding=True,
            return_tensors="pt"
        )
        
        # Labels for causal language modeling
        labels = batch_inputs["input_ids"].clone()
        # Mask padding tokens in labels so loss calculation ignores them
        labels[labels == processor.tokenizer.pad_token_id] = -100
        batch_inputs["labels"] = labels
        
        return batch_inputs

    # 7. Standard Training Arguments
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        logging_steps=5,
        num_train_epochs=3,
        bf16=True,
        save_strategy="epoch",
        report_to="none",
        remove_unused_columns=False
    )

    # 8. Initialize standard Trainer with the custom collator
    trainer = Trainer(
        model=model,
        train_dataset=dataset,
        data_collator=collate_fn,
        args=training_args,
    )

    # 9. Execute the compute graph
    print("\n🔥 Commencing training loops on compute blocks...")
    trainer.train()

    # 10. Save the locally baked adapter arrays
    print(f"\n✅ Training complete! Saving custom adapters locally to: {OUTPUT_DIR}")
    trainer.model.save_pretrained(OUTPUT_DIR)
    processor.save_pretrained(OUTPUT_DIR)

if __name__ == "__main__":
    main()