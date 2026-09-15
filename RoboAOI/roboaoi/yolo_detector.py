from pathlib import Path

from ultralytics import YOLO


class YOLODetector:

    def __init__(self, model_name: str):

        model_path = Path(__file__).parent / "models" / model_name

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found: {model_path}"
            )

        print(f"Loading {model_name}...")

        self.model = YOLO(str(model_path))

        print(f"{model_name} loaded.")

    def detect(self, image):

        results = self.model.predict(
            source=image,
            verbose=False,
        )

        detections = []

        for result in results:

            for box in result.boxes:

                detections.append(
                    {
                        "class_id": int(box.cls.item()),
                        "class": self.model.names[int(box.cls.item())],
                        "confidence": float(box.conf.item()),
                        "bbox": box.xyxy[0].tolist(),
                    }
                )

        annotated = results[0].plot()

        return {
            "detections": detections,
            "annotated": annotated,
            "raw": results,
        }

    def predict(self, image):
        """
        Alias for detect()
        """
        return self.detect(image)
