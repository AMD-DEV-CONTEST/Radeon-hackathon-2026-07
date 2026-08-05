from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_IMAGE = PROJECT_ROOT / "data/smoke/single/synthetic_intersection.png"


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI optional extra is not installed")
class CaseApiTests(unittest.TestCase):
    def test_create_upload_and_read_case(self) -> None:
        from fastapi.testclient import TestClient

        from app.api.cases import create_app

        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory)))
            created = client.post("/cases", json={"case_id": "CASE-API-001"})
            self.assertEqual(created.status_code, 200)
            uploaded = client.post(
                "/cases/CASE-API-001/sources",
                params={
                    "filename": "现场 图.png",
                    "role": "scene_photo",
                },
                content=SMOKE_IMAGE.read_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            self.assertEqual(uploaded.json()["original_name"], "现场 图.png")
            role_update = client.patch(
                f"/cases/CASE-API-001/sources/{uploaded.json()['source_id']}/role",
                params={"role": "vehicle_document"},
            )
            self.assertEqual(role_update.status_code, 200, role_update.text)
            self.assertEqual(role_update.json()["role"], "vehicle_document")
            case = client.get("/cases/CASE-API-001")
            self.assertEqual(case.status_code, 200)
            self.assertEqual(len(case.json()["sources"]), 1)
            self.assertIn("道路交通事故认定书（如已出具）", case.json()["intake"]["missing_materials"])


if __name__ == "__main__":
    unittest.main()
