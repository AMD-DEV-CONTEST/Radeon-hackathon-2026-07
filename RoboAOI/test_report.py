from roboaoi.report_generator import ReportGenerator

report = ReportGenerator()

report.generate(
    image_name="test.jpg",
    components=[
        {"class": "IC", "confidence": 0.98},
        {"class": "Capacitor", "confidence": 0.95},
    ],
    pcb_defects=[
        {"class": "open", "confidence": 0.91},
    ],
    wafer_defects=[],
    status="FAIL",
)
