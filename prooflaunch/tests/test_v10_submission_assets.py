from __future__ import annotations

import base64
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _decoded_pdf_streams(path: Path) -> bytes:
    raw = path.read_bytes()
    decoded = bytearray()
    for match in re.finditer(rb"stream\r?\n", raw):
        end = raw.find(b"endstream", match.end())
        if end < 0:
            continue
        header = raw[max(0, match.start() - 300) : match.start()]
        value = raw[match.end() : end].rstrip(b"\r\n")
        try:
            if b"ASCII85Decode" in header:
                value = base64.a85decode(value, adobe=True)
            if b"FlateDecode" in header:
                value = zlib.decompress(value)
        except (ValueError, zlib.error):
            continue
        decoded.extend(value)
        decoded.extend(b"\n")
    return bytes(decoded)


class SubmissionAssetTests(unittest.TestCase):
    def test_project_pdf_is_seven_page_english_current_and_truth_bounded(self) -> None:
        path = ROOT / "docs/ProofLaunch_Project_Profile.pdf"
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF-"))
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", raw)), 7)
        text = _decoded_pdf_streams(path).decode("latin-1", errors="ignore")
        for phrase in (
            "ProofLaunch", "SYSTEM ARCHITECTURE", "AMD RADEON / ROCm ADAPTATION",
            "827 / 827 passed", "17 / 17 passed", "10 / 10 passed",
            "46 routes / 60 API contracts", "4 / 4 passed", "Active Radeon instance",
            "Not observed", "Final Evidence Seal", "Not sealed",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("111 / 111 passed", text)
        self.assertNotIn("580 / 580 passed", text)
        self.assertNotIn("Single-GPU BF16 LoRA instead of multi-GPU launch", text)

    def test_poster_is_widescreen_single_slide_current_and_truth_bounded(self) -> None:
        path = ROOT / "docs/ProofLaunch_Poster.pptx"
        with zipfile.ZipFile(path) as archive:
            slide_names = [
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ]
            self.assertEqual(len(slide_names), 1)
            presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
            size = presentation.find(
                "{http://schemas.openxmlformats.org/presentationml/2006/main}sldSz"
            )
            self.assertIsNotNone(size)
            assert size is not None
            self.assertAlmostEqual(
                int(size.attrib["cx"]) / int(size.attrib["cy"]), 16 / 9, places=2
            )
            slide = ET.fromstring(archive.read(slide_names[0]))
            text = "\n".join(
                node.text or ""
                for node in slide.iter(
                    "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
                )
            )
        self.assertIn("827/827 product-critical", text)
        self.assertIn("UI 17/17", text)
        self.assertIn("routes 10/10", text)
        self.assertIn("final locks 4/4", text)
        self.assertIn("live Radeon/video/PR remain open", text)
        self.assertIn("FIELD JOURNAL V5", text)


if __name__ == "__main__":
    unittest.main()
