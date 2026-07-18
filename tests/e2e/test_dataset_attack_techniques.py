import json
import re
from pathlib import Path

PATH = Path("scenarios/soc_consortium/dataset/attack_techniques.json")
TACTICS = [
    "Reconnaissance", "Resource Development", "Initial Access", "Execution",
    "Persistence", "Privilege Escalation", "Defense Evasion", "Credential Access",
    "Discovery", "Lateral Movement", "Collection", "Command and Control",
    "Exfiltration", "Impact",
]


def test_attack_techniques_shape():
    data = json.loads(PATH.read_text())
    assert isinstance(data, list)
    assert len(data) == 210, len(data)
    tactic_counts = {}
    for entry in data:
        assert {"tactic", "technique_id", "name"}.issubset(entry), entry
        assert entry["tactic"] in TACTICS, entry["tactic"]
        assert re.match(r"^T\d{4}(\.\d{3})?$", entry["technique_id"]), entry["technique_id"]
        assert isinstance(entry["name"], str) and entry["name"]
        tactic_counts[entry["tactic"]] = tactic_counts.get(entry["tactic"], 0) + 1
    assert set(tactic_counts) == set(TACTICS)
    for t, c in tactic_counts.items():
        assert 10 <= c <= 20, (t, c)
