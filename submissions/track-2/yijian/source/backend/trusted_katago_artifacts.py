# -*- coding: utf-8 -*-
"""KataGo 服务端分析制品的受信登记与不可变导出边界。

这个模块不判断棋理，只做三件事：
1. 把服务端 KataGo 返回投影成严格的规范制品；
2. 把制品登记到服务端 SQLite，不允许同 ID 覆写；
3. 导出按整文件 SHA-256 锁定的 JSONL 快照，供离线训练编译器只读。

训练单元自己声明的 JSON/哈希不是信任根。信任根是运行编译器时显式
选择、并且按整文件 SHA-256 锁定的服务端快照。
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ARTIFACT_SCHEMA = "gomentor-trusted-katago-analysis-v1"
REGISTRY_ENTRY_SCHEMA = "gomentor-trusted-katago-registry-entry-v1"
REGISTRY_WORKFLOW = "katago-analysis-registration-v1"
PRODUCER_SERVICE = "gomentor-backend"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GTP_COORD_RE = re.compile(r"^(?:PASS|[A-HJ-T](?:[1-9]|1[0-9]))$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class RegistryError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"制品无法规范化为 JSON：{exc}") from exc


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RegistryError(message)


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{label}必须是对象")
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _require(not missing, f"{label}缺少字段：{', '.join(missing)}")
    _require(not extra, f"{label}含未受信字段：{', '.join(extra)}")
    return value


def _sha(value: Any, label: str) -> str:
    normalized = str(value or "").lower()
    _require(bool(SHA256_RE.fullmatch(normalized)), f"{label}必须是有效 SHA-256")
    return normalized


def _positive_int(value: Any, label: str, minimum: int = 1) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
        f"{label}必须是不小于 {minimum} 的整数",
    )
    return value


def _finite(value: Any, label: str) -> float | int:
    _require(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value)),
        f"{label}必须是有限数值",
    )
    return value


def _coord(value: Any, board_size: int, label: str) -> str:
    coord = str(value or "").strip().upper()
    _require(bool(GTP_COORD_RE.fullmatch(coord)), f"{label}不是有效 GTP 坐标")
    if coord != "PASS":
        column = "ABCDEFGHJKLMNOPQRST".index(coord[0]) + 1
        row = int(coord[1:])
        _require(column <= board_size and row <= board_size, f"{label}超出棋盘")
    return coord


def canonicalize_artifact(value: Any) -> dict[str, Any]:
    """返回可参与哈希的唯一规范投影；多余字段一律拒绝。"""
    artifact = _exact_keys(
        value,
        {
            "schemaVersion",
            "source",
            "demo",
            "engine",
            "model",
            "config",
            "rules",
            "position",
            "subjectColor",
            "valuePerspective",
            "visits",
            "bestMove",
            "candidates",
        },
        "artifact",
    )
    _require(artifact["schemaVersion"] == ARTIFACT_SCHEMA, "artifact.schemaVersion错误")
    _require(artifact["source"] == "katago", "artifact.source必须是katago")
    _require(artifact["demo"] is False, "Mock/演示分析不能登记为受信制品")

    engine = _exact_keys(
        artifact["engine"], {"name", "version", "backend", "binarySha256"}, "engine"
    )
    _require(engine["name"] == "KataGo", "engine.name必须是KataGo")
    _require(bool(str(engine["version"]).strip()), "engine.version不能为空")
    _require(bool(str(engine["backend"]).strip()), "engine.backend不能为空")
    engine_binary_sha = _sha(engine["binarySha256"], "engine.binarySha256")

    model = _exact_keys(artifact["model"], {"name", "sha256"}, "model")
    _require(bool(str(model["name"]).strip()), "model.name不能为空")
    model_sha = _sha(model["sha256"], "model.sha256")

    config = _exact_keys(
        artifact["config"], {"sha256", "maxVisits", "analysisPVLen"}, "config"
    )
    config_sha = _sha(config["sha256"], "config.sha256")
    max_visits = _positive_int(config["maxVisits"], "config.maxVisits", 128)
    pv_len = _positive_int(config["analysisPVLen"], "config.analysisPVLen")

    rules = _exact_keys(artifact["rules"], {"name", "komi", "boardSize"}, "rules")
    rules_name = str(rules["name"] or "").strip().lower()
    _require(
        rules_name in {"chinese", "japanese", "korean", "aga"},
        "rules.name必须是服务端支持的 KataGo 规则",
    )
    komi = _finite(rules["komi"], "rules.komi")
    board_size = _positive_int(rules["boardSize"], "rules.boardSize", 2)
    _require(board_size <= 19, "rules.boardSize不能大于19")

    position = _exact_keys(
        artifact["position"],
        {"analysisPositionHashBefore", "moveNumber"},
        "position",
    )
    position_sha = _sha(
        position["analysisPositionHashBefore"],
        "position.analysisPositionHashBefore",
    )
    move_number = _positive_int(position["moveNumber"], "position.moveNumber", 0)

    subject = str(artifact["subjectColor"] or "").upper()
    _require(subject in {"B", "W"}, "subjectColor必须是B或W")
    _require(
        artifact["valuePerspective"] == "subject",
        "valuePerspective必须与subjectColor的候选值视角一致",
    )
    visits = _positive_int(artifact["visits"], "金标 visits", 128)
    _require(visits <= max_visits, "实际 visits 不能大于 config.maxVisits")
    best_move = _coord(artifact["bestMove"], board_size, "bestMove")

    candidates = artifact["candidates"]
    _require(isinstance(candidates, list) and bool(candidates), "candidates不能为空")
    normalized_candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_candidate in enumerate(candidates, 1):
        candidate = _exact_keys(
            raw_candidate,
            {"move", "visits", "winrate", "scoreLead", "pv"},
            f"candidates[{index}]",
        )
        move = _coord(candidate["move"], board_size, f"candidates[{index}].move")
        _require(move not in seen, "candidates候选手重复")
        seen.add(move)
        candidate_visits = _positive_int(
            candidate["visits"], f"candidates[{index}].visits"
        )
        _require(candidate_visits <= visits, "候选 visits 不能大于制品 visits")
        winrate = _finite(candidate["winrate"], f"candidates[{index}].winrate")
        _require(0 <= float(winrate) <= 1, "候选 winrate 必须位于[0,1]")
        score_lead = _finite(candidate["scoreLead"], f"candidates[{index}].scoreLead")
        pv = candidate["pv"]
        _require(isinstance(pv, list) and bool(pv), f"candidates[{index}].pv不能为空")
        _require(len(pv) <= pv_len, f"candidates[{index}].pv超过analysisPVLen")
        normalized_pv = [
            _coord(item, board_size, f"candidates[{index}].pv") for item in pv
        ]
        _require(normalized_pv[0] == move, "候选 PV 必须从该候选手开始")
        normalized_candidates.append(
            {
                "move": move,
                "visits": candidate_visits,
                "winrate": winrate,
                "scoreLead": score_lead,
                "pv": normalized_pv,
            }
        )
    _require(normalized_candidates[0]["move"] == best_move, "bestMove必须是第一候选")

    normalized = {
        "schemaVersion": ARTIFACT_SCHEMA,
        "source": "katago",
        "demo": False,
        "engine": {
            "name": "KataGo",
            "version": str(engine["version"]).strip(),
            "backend": str(engine["backend"]).strip(),
            "binarySha256": engine_binary_sha,
        },
        "model": {"name": str(model["name"]).strip(), "sha256": model_sha},
        "config": {
            "sha256": config_sha,
            "maxVisits": max_visits,
            "analysisPVLen": pv_len,
        },
        "rules": {"name": rules_name, "komi": komi, "boardSize": board_size},
        "position": {
            "analysisPositionHashBefore": position_sha,
            "moveNumber": move_number,
        },
        "subjectColor": subject,
        "valuePerspective": "subject",
        "visits": visits,
        "bestMove": best_move,
        "candidates": normalized_candidates,
    }
    _require(
        canonical_json(value) == canonical_json(normalized),
        "artifact必须已是服务端规范形式",
    )
    return normalized


def artifact_from_server_analysis(
    analysis: dict[str, Any],
    *,
    engine_version: str,
    engine_backend: str,
    engine_binary_sha256: str,
    model_name: str,
    model_sha256: str,
    config_sha256: str,
    max_visits: int,
    analysis_pv_len: int,
    rules_name: str,
    komi: float,
    board_size: int,
    analysis_position_hash_before: str,
    move_number: int,
    subject_color: str,
) -> dict[str, Any]:
    """把 ``KataGoEngine.analyze_position`` 的服务端返回投影成金标制品。

    引擎返回黑方视角数值；本函数在登记前唯一地转换为 subject 视角，
    避免训练侧或数据标注者自行翻转胜率/目差。
    """
    _require(isinstance(analysis, dict), "KataGo server analysis必须是对象")
    subject = str(subject_color or "").upper()
    _require(subject in {"B", "W"}, "subjectColor必须是B或W")
    recommendations = analysis.get("recommendations")
    _require(
        isinstance(recommendations, list) and bool(recommendations),
        "KataGo server analysis缺少recommendations",
    )
    candidates = []
    for index, item in enumerate(recommendations, 1):
        _require(isinstance(item, dict), f"recommendations[{index}]必须是对象")
        winrate_black = _finite(
            item.get("winrateBlack"), f"recommendations[{index}].winrateBlack"
        )
        score_black = _finite(
            item.get("scoreLeadBlack"), f"recommendations[{index}].scoreLeadBlack"
        )
        candidates.append(
            {
                "move": str(item.get("move") or "").upper(),
                "visits": item.get("visits"),
                "winrate": (
                    winrate_black if subject == "B" else 1 - float(winrate_black)
                ),
                "scoreLead": score_black if subject == "B" else -float(score_black),
                "pv": [str(move).upper() for move in (item.get("pv") or [])],
            }
        )
    artifact = {
        "schemaVersion": ARTIFACT_SCHEMA,
        "source": "katago",
        "demo": False,
        "engine": {
            "name": "KataGo",
            "version": engine_version,
            "backend": engine_backend,
            "binarySha256": engine_binary_sha256,
        },
        "model": {"name": model_name, "sha256": model_sha256},
        "config": {
            "sha256": config_sha256,
            "maxVisits": max_visits,
            "analysisPVLen": analysis_pv_len,
        },
        "rules": {"name": rules_name, "komi": komi, "boardSize": board_size},
        "position": {
            "analysisPositionHashBefore": analysis_position_hash_before,
            "moveNumber": move_number,
        },
        "subjectColor": subject,
        "valuePerspective": "subject",
        "visits": analysis.get("visits"),
        "bestMove": candidates[0]["move"],
        "candidates": candidates,
    }
    return canonicalize_artifact(artifact)


def make_registry_entry(
    artifact: dict[str, Any], *, registered_at: str, instance_id: str
) -> dict[str, Any]:
    normalized = canonicalize_artifact(artifact)
    _require(bool(UTC_TIMESTAMP_RE.fullmatch(registered_at)), "registeredAt必须是UTC ISO-8601")
    _require(bool(str(instance_id).strip()), "producer.instanceId不能为空")
    artifact_sha = canonical_json_sha256(normalized)
    body = {
        "schemaVersion": REGISTRY_ENTRY_SCHEMA,
        "artifactId": f"katago:{artifact_sha}",
        "artifactSha256": artifact_sha,
        "registeredAt": registered_at,
        "producer": {
            "service": PRODUCER_SERVICE,
            "instanceId": str(instance_id).strip(),
            "workflow": REGISTRY_WORKFLOW,
        },
        "artifact": normalized,
    }
    return {**body, "entrySha256": canonical_json_sha256(body)}


def _validate_entry(value: Any) -> dict[str, Any]:
    entry = _exact_keys(
        value,
        {
            "schemaVersion",
            "artifactId",
            "artifactSha256",
            "registeredAt",
            "producer",
            "artifact",
            "entrySha256",
        },
        "registry entry",
    )
    _require(entry["schemaVersion"] == REGISTRY_ENTRY_SCHEMA, "registry entry版本错误")
    producer = _exact_keys(
        entry["producer"], {"service", "instanceId", "workflow"}, "producer"
    )
    _require(producer["service"] == PRODUCER_SERVICE, "producer.service不是服务端")
    _require(producer["workflow"] == REGISTRY_WORKFLOW, "producer.workflow错误")
    _require(bool(str(producer["instanceId"]).strip()), "producer.instanceId不能为空")
    _require(
        bool(UTC_TIMESTAMP_RE.fullmatch(str(entry["registeredAt"]))),
        "registeredAt必须是UTC ISO-8601",
    )
    artifact = canonicalize_artifact(entry["artifact"])
    artifact_sha = canonical_json_sha256(artifact)
    _require(entry["artifactSha256"] == artifact_sha, "artifactSha256与制品不一致")
    _require(entry["artifactId"] == f"katago:{artifact_sha}", "artifactId与制品不一致")
    body = {
        "schemaVersion": REGISTRY_ENTRY_SCHEMA,
        "artifactId": entry["artifactId"],
        "artifactSha256": artifact_sha,
        "registeredAt": entry["registeredAt"],
        "producer": {
            "service": PRODUCER_SERVICE,
            "instanceId": str(producer["instanceId"]).strip(),
            "workflow": REGISTRY_WORKFLOW,
        },
        "artifact": artifact,
    }
    _require(entry["entrySha256"] == canonical_json_sha256(body), "entrySha256与登记条目不一致")
    return {**body, "entrySha256": entry["entrySha256"]}


def write_registry_snapshot(path: Path, entries: Iterable[dict[str, Any]]) -> str:
    normalized = [_validate_entry(entry) for entry in entries]
    _require(bool(normalized), "registry快照不能为空")
    ordered = sorted(normalized, key=lambda item: item["artifactId"])
    ids = [item["artifactId"] for item in ordered]
    _require(len(ids) == len(set(ids)), "registry存在重复artifactId")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for entry in ordered:
            handle.write(canonical_json(entry) + "\n")
    os.replace(temporary, path)
    return sha256_file(path)


@dataclass(frozen=True)
class TrustedKataGoRegistry:
    source_path: Path
    snapshot_sha256: str
    _artifacts: dict[str, dict[str, Any]]

    def get(self, artifact_id: str) -> dict[str, Any]:
        artifact = self._artifacts.get(str(artifact_id))
        if artifact is None:
            raise RegistryError(f"KataGo artifact未登记：{artifact_id}")
        return copy.deepcopy(artifact)

    def resolve(self, reference: Any) -> dict[str, Any]:
        ref = _exact_keys(
            reference,
            {"artifactId", "artifactSha256", "registrySnapshotSha256"},
            "trustedArtifactRef",
        )
        ref_snapshot = _sha(ref["registrySnapshotSha256"], "registrySnapshotSha256")
        _require(ref_snapshot == self.snapshot_sha256, "制品引用与registry快照SHA-256不一致")
        artifact_sha = _sha(ref["artifactSha256"], "artifactSha256")
        artifact_id = str(ref["artifactId"] or "")
        _require(artifact_id == f"katago:{artifact_sha}", "制品引用ID与SHA-256不一致")
        artifact = self.get(artifact_id)
        _require(
            canonical_json_sha256(artifact) == artifact_sha,
            "登记制品与引用SHA-256不一致",
        )
        return artifact


@dataclass(frozen=True)
class TrustedKataGoRegistryBundle:
    source_path: Path
    snapshot_sha256: str
    _registries: dict[str, TrustedKataGoRegistry]

    def resolve(self, reference: Any) -> dict[str, Any]:
        ref = _exact_keys(
            reference,
            {"artifactId", "artifactSha256", "registrySnapshotSha256"},
            "trustedArtifactRef",
        )
        snapshot = _sha(ref["registrySnapshotSha256"], "registrySnapshotSha256")
        registry = self._registries.get(snapshot)
        _require(registry is not None, "制品引用的registry快照不在bundle中")
        return registry.resolve(ref)


def load_registry_snapshot(
    path: Path, *, expected_sha256: str | None
) -> TrustedKataGoRegistry | TrustedKataGoRegistryBundle:
    _require(expected_sha256 is not None, "缺少显式registry快照SHA-256")
    expected = _sha(expected_sha256, "registry快照SHA-256")
    path = Path(path)
    _require(path.is_file(), f"registry快照不存在：{path}")
    # 只读一次：用同一份 bytes 做整文件哈希和 JSONL 解析，避免 TOCTOU。
    snapshot_bytes = path.read_bytes()
    actual = hashlib.sha256(snapshot_bytes).hexdigest()
    _require(actual == expected, "registry快照SHA-256与显式锁定值不一致")
    try:
        bundle = json.loads(snapshot_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        bundle = None
    if isinstance(bundle, dict) and bundle.get("schemaVersion") == "gomentor-trusted-katago-registry-bundle-v1":
        snapshots = bundle.get("snapshots")
        _require(isinstance(snapshots, list) and bool(snapshots), "KataGo registry bundle为空")
        registries: dict[str, TrustedKataGoRegistry] = {}
        for index, snapshot in enumerate(snapshots, 1):
            _require(isinstance(snapshot, dict), f"KataGo bundle第{index}条无效")
            relative = Path(str(snapshot.get("path") or ""))
            _require(
                not relative.is_absolute() and ".." not in relative.parts,
                f"KataGo bundle第{index}条路径不安全",
            )
            child = load_registry_snapshot(
                path.parent / relative,
                expected_sha256=snapshot.get("sha256"),
            )
            _require(
                isinstance(child, TrustedKataGoRegistry),
                "KataGo registry bundle不允许递归bundle",
            )
            _require(
                child.snapshot_sha256 not in registries,
                f"KataGo bundle重复快照：{child.snapshot_sha256}",
            )
            registries[child.snapshot_sha256] = child
        return TrustedKataGoRegistryBundle(path.resolve(), actual, registries)
    entries: dict[str, dict[str, Any]] = {}
    try:
        snapshot_text = snapshot_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RegistryError(f"registry快照不是有效UTF-8：{exc}") from exc
    for line_number, line in enumerate(snapshot_text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"registry第{line_number}行JSON错误：{exc}") from exc
        entry = _validate_entry(raw)
        artifact_id = entry["artifactId"]
        _require(artifact_id not in entries, f"registry重复artifactId：{artifact_id}")
        entries[artifact_id] = entry["artifact"]
    _require(bool(entries), "registry快照不能为空")
    return TrustedKataGoRegistry(path.resolve(), actual, entries)


def _connect_registry(database: Path) -> sqlite3.Connection:
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS trusted_katago_artifacts (
            artifact_id TEXT PRIMARY KEY,
            artifact_sha256 TEXT NOT NULL UNIQUE,
            artifact_json TEXT NOT NULL,
            entry_json TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            producer_instance_id TEXT NOT NULL
        )
        """
    )
    return connection


def register_artifact_sqlite(
    database: Path,
    artifact: dict[str, Any],
    *,
    registered_at: str,
    instance_id: str,
) -> dict[str, Any]:
    """服务端登记一个规范制品；同 ID 只允许完全相同的幂等写入。"""
    entry = make_registry_entry(
        artifact, registered_at=registered_at, instance_id=instance_id
    )
    artifact_json = canonical_json(entry["artifact"])
    entry_json = canonical_json(entry)
    with _connect_registry(database) as connection:
        existing = connection.execute(
            "SELECT artifact_json, entry_json FROM trusted_katago_artifacts WHERE artifact_id=?",
            (entry["artifactId"],),
        ).fetchone()
        if existing:
            _require(
                existing["artifact_json"] == artifact_json
                and existing["entry_json"] == entry_json,
                "已登记KataGo artifact不允许覆写",
            )
            return entry
        connection.execute(
            """
            INSERT INTO trusted_katago_artifacts(
                artifact_id, artifact_sha256, artifact_json, entry_json,
                registered_at, producer_instance_id
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                entry["artifactId"],
                entry["artifactSha256"],
                artifact_json,
                entry_json,
                entry["registeredAt"],
                entry["producer"]["instanceId"],
            ),
        )
    return entry


def export_registry_snapshot(database: Path, output: Path) -> str:
    with _connect_registry(database) as connection:
        rows = connection.execute(
            "SELECT entry_json FROM trusted_katago_artifacts ORDER BY artifact_id"
        ).fetchall()
    _require(bool(rows), "服务端KataGo artifact登记表为空")
    entries = []
    for row in rows:
        try:
            entries.append(json.loads(row["entry_json"]))
        except json.JSONDecodeError as exc:
            raise RegistryError(f"数据库登记条目JSON损坏：{exc}") from exc
    return write_registry_snapshot(output, entries)


__all__ = [
    "ARTIFACT_SCHEMA",
    "REGISTRY_ENTRY_SCHEMA",
    "RegistryError",
    "TrustedKataGoRegistry",
    "TrustedKataGoRegistryBundle",
    "artifact_from_server_analysis",
    "canonical_json",
    "canonical_json_sha256",
    "canonicalize_artifact",
    "export_registry_snapshot",
    "load_registry_snapshot",
    "make_registry_entry",
    "register_artifact_sqlite",
    "sha256_file",
    "write_registry_snapshot",
]
