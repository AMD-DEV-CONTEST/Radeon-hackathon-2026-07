from .yolo_detector import YOLODetector


class ModelManager:
    def __init__(self):
        print("\nLoading RoboAOI models...")

        self.models = {
            "pcb": YOLODetector("pcb_detector.pt"),
            "component": YOLODetector("component_detector.pt"),
            "wafer": YOLODetector("wafer_detector.pt"),
        }

        print("\nAll RoboAOI models loaded successfully!")

    def get_model(self, model_name: str):
        if model_name not in self.models:
            raise ValueError(f"Unknown model: {model_name}")

        return self.models[model_name]
