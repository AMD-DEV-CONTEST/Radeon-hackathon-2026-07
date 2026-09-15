from roboaoi.yolo_detector import YOLODetector

models = [
    "pcb_detector.pt",
    "component_detector.pt",
    "wafer_detector.pt",
]

for model in models:
    detector = YOLODetector(model)
    print(f"✓ {model} OK")

print("\nAll models loaded successfully!")
