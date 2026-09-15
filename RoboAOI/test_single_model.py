from ultralytics import YOLO

# Load your trained PCB defect model
model = YOLO("roboaoi/models/wafer_detector.pt")
# Run inference on one test image
results = model.predict(
    source="sample_images/test.jpg",
    save=True,
    conf=0.25
)

print("\nInference completed successfully!")

for result in results:
    print(f"Detected {len(result.boxes)} objects")
