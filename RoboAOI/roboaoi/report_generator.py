import json
import csv
from pathlib import Path
from datetime import datetime


class ReportGenerator:

    def __init__(self, output_dir="reports"):

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def generate(
        self,
        image_name,
        components,
        pcb_defects,
        wafer_defects,
        status,
    ):

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        report = {
            "inspection_id": timestamp,
            "image": image_name,
            "status": status,
            "components": components,
            "pcb_defects": pcb_defects,
            "wafer_defects": wafer_defects,
            "time": str(datetime.now()),
        }

        json_file = self.output_dir / f"{timestamp}.json"

        with open(json_file, "w") as f:
            json.dump(report, f, indent=4)

        csv_file = self.output_dir / f"{timestamp}.csv"

        with open(csv_file, "w", newline="") as f:

            writer = csv.writer(f)

            writer.writerow(["Field", "Value"])

            writer.writerow(["Inspection ID", timestamp])
            writer.writerow(["Image", image_name])
            writer.writerow(["Status", status])

            writer.writerow([""])

            writer.writerow(["Components", len(components)])

            for item in components:
                writer.writerow(
                    [
                        item["class"],
                        f'{item["confidence"]:.2f}',
                    ]
                )

            writer.writerow([""])

            writer.writerow(["PCB Defects", len(pcb_defects)])

            for item in pcb_defects:
                writer.writerow(
                    [
                        item["class"],
                        f'{item["confidence"]:.2f}',
                    ]
                )

            writer.writerow([""])

            writer.writerow(["Wafer Defects", len(wafer_defects)])

            for item in wafer_defects:
                writer.writerow(
                    [
                        item["class"],
                        f'{item["confidence"]:.2f}',
                    ]
                )

        print("\n==============================")
        print("RoboAOI Inspection Report")
        print("==============================")
        print("Inspection :", timestamp)
        print("Image      :", image_name)
        print("Status     :", status)
        print("Components :", len(components))
        print("PCB Defects:", len(pcb_defects))
        print("Wafer Defects:", len(wafer_defects))
        print("==============================")

        return report
