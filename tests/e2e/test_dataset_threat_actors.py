import json
import re
from pathlib import Path

ACTORS_PATH = Path("scenarios/soc_consortium/dataset/threat_actors.json")
TECH_PATH = Path("scenarios/soc_consortium/dataset/attack_techniques.json")
MITRE_RE = re.compile(r"^T\d{4}(\.\d{3})?$")


def test_threat_actors_shape():
    actors = json.loads(ACTORS_PATH.read_text())
    assert isinstance(actors, list) and len(actors) == 6, len(actors)
    seen = set()
    valid_techs = {e["technique_id"] for e in json.loads(TECH_PATH.read_text())}
    for a in actors:
        assert {"actor", "country_attribution", "common_tactics"}.issubset(a), a
        assert a["actor"] not in seen
        seen.add(a["actor"])
        assert isinstance(a["country_attribution"], str) and len(a["country_attribution"]) >= 2
        assert isinstance(a["common_tactics"], list) and 1 <= len(a["common_tactics"]) <= 5
        for t in a["common_tactics"]:
            assert MITRE_RE.match(t), t
            assert t in valid_techs, f"actor {a['actor']} references unknown technique {t}"
    assert "unknown" in seen, "must include an 'unknown' bucket for unattributed activity"
