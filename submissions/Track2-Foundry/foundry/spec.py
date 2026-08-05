"""TaskSpec: the task definition as data.

A spec is what the agent drafts from conversation and what every
pipeline stage reads. One spec = one small model being manufactured.
MVP scope: single free-text input field, enum output fields (objective
eval by exact match); string output fields allowed, scored exact-match.
"""

import json
from pathlib import Path

REQUIRED_KEYS = [
    "name", "description", "example_noun", "input_field",
    "seed_docs", "output_schema", "balance_field",
]
DEFAULT_FACETS = {
    "personas": ["an ordinary user of the product"],
    "tones": ["neutral"],
    "lengths": ["2-4 sentences"],
    "wrinkles": ["no wrinkle"],
    "situations": {},
}


def _normalize_length(val) -> list:
    """Agent-drafted specs arrive in whatever shape the model chose:
    [lo, hi], {"min": lo, "max": hi}, string numbers. Normalize hard."""
    if val is None:
        return [40, 2000]
    if isinstance(val, dict):
        val = [val.get("min", 40), val.get("max", 2000)]
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        raise ValueError(f"input_length must be [min, max] chars, got: {val!r}")
    lo, hi = int(val[0]), int(val[1])
    if not (0 < lo < hi):
        raise ValueError(f"input_length needs 0 < min < max, got: [{lo}, {hi}]")
    return [lo, hi]


class TaskSpec:
    def __init__(self, data: dict):
        for key in REQUIRED_KEYS:
            if key not in data:
                raise ValueError(f"task spec missing required key: {key}")
        if not data["output_schema"]:
            raise ValueError("output_schema must have at least one field")
        for field, fs in data["output_schema"].items():
            if fs.get("type") not in ("enum", "string"):
                raise ValueError(f"output field {field}: type must be enum or string")
            if fs["type"] == "enum" and not fs.get("values"):
                raise ValueError(f"output field {field}: enum needs non-empty values")
        if data["balance_field"] not in data["output_schema"]:
            raise ValueError("balance_field must be an output_schema field")
        if data["output_schema"][data["balance_field"]]["type"] != "enum":
            raise ValueError("balance_field must be an enum field")

        self.raw = data
        self.name: str = data["name"]
        self.description: str = data["description"]
        self.example_noun: str = data["example_noun"]
        self.input_field: str = data["input_field"]
        self.input_length: list = _normalize_length(data.get("input_length"))
        self.seed_docs: list[str] = data["seed_docs"]
        self.output_schema: dict = data["output_schema"]
        self.balance_field: str = data["balance_field"]
        self.balance_values: list = data["output_schema"][data["balance_field"]]["values"]
        self.datagen_guidance: str = data.get("datagen_guidance", "")
        self.facets: dict = {**DEFAULT_FACETS, **data.get("facets", {})}

    @classmethod
    def load(cls, path: str | Path) -> "TaskSpec":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path):
        Path(path).write_text(json.dumps(self.raw, indent=2), encoding="utf-8")

    def enum_fields(self) -> dict:
        return {f: fs["values"] for f, fs in self.output_schema.items()
                if fs["type"] == "enum"}

    def output_fields(self) -> list[str]:
        return list(self.output_schema)

    def schema_line(self) -> str:
        """One-line JSON shape description for prompts."""
        parts = []
        for field, fs in self.output_schema.items():
            if fs["type"] == "enum":
                parts.append(f'"{field}": <one of {", ".join(fs["values"])}>')
            else:
                parts.append(f'"{field}": <string>')
        return "{" + ", ".join(parts) + "}"
