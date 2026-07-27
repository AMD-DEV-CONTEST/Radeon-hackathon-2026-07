import json
import os
import random

def convert_wafer_to_vlm_format():
    raw_dir = "./data/raw/Wafer-Defect-Detection-1"
    processed_dir = "./data/processed"
    os.makedirs(processed_dir, exist_ok=True)

    # Since the Roboflow folder export organizes data into split folders containing class subfolders
    splits = ["train", "valid", "test"]
    
    for split in splits:
        split_dir = os.path.join(raw_dir, split)
        if not os.path.exists(split_dir):
            print(f"⚠️ Split directory not found: {split_dir}, skipping...")
            continue

        print(f"📖 Processing '{split}' split from folder structure...")
        vlm_dataset = []

        # Iterate through class folders inside the split directory
        for class_name in os.listdir(split_dir):
            class_path = os.path.join(split_dir, class_name)
            if os.path.isdir(class_path):
                for img_name in os.listdir(class_path):
                    if img_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                        full_img_path = os.path.abspath(os.path.join(class_path, img_name))

                        # Build structured payload for the wafer defect classification
                        ground_truth_payload = {
                            "wafer_defect_analysis": {
                                "defect_classification": class_name,
                                "status": "verified"
                            }
                        }

                        # Native Qwen2.5-VL conversation format
                        conversation_entry = {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "image", "image": full_img_path},
                                        {"type": "text", "text": "Analyze this semiconductor wafer map and identify its defect pattern classification."}
                                    ]
                                },
                                {
                                    "role": "assistant",
                                    "content": [
                                        {"type": "text", "text": json.dumps(ground_truth_payload)}
                                    ]
                                }
                            ]
                        }
                        vlm_dataset.append(conversation_entry)

        # Shuffle and save individual split manifests
        random.shuffle(vlm_dataset)
        output_file = os.path.join(processed_dir, f"wafer_{split}_ready.json")
        with open(output_file, "w") as out_f:
            json.dump(vlm_dataset, out_f, indent=2)

        print(f"🎯 Successfully generated {len(vlm_dataset)} records for '{split}' in: {output_file}!")

if __name__ == "__main__":
    convert_wafer_to_vlm_format()