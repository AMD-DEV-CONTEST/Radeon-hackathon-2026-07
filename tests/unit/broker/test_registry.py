import json
from pathlib import Path

from cortex.broker.registry import OrgRecord, OrgRegistry


def write_registry(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "org_registry.json"
    p.write_text(json.dumps(payload))
    return p


def test_org_record_dataclass_fields():
    rec = OrgRecord(
        did="did:percq:org:soc-alpha",
        pubkey="-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----\n",
        name="SOC Alpha",
        topics=["threat-intel", "apt29"],
    )
    assert rec.did == "did:percq:org:soc-alpha"
    assert rec.pubkey.startswith("-----BEGIN PUBLIC KEY-----")
    assert "apt29" in rec.topics


def test_from_json_file_loads_known_org(tmp_path):
    p = write_registry(
        tmp_path,
        {
            "did:percq:org:soc-alpha": {
                "pubkey": "-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----\n",
                "name": "SOC Alpha",
                "topics": ["threat-intel", "apt29"],
            }
        },
    )
    reg = OrgRegistry.from_json_file(p)
    rec = reg.get("did:percq:org:soc-alpha")
    assert isinstance(rec, OrgRecord)
    assert rec.name == "SOC Alpha"
    assert rec.topics == ["threat-intel", "apt29"]


def test_get_returns_none_for_unknown_org(tmp_path):
    p = write_registry(tmp_path, {})
    reg = OrgRegistry.from_json_file(p)
    assert reg.get("did:percq:org:unknown") is None


def test_from_json_file_handles_empty_topics(tmp_path):
    p = write_registry(
        tmp_path,
        {
            "did:percq:org:soc-beta": {
                "pubkey": "PK",
                "name": "SOC Beta",
            }
        },
    )
    reg = OrgRegistry.from_json_file(p)
    rec = reg.get("did:percq:org:soc-beta")
    assert rec is not None
    assert rec.topics == []
