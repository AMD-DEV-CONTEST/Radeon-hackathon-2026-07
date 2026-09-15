from dataclasses import dataclass

@dataclass
class InspectionObject:
    id: str
    category: str
    defect_type: str | None
    status: str

INSPECTION_OBJECTS = {
    "011_banana": InspectionObject(
        id="PCB_001",
        category="PCB",
        defect_type=None,
        status="Pending"
    ),

    "014_lemon": InspectionObject(
        id="CHIP_001",
        category="Semiconductor",
        defect_type="Scratch",
        status="Pending"
    ),

    "018_plum": InspectionObject(
        id="PCB_002",
        category="PCB",
        defect_type="Missing Component",
        status="Pending"
    ),

    "024_bowl": InspectionObject(
        id="INSPECTION_TRAY",
        category="Tray",
        defect_type=None,
        status="Idle"
    ),
}
