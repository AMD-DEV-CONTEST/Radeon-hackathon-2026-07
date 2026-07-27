import torch
import os
import json
import csv
import glob
import re
from datetime import datetime, timedelta
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from peft import PeftModel
from PIL import Image
from tqdm import tqdm

# --- STRICT WORKSPACE PATH ALIGNMENT FOR WAFER CLASSIFICATION ---
BASE_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"
ADAPTER_DIR = "./models/wafer_map_qwen_lora"
DATASET_DIR = "./data/raw/Wafer-Defect-Detection-1/test" 

LEDGER_JSON_PATH = "wafer_batch_inference_summary.json"
LEDGER_CSV_PATH = "wafer_defect_summary_log.csv"

def init_ledgers():
    """Ensures storage layers exist before writing records, appending gracefully."""
    # 1. Initialize JSON ledger as an empty array if missing
    if os.path.exists(LEDGER_JSON_PATH):
        print(f"🗄️ Existing JSON summary ledger verified at '{LEDGER_JSON_PATH}'. Preserving history.")
    else:
        with open(LEDGER_JSON_PATH, "w") as f:
            json.dump([], f)
        print(f"📝 Created new JSON summary ledger at '{LEDGER_JSON_PATH}'.")
            
    # 2. Initialize CSV alert ledger with headers if missing
    if os.path.exists(LEDGER_CSV_PATH):
        print(f"📊 Existing CSV log verified at '{LEDGER_CSV_PATH}'. New records will append.")
    else:
        with open(LEDGER_CSV_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Asset_Name", "Defect_Classification", "Status"
            ])
        print(f"📝 Created new CSV log at '{LEDGER_CSV_PATH}'.")

def main():
    init_ledgers()
    
    if not os.path.exists(DATASET_DIR):
        print(f"❌ Error: Target dataset directory '{DATASET_DIR}' not found.")
        print("💡 Make sure you have run your data download/setup script on the AMD instance first.")
        return

    # Gather and sort all image assets recursively in the target test path
    valid_extensions = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    image_files = []
    for ext in valid_extensions:
        image_files.extend(glob.glob(os.path.join(DATASET_DIR, "**", ext), recursive=True))
    image_files.sort()

    total_files = len(image_files)
    if total_files == 0:
        print(f"⚠️ No matching image assets found in {DATASET_DIR}")
        return

    print(f"📦 Found {total_files} wafer map test images for batch processing.")
    print("📡 Loading local fine-tuned model and processor layers onto AMD/Radeon hardware...")
    
    # Load base weights natively using standard PyTorch ROCm setup
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        BASE_MODEL, 
        torch_dtype=torch.bfloat16, 
        attn_implementation="sdpa"
    )
    # Merge local wafer LoRA adapter layers
    model = PeftModel.from_pretrained(model, ADAPTER_DIR)
    model = model.to("cuda")
    
    processor = AutoProcessor.from_pretrained(BASE_MODEL)
    model.eval()
    
    base_time = datetime.now()
    print(f"\n🔥 Commencing local Wafer VLM batch inference loops...")
    print("=" * 80)

    with torch.no_grad():
        for idx, img_path in enumerate(tqdm(image_files, desc="Batch Wafer Auditing"), start=1):
            try:
                filename = os.path.basename(img_path)
                frame_timestamp = (base_time + timedelta(seconds=idx * 10)).strftime("%Y-%m-%d %H:%M:%S")
                raw_image = Image.open(img_path).convert("RGB")
                
                # Target prompt matching your wafer defect classification training schema
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": img_path},
                            {"type": "text", "text": "Analyze this semiconductor wafer map and identify its defect pattern classification."}
                        ]
                    }
                ]
                
                text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = processor(text=[text], images=[raw_image], padding=True, return_tensors="pt").to("cuda")
                
                generated_ids = model.generate(
                    **inputs, 
                    max_new_tokens=128,
                    repetition_penalty=1.2, 
                    pad_token_id=processor.tokenizer.pad_token_id,
                    eos_token_id=processor.tokenizer.eos_token_id
                )
                generated_ids_trimmed = [out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)]
                output_text = processor.batch_decode(generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                
                # --- RUGGED JSON CLEANING AND REPAIR LAYER ---
                cleaned_json_string = output_text.strip()
                
                if cleaned_json_string.startswith("```json"):
                    cleaned_json_string = cleaned_json_string.split("```json")[1].split("```")[0].strip()
                elif cleaned_json_string.startswith("```"):
                    cleaned_json_string = cleaned_json_string.split("```")[1].split("```")[0].strip()
                
                cleaned_json_string = re.sub(r'//.*$', '', cleaned_json_string, flags=re.MULTILINE)
                
                if cleaned_json_string.startswith("{") and not cleaned_json_string.endswith("}"):
                    open_braces = cleaned_json_string.count("{")
                    close_braces = cleaned_json_string.count("}")
                    if open_braces > close_braces:
                        cleaned_json_string += "}" * (open_braces - close_braces)

                try:
                    payload = json.loads(cleaned_json_string)
                except json.JSONDecodeError:
                    payload = {"raw_output": output_text.strip()}

                # Extract defect classification safely
                defect_class = "Unknown"
                status = "unverified"
                if isinstance(payload, dict):
                    analysis_block = payload.get("wafer_defect_analysis", {})
                    if isinstance(analysis_block, dict):
                        defect_class = analysis_block.get("defect_classification", "Unknown")
                        status = analysis_block.get("status", "unverified")

                # Construct ledger entry for HF Spaces dashboard
                ledger_entry = {
                    "timestamp": frame_timestamp,
                    "file_name": filename,
                    "image_path": img_path,
                    "prediction": payload,
                    "summary_metrics": {
                        "defect_classification": defect_class,
                        "status": status
                    }
                }

                # Transactional Append into JSON ledger file
                try:
                    with open(LEDGER_JSON_PATH, "r+") as f:
                        data = json.load(f)
                        data.append(ledger_entry)
                        f.seek(0)
                        json.dump(data, f, indent=2)
                        f.truncate()
                except Exception as e:
                    print(f"  ⚠️ Error writing to JSON summary volume: {str(e)}")

                # Append to CSV flat log
                try:
                    with open(LEDGER_CSV_PATH, "a", newline="") as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            frame_timestamp,
                            filename,
                            defect_class,
                            status
                        ])
                except Exception as e:
                    print(f"  ⚠️ Error writing to CSV log: {str(e)}")

            except Exception as e:
                print(f"\n⚠️ Unexpected error processing image asset {img_path}: {str(e)}")
                continue

    print(f"\n✅ Batch Wafer Processing Phase Complete!")
    print(f" ➡️ JSON Summary Ledger saved to: {LEDGER_JSON_PATH} (Ready for Hugging Face Spaces)")
    print(f" ➡️ CSV Log saved to: {LEDGER_CSV_PATH}")

if __name__ == "__main__":
    main()