import cv2

from roboaoi.inspection_manager import InspectionManager

manager = InspectionManager()

image = cv2.imread("sample_images/test.jpg")

result = manager.inspect(image, inspection_type="wafer")

print("\n========== RESULT ==========")
print("Inspection Type :", result["inspection_type"])
print("Status          :", result["status"])
print("Defects Found   :", len(result["wafer_defects"]))

for defect in result["wafer_defects"]:
    print(f'- {defect["class"]} ({defect["confidence"]:.2f})')
