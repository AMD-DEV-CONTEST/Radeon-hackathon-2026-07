"""Command-line compiler for the opt-in NuclidePath PHREEQC chemistry slice."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .phreeqc_scenario import ScenarioCompileError, compile_phreeqc_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile a declared NuclidePath multicomponent Cs chemistry scenario to PHREEQC input"
    )
    parser.add_argument("scenario", type=Path, help="JSON scenario containing an opt-in phreeqc block")
    parser.add_argument("--output", type=Path, required=True, help="output directory for input.pqi and metadata.json")
    parser.add_argument("--cells", type=int, help="override the declared PHREEQC cell count")
    parser.add_argument("--max-shifts", type=int, help="explicit shift cap; must cover all requested times")
    args = parser.parse_args(argv)
    try:
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        compiled = compile_phreeqc_scenario(
            scenario, cells=args.cells, max_shifts=args.max_shifts
        )
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "input.pqi").write_text(compiled.input_text, encoding="utf-8")
        metadata = compiled.canonical_payload()
        (args.output / "metadata.json").write_text(
            json.dumps(metadata, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, ScenarioCompileError) as exc:
        print(f"nuclear-phreeqc-scenario: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"input": str(args.output / "input.pqi"), "metadata": str(args.output / "metadata.json"),
                      "input_sha256": metadata["input_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

