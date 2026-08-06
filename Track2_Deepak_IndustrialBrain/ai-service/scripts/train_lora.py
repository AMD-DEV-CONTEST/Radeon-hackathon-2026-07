import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig
from transformers.trainer_utils import get_last_checkpoint
import os

# Configuration for 6GB VRAM (RTX 3050)
import os
local_model_path = os.path.join(os.path.dirname(__file__), "..", "local_model")
MODEL_NAME = local_model_path if os.path.exists(local_model_path) and os.listdir(local_model_path) else "unsloth/llama-3-8b-Instruct-bnb-4bit"
# Alternatively, you can use "unsloth/llama-3-8b-Instruct-bnb-4bit" which is pre-quantized and easier to load.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUTPUT_DIR = os.path.join(ROOT_DIR, "model-lora-output")

def train():
    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    print("Configuring 4-bit quantization for 6GB VRAM...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
        llm_int8_enable_fp32_cpu_offload=True
    )

    print("Loading base model...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=bnb_config,
        device_map={"": 0},
        trust_remote_code=True
    )
    
    model = prepare_model_for_kbit_training(model)

    print("Setting up LoRA configuration...")
    peft_config = LoraConfig(
        r=8, 
        lora_alpha=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )

    print("Loading and mixing datasets...")
    import json
    import pandas as pd
    from datasets import Dataset, load_from_disk

    processed_dataset_path = os.path.join(os.path.dirname(__file__), "..", "training_data", "processed_dataset")
    if os.path.exists(processed_dataset_path):
        print("Loading pre-processed dataset from cache...")
        dataset = load_from_disk(processed_dataset_path)
    else:
        combined_data = []

        # 1. Load Alpaca
        alpaca_path = os.path.join(os.path.dirname(__file__), "..", "training_data", "alpaca_data_cleaned.json")
        if os.path.exists(alpaca_path):
            with open(alpaca_path, "r", encoding="utf-8") as f:
                alpaca_data = json.load(f)
                for row in alpaca_data:
                    combined_data.append({
                        "instruction": row.get("instruction", ""),
                        "context": row.get("input", ""),
                        "response": row.get("output", "")
                    })
            print(f"Loaded {len(alpaca_data)} examples from Alpaca.")

        # 2. Load MechQA
        mechqa_path = os.path.join(os.path.dirname(__file__), "..", "training_data", "train-00000-of-00001.parquet")
        if os.path.exists(mechqa_path):
            df = pd.read_parquet(mechqa_path)
            for _, row in df.iterrows():
                answers = row.get("answers", {})
                answer_text = answers.get("text", [""])[0] if isinstance(answers, dict) and "text" in answers and len(answers["text"]) > 0 else str(answers)
                combined_data.append({
                    "instruction": row.get("question", ""),
                    "context": row.get("context", ""),
                    "response": answer_text
                })
            print(f"Loaded {len(df)} examples from MechQA.")

        dataset = Dataset.from_list(combined_data).shuffle(seed=42)

        def format_prompt(example):
            context_block = f"\n### Evidence:\n{example['context']}\n" if example['context'] else ""
            prompt = f"""You are an industrial knowledge copilot. Answer accurately and use evidence if provided.

### Question:
{example['instruction']}
{context_block}
### Answer:
{example['response']}"""
            return {"text": prompt}

        dataset = dataset.map(format_prompt)
        print("Saving processed dataset to cache for faster restarts...")
        dataset.save_to_disk(processed_dataset_path)

    print("Configuring training arguments...")
    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        dataset_text_field="text",
        per_device_train_batch_size=1, # Keep batch size 1 for 6GB VRAM
        gradient_accumulation_steps=4, # Accumulate to simulate larger batch size
        optim="paged_adamw_32bit",
        save_steps=100, # Save checkpoint every 100 steps
        save_total_limit=5, # Keep 5 most recent checkpoints to save disk space
        logging_steps=10,
        learning_rate=2e-4,
        weight_decay=0.001,
        fp16=False,
        bf16=True, # RTX 3050 supports bfloat16 natively, prevents scaler bugs
        max_grad_norm=0.3,
        max_steps=100000, # Run as much as possible (100,000 steps) until Ctrl+C
        warmup_steps=100,
        lr_scheduler_type="constant"
    )

    print("Starting SFT Trainer...")
    last_checkpoint = get_last_checkpoint(OUTPUT_DIR) if os.path.exists(OUTPUT_DIR) else None
    if last_checkpoint is not None:
        print(f"Resuming training from checkpoint: {last_checkpoint}")
    
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        processing_class=tokenizer,
        args=training_args,
    )

    try:
        trainer.train(resume_from_checkpoint=last_checkpoint)
    except KeyboardInterrupt:
        print("\n[Ctrl+C] Training paused by user! Saving exact progress to a resumable checkpoint...")
        try:
            trainer._save_checkpoint(trainer.model, trial=None)
            print(f"Resumable checkpoint saved at step {trainer.state.global_step}!")
        except Exception as e:
            print(f"Note: Could not save optimizer state ({e}), saving weights...")
        print(f"Updating latest LoRA adapter weights in {OUTPUT_DIR}...")
        trainer.model.save_pretrained(OUTPUT_DIR)
        tokenizer.save_pretrained(OUTPUT_DIR)
        print("Checkpoint and latest model weights saved successfully! You can safely resume training later.")
        return
    
    print(f"Saving fine-tuned LoRA adapter to {OUTPUT_DIR}...")
    trainer.model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print("Training complete!")

if __name__ == "__main__":
    train()
