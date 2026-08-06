import json
import unittest
from pathlib import Path

from incident_commander import Incident, IncidentAnalyzer
from incident_commander.retrieval import rank_evidence


SAMPLE = Path(__file__).parent.parent / "samples" / "checkout-latency.json"


def load_incident() -> Incident:
    return Incident.from_dict(json.loads(SAMPLE.read_text(encoding="utf-8")))


class AnalyzerTests(unittest.TestCase):
    def test_sample_ranks_deployment_and_database_hypotheses(self) -> None:
        report = IncidentAnalyzer().analyze(load_incident())
        titles = {hypothesis.title for hypothesis in report.hypotheses}
        self.assertIn("Deployment regression", titles)
        self.assertIn("Database saturation or contention", titles)
        self.assertEqual(report.metadata["evidence_count"], 5)
        self.assertGreaterEqual(report.metadata["analysis_ms"], 0)

    def test_every_hypothesis_is_cited_and_every_action_has_safety(self) -> None:
        report = IncidentAnalyzer().analyze(load_incident())
        known_ids = {item.id for item in report.incident.evidence}
        self.assertTrue(all(hypothesis.evidence_ids for hypothesis in report.hypotheses))
        self.assertTrue(all(set(hypothesis.evidence_ids) <= known_ids for hypothesis in report.hypotheses))
        self.assertTrue(all(action.safety for action in report.actions))

    def test_uncertainties_do_not_contradict_sample_evidence(self) -> None:
        report = IncidentAnalyzer().analyze(load_incident())
        self.assertNotIn("No explicit deployment or change record was supplied.", report.uncertainties)
        self.assertNotIn("No concrete error signature was supplied.", report.uncertainties)
        self.assertIn("Downstream dependency health has not been established.", report.uncertainties)

    def test_retrieval_prioritizes_matching_evidence(self) -> None:
        ranked = rank_evidence("database connection pool", load_incident().evidence, limit=2)
        self.assertEqual(ranked[0].id, "EV-003")

    def test_required_fields(self) -> None:
        for field in ("title", "summary"):
            with self.subTest(field=field):
                payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
                payload[field] = ""
                with self.assertRaisesRegex(ValueError, f"{field} is required"):
                    Incident.from_dict(payload)

    def test_requires_evidence(self) -> None:
        payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
        payload["evidence"] = []
        with self.assertRaisesRegex(ValueError, "at least one evidence"):
            Incident.from_dict(payload)

    def test_rejects_non_object_and_duplicate_evidence(self) -> None:
        payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
        payload["evidence"] = ["not-an-object"]
        with self.assertRaisesRegex(ValueError, "must be an object"):
            Incident.from_dict(payload)

        payload["evidence"] = [
            {"id": "duplicate", "content": "first"},
            {"id": "duplicate", "content": "second"},
        ]
        with self.assertRaisesRegex(ValueError, "unique"):
            Incident.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
