from .model_manager import ModelManager
from .robot_controller import RobotController

class InspectionManager:

    def __init__(self):
        self.model_manager = ModelManager()
        self.robot_controller = RobotController()

    def inspect(self, image, inspection_type="pcb"):
        """
        Generic inspection entry point.
        """

        inspection_type = inspection_type.lower()

        if inspection_type == "pcb":
            return self.inspect_pcb(image)

        elif inspection_type == "wafer":
            return self.inspect_wafer(image)

        else:
            raise ValueError(
                f"Unsupported inspection type: {inspection_type}"
            )

    def inspect_pcb(self, image):
        """
        Performs PCB inspection using
        - Component Detector
        - PCB Defect Detector
        """

        component_detector = self.model_manager.get_model("component")
        pcb_detector = self.model_manager.get_model("pcb")

        component_result = component_detector.detect(image)
        pcb_result = pcb_detector.detect(image)

        components = component_result["detections"]
        pcb_defects = pcb_result["detections"]

        status = "PASS"
        robot_action = "Pick PCB"

        if len(pcb_defects) > 0:
            status = "FAIL"
            robot_action = "Reject PCB"

        # Execute robot action
        self.robot_controller.execute(status)

        return {
            "inspection_type": "PCB",
            "status": status,
            "robot_action": robot_action,
            "components": components,
            "pcb_defects": pcb_defects,
            "annotated": pcb_result["annotated"],
        }

    def inspect_wafer(self, image):
        """
        Performs wafer inspection.
        """

        wafer_detector = self.model_manager.get_model("wafer")

        wafer_result = wafer_detector.detect(image)

        wafer_defects = wafer_result["detections"]

        status = "PASS"
        robot_action = "Pick Wafer"

        if len(wafer_defects) > 0:
            status = "FAIL"
            robot_action = "Reject Wafer"

        # Execute robot action
        self.robot_controller.execute(status)

        return {
            "inspection_type": "Wafer",
            "status": status,
            "robot_action": robot_action,
            "wafer_defects": wafer_defects,
            "annotated": wafer_result["annotated"],
        }

    def summarize(self, result):
        """
        Creates a human-readable summary.
        """

        summary = {
            "Inspection Type": result["inspection_type"],
            "Status": result["status"],
            "Robot Action": result["robot_action"],
        }

        if result["inspection_type"] == "PCB":
            summary["Components"] = len(result["components"])
            summary["PCB Defects"] = len(result["pcb_defects"])

        else:
            summary["Wafer Defects"] = len(result["wafer_defects"])

        return summary
