from defect_detector import DefectDetector

detector = DefectDetector()

detections = detector.detect(None)

print("\n========== DETECTIONS ==========")

for d in detections:
    print(f"Defect      : {d.name}")
    print(f"Confidence  : {d.confidence:.2f}")
    print(f"Location    : ({d.x:.2f}, {d.y:.2f})")
    print("-------------------------------")
