#!/usr/bin/env python3
"""Split a PPTX into one-slide PPTX files for visual QA using only stdlib."""

from __future__ import annotations

import argparse
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import zipfile

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")
ET.register_namespace("p", P_NS)
ET.register_namespace("r", R_NS)


def split(source: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        presentation_bytes = archive.read("ppt/presentation.xml")
        presentation = ET.fromstring(presentation_bytes)
        slide_list = presentation.find(f"{{{P_NS}}}sldIdLst")
        if slide_list is None:
            raise ValueError("PPTX has no slide list")
        slide_ids = list(slide_list)
        rendered: list[Path] = []
        for index, selected in enumerate(slide_ids, start=1):
            root = ET.fromstring(presentation_bytes)
            current_list = root.find(f"{{{P_NS}}}sldIdLst")
            assert current_list is not None
            for candidate in list(current_list):
                if candidate.attrib.get("id") != selected.attrib.get("id"):
                    current_list.remove(candidate)
            payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            destination = output / f"slide-{index:02d}.pptx"
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as target:
                for info in archive.infolist():
                    data = payload if info.filename == "ppt/presentation.xml" else archive.read(info.filename)
                    target.writestr(info.filename, data, compress_type=zipfile.ZIP_DEFLATED)
            rendered.append(destination)
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for item in split(args.source, args.output):
        print(item)


if __name__ == "__main__":
    main()
