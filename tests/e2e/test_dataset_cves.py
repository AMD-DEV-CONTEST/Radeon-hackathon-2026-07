import json
import re
from pathlib import Path

CVES_PATH = Path("scenarios/soc_consortium/dataset/cves.jsonl")
MITRE_RE = re.compile(r"T\d{4}(\.\d{3})?")
REQUIRED_KEYS = {"cve_id", "description", "attack_id", "actor", "severity", "published_year"}


def test_cves_jsonl_valid():
    assert CVES_PATH.exists(), f"missing {CVES_PATH}"
    lines = [ln for ln in CVES_PATH.read_text().splitlines() if ln.strip()]
    assert len(lines) == 10, f"expected 10 CVE records, got {len(lines)}"
    seen_ids = set()
    valid_actors = {"APT28", "APT29", "Lockbit", "FIN7", "MuddyWater", "unknown"}
    for ln in lines:
        rec = json.loads(ln)
        assert REQUIRED_KEYS.issubset(rec), f"missing keys in {rec}"
        assert re.match(r"^CVE-202\d-\d{4,}$", rec["cve_id"]), rec["cve_id"]
        assert rec["cve_id"] not in seen_ids
        seen_ids.add(rec["cve_id"])
        assert MITRE_RE.fullmatch(rec["attack_id"]), rec["attack_id"]
        assert rec["actor"] in valid_actors, rec["actor"]
        assert rec["severity"] in {"low", "medium", "high", "critical"}
        assert 2018 <= rec["published_year"] <= 2026
        assert 32 <= len(rec["description"]) <= 400
