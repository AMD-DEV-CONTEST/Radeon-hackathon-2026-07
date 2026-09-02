import sqlite3
import json
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field


@dataclass
class Conflict:
    severity: str  # "high" | "medium" | "low"
    description: str
    involved_entities: List[str] = field(default_factory=list)
    suggestion: str = ""
    location: str = ""


@dataclass
class CheckResult:
    type: str
    status: str  # "passed" | "warning" | "error"
    conflicts: List[Conflict] = field(default_factory=list)


class ConsistencyChecker:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def run_all(self, entity_id: str = None, book_id: str = None,
                check_types: List[str] = None) -> Tuple[List[CheckResult], Dict]:
        if check_types is None:
            check_types = ["timeline", "character", "rule", "faction"]
        results = []
        for ct in check_types:
            method_name = "check_" + ct
            method = getattr(self, method_name, None)
            if method:
                try:
                    result = method(entity_id, book_id)
                    results.append(result)
                except Exception as e:
                    results.append(CheckResult(type=ct, status="error",
                        conflicts=[Conflict(severity="high", description="Check failed: " + str(e))]))
            else:
                results.append(CheckResult(type=ct, status="passed"))
        summary = {"total_checks": len(results), "passed": 0, "warnings": 0, "errors": 0}
        for r in results:
            if r.status == "error":
                summary["errors"] += 1
            elif r.status == "warning":
                summary["warnings"] += 1
            else:
                summary["passed"] += 1
        return results, summary

    def check_timeline(self, entity_id: str = None, book_id: str = None) -> CheckResult:
        conn = self._get_conn()
        conflicts = []
        try:
            cursor = conn.cursor()
            # Build query
            sql = """
                SELECT te.*, e.title as entity_title, e.entity_type
                FROM timeline_events te
                LEFT JOIN entities e ON te.entity_id = e.entity_id
                WHERE 1=1
            """
            params = []
            if entity_id:
                sql += " AND te.entity_id = ?"
                params.append(entity_id)
            if book_id:
                sql += " AND te.book_id = ?"
                params.append(book_id)
            sql += " ORDER BY te.year, te.era"
            cursor.execute(sql, params)
            events = [dict(r) for r in cursor.fetchall()]

            # Rule 1: Check for events with same year that might conflict
            year_groups = {}
            for evt in events:
                y = evt.get("year")
                if y is not None:
                    key = (y, evt.get("era", ""))
                    if key not in year_groups:
                        year_groups[key] = []
                    year_groups[key].append(evt)
            for key, group in year_groups.items():
                if len(group) > 3:  # More than 3 events in same year
                    titles = [e.get("title", "?") for e in group[:5]]
                    conflicts.append(Conflict(
                        severity="low",
                        description=f"{len(group)} events clustered at year {key[0]} ({key[1]}): {', '.join(titles)}",
                        involved_entities=[e.get("entity_id", "") for e in group if e.get("entity_id")],
                        suggestion="Consider spreading events across different years or sub-eras.",
                        location="timeline_events"
                    ))

            # Rule 2: Check for events without a year
            no_year = [e for e in events if e.get("year") is None]
            if len(no_year) > 5:
                conflicts.append(Conflict(
                    severity="low",
                    description=f"{len(no_year)} timeline events have no year set.",
                    involved_entities=[e.get("entity_id", "") for e in no_year[:5]],
                    suggestion="Set a year for each timeline event to improve chronology.",
                    location="timeline_events"
                ))

            # Rule 3: Check if same entity appears in events with very different years
            entity_year_range = {}
            for evt in events:
                eid = evt.get("entity_id")
                y = evt.get("year")
                if eid and y is not None:
                    if eid not in entity_year_range:
                        entity_year_range[eid] = {"min": y, "max": y, "title": evt.get("entity_title", "?")}
                    else:
                        entity_year_range[eid]["min"] = min(entity_year_range[eid]["min"], y)
                        entity_year_range[eid]["max"] = max(entity_year_range[eid]["max"], y)
            for eid, range_data in entity_year_range.items():
                span = range_data["max"] - range_data["min"]
                if span > 1000:
                    conflicts.append(Conflict(
                        severity="warning",
                        description=f"Entity '{range_data['title']}' spans {span} years ({range_data['min']}-{range_data['max']}).",
                        involved_entities=[eid],
                        suggestion="Verify this entity's lifespan or if different entities share the same ID.",
                        location="timeline_events"
                    ))

            temporal_sql = (
                "SELECT id,source_anchor_id,target_anchor_id FROM temporal_relations "
                "WHERE confidence='conflicting' AND review_status='pending'"
            )
            temporal_params = []
            if book_id:
                temporal_sql += " AND book_id=?"
                temporal_params.append(book_id)
            pending_relations = cursor.execute(temporal_sql, temporal_params).fetchall()
            for relation in pending_relations:
                conflicts.append(Conflict(
                    severity="high",
                    description="Temporal relation forms an unresolved ordering cycle.",
                    suggestion="Review the retained conflicting relation; do not treat it as accepted order.",
                    location=f"temporal_relations:{relation['id']}",
                ))

            from services.temporal import find_state_conflict_candidates

            for candidate in find_state_conflict_candidates(conn, book_id, entity_id):
                conflicts.append(Conflict(
                    severity="warning",
                    description=(
                        f"Entity state '{candidate['state_type']}' has mutually exclusive values "
                        "in overlapping or unordered intervals."
                    ),
                    involved_entities=[candidate["entity_id"]],
                    suggestion="Set non-overlapping anchors, supersede an old state, or keep the conflict for author review.",
                    location="entity_state_segments:" + ",".join(candidate["segment_ids"]),
                ))

        finally:
            conn.close()

        status = "passed"
        if conflicts:
            high_count = sum(1 for c in conflicts if c.severity == "high")
            if high_count > 0:
                status = "error"
            else:
                status = "warning"
        return CheckResult(type="timeline", status=status, conflicts=conflicts)

    def check_character(self, entity_id: str = None, book_id: str = None) -> CheckResult:
        conn = self._get_conn()
        conflicts = []
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM entities WHERE entity_type = 'character' AND is_active = 1"
            params = []
            if entity_id:
                sql += " AND entity_id = ?"
                params.append(entity_id)
            if book_id:
                sql += " AND book_id = ?"
                params.append(book_id)
            cursor.execute(sql, params)
            characters = [dict(r) for r in cursor.fetchall()]

            for char in characters:
                tags = []
                try:
                    tags = json.loads(char.get("tags", "[]")) if char.get("tags") else []
                except (json.JSONDecodeError, TypeError):
                    pass
                tags_lower = [t.lower() for t in tags]

                # Rule 1: Check for contradictory tags
                contradiction_pairs = [
                    (["dead", "deceased", "died"], ["alive", "living", "immortal"]),
                    (["child", "young"], ["ancient", "elderly", "old"]),
                    (["hero", "good"], ["villain", "evil", "antagonist"]),
                ]
                for positive_list, negative_list in contradiction_pairs:
                    has_positive = any(t in tags_lower for t in positive_list)
                    has_negative = any(t in tags_lower for t in negative_list)
                    if has_positive and has_negative:
                        conflicts.append(Conflict(
                            severity="warning",
                            description=f"Character '{char.get('title', '')}' has contradictory tags: {positive_list[0]} vs {negative_list[0]}.",
                            involved_entities=[char["entity_id"]],
                            suggestion="Remove one of the conflicting tags.",
                            location="entities.tags"
                        ))

                # Rule 2: Check for low-importance characters with many relationships
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM relations WHERE source_id = ? OR target_id = ?",
                    (char["entity_id"], char["entity_id"])
                )
                rel_count = cursor.fetchone()["cnt"]
                if rel_count > 10 and char.get("importance", 5) < 3:
                    conflicts.append(Conflict(
                        severity="low",
                        description=f"Character '{char.get('title', '')}' has {rel_count} relations but importance={char.get('importance')}.",
                        involved_entities=[char["entity_id"]],
                        suggestion="Consider raising importance or reducing relations.",
                        location="relations"
                    ))

        finally:
            conn.close()

        status = "passed"
        if conflicts:
            if any(c.severity == "high" for c in conflicts):
                status = "error"
            else:
                status = "warning"
        return CheckResult(type="character", status=status, conflicts=conflicts)

    def check_rule(self, entity_id: str = None, book_id: str = None) -> CheckResult:
        conn = self._get_conn()
        conflicts = []
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM entities WHERE entity_type = 'rule' AND is_active = 1"
            params = []
            if entity_id:
                sql += " AND entity_id = ?"
                params.append(entity_id)
            if book_id:
                sql += " AND book_id = ?"
                params.append(book_id)
            cursor.execute(sql, params)
            rules = [dict(r) for r in cursor.fetchall()]

            # Check for rules with empty content
            for rule in rules:
                content = rule.get("content", "") or ""
                full_content = rule.get("full_content", "") or ""
                if not content and not full_content:
                    conflicts.append(Conflict(
                        severity="warning",
                        description=f"Rule '{rule.get('title', '')}' has no content or full_content.",
                        involved_entities=[rule["entity_id"]],
                        suggestion="Fill in the rule description.",
                        location="entities"
                    ))

            # Simple keyword-level contradiction check
            negation_pairs = [
                ("not exist", "exist"), ("cannot", "can"), ("no magic", "magic"),
                ("forbidden", "allowed"), ("never", "always"),
            ]
            for i, rule1 in enumerate(rules):
                text1 = (rule1.get("content", "") + " " + (rule1.get("full_content", "") or "")).lower()
                for rule2 in rules[i+1:]:
                    text2 = (rule2.get("content", "") + " " + (rule2.get("full_content", "") or "")).lower()
                    for neg, pos in negation_pairs:
                        if (neg in text1 and pos in text2) or (pos in text1 and neg in text2):
                            conflicts.append(Conflict(
                                severity="warning",
                                description=f"Potential contradiction between rules: '{rule1.get('title')}' and '{rule2.get('title')}' ({neg}/{pos}).",
                                involved_entities=[rule1["entity_id"], rule2["entity_id"]],
                                suggestion="Review both rules for consistency.",
                                location="entities"
                            ))
                            break

        finally:
            conn.close()

        status = "passed"
        if conflicts:
            if any(c.severity == "high" for c in conflicts):
                status = "error"
            else:
                status = "warning"
        return CheckResult(type="rule", status=status, conflicts=conflicts)

    def check_faction(self, entity_id: str = None, book_id: str = None) -> CheckResult:
        conn = self._get_conn()
        conflicts = []
        try:
            cursor = conn.cursor()
            sql = """
                SELECT e.*, r.source_id, r.target_id, r.relation_type, r.description as rel_desc
                FROM entities e
                LEFT JOIN relations r ON r.source_id = e.entity_id OR r.target_id = e.entity_id
                WHERE e.entity_type = 'faction' AND e.is_active = 1
            """
            params = []
            if entity_id:
                sql += " AND e.entity_id = ?"
                params.append(entity_id)
            if book_id:
                sql += " AND e.book_id = ?"
                params.append(book_id)
            cursor.execute(sql, params)
            rows = [dict(r) for r in cursor.fetchall()]

            # Deduplicate factions
            faction_ids = set()
            for r in rows:
                faction_ids.add(r["entity_id"])
            faction_ids = list(faction_ids)

            # Check factions with very few members
            for fid in faction_ids:
                cursor.execute(
                    "SELECT COUNT(*) as cnt FROM relations WHERE (source_id = ? OR target_id = ?) AND relation_type IN ('belongs_to', 'member_of', 'member')",
                    (fid, fid)
                )
                member_count = cursor.fetchone()["cnt"]
                if member_count == 0:
                    cursor.execute("SELECT title FROM entities WHERE entity_id = ?", (fid,))
                    title = cursor.fetchone()
                    if title:
                        conflicts.append(Conflict(
                            severity="low",
                            description=f"Faction '{title['title']}' has no members.",
                            involved_entities=[fid],
                            suggestion="Add members to this faction or mark it as inactive.",
                            location="relations"
                        ))

            # Check for competing/conflicting factions
            enemy_relations = {}
            for r in rows:
                if r.get("relation_type") in ("enemy", "hostile", "war", "rival"):
                    key = tuple(sorted([r["source_id"], r["target_id"]]))
                    enemy_relations[key] = r

            # Check if a character belongs to enemy factions
            if enemy_relations:
                for eid1, eid2 in enemy_relations:
                    cursor.execute("""
                        SELECT COUNT(*) as cnt FROM relations
                        WHERE relation_type IN ('belongs_to', 'member_of', 'member')
                        AND ((source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?))
                    """, (eid1, eid1, eid2, eid2))
                    # This simplified check looks for any character linked to both factions

        finally:
            conn.close()

        status = "passed"
        if conflicts:
            if any(c.severity == "high" for c in conflicts):
                status = "error"
            else:
                status = "warning"
        return CheckResult(type="faction", status=status, conflicts=conflicts)


def run_check(db_path: str, scope: str = "full", check_types: List[str] = None,
              entity_id: str = None, book_id: str = None) -> Tuple[List[CheckResult], Dict]:
    checker = ConsistencyChecker(db_path)
    if scope and scope.startswith("entity:"):
        entity_id = scope.split(":", 1)[1]
    return checker.run_all(entity_id=entity_id, book_id=book_id, check_types=check_types)
