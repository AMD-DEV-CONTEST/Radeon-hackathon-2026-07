from pathlib import Path
import cv2

from roboaoi.inspection_manager import InspectionManager

manager = InspectionManager()

image_path = "sample_images/test.jpg"

if not Path(image_path).exists():
    print(f"Image not found: {image_path}")
    print("Copy any PCB image into sample_images/test.jpg")
    exit()

image = cv2.imread(image_path)

result = manager.inspect(image)

print("\n========== RESULT ==========")
print("Decision :", result["decision"])
print("Components :", len(result["components"]))
print("PCB Defects :", len(result["pcb_defects"]))
print("Wafer Defects :", len(result["wafer_defects"]))
