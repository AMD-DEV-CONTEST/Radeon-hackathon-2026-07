import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))


def test_upstream_source_is_native_reimpl_only():
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "noborus__ov.b96c2ba",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
            "spec": {"path": "corpus/programbench/specs/noborus__ov.b96c2ba.json"},
        }
    )

    assert route.verdict == "needs-native-reimpl"
    assert route.official_eval_allowed is False
    assert route.autofix_allowed is False
    assert route.local_oracle_required is True
    assert [stage["name"] for stage in route.stages] == [
        "extract-spec",
        "write-native-reimpl",
        "local-oracle",
        "official-eval-after-local-green",
    ]


def test_upstream_source_with_green_local_oracle_can_reach_official_gate():
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "yoav-lavi__melody.f4af9b4",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
            "spec": {"path": "corpus/programbench/specs/yoav-lavi__melody.f4af9b4.json"},
        },
        oracle_result={"passed": 12, "total": 12},
    )

    assert route.verdict == "oracle-green-ready-for-official"
    assert route.official_eval_allowed is True
    assert route.local_oracle_required is False


def test_reimpl_skill_requires_local_oracle_before_official_eval():
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "wfxr__csview.8ac4de0",
            "engine": "reimpl-skill-oracle",
            "source_shape": {"class": "reimpl-candidate", "source_files": 2},
            "spec": {"path": "corpus/programbench/specs/wfxr__csview.8ac4de0.json"},
            "reimpl_skill": {"path": "corpus/programbench/reimpl_skills/csview.json"},
        },
        current_verdict="near-lock",
    )

    assert route.verdict == "needs-local-oracle-tail"
    assert route.official_eval_allowed is False
    assert route.autofix_allowed is False
    assert route.local_oracle_required is True
    assert route.stages[0]["name"] == "local-oracle"


def test_oracle_green_candidate_is_allowed_to_reach_official_eval():
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "ducaale__xh.4a6e44f",
            "engine": "spec-local-oracle",
            "source_shape": {"class": "reimpl-candidate", "source_files": 3},
            "spec": {"path": "corpus/programbench/specs/ducaale__xh.4a6e44f.json"},
        },
        oracle_result={"passed": 335, "total": 335},
    )

    assert route.verdict == "oracle-green-ready-for-official"
    assert route.official_eval_allowed is True
    assert route.autofix_allowed is False
    assert route.local_oracle_required is False


def test_missing_spec_routes_to_extraction_first():
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "somebody__newtool.1234567",
            "engine": "extract-spec-first",
            "source_shape": {"class": "reimpl-candidate", "source_files": 1},
        }
    )

    assert route.verdict == "needs-spec-extraction"
    assert route.official_eval_allowed is False
    assert route.stages[0]["name"] == "extract-spec"


def test_autodrive_routes_before_repack_or_eval():
    src = (ROOT / "scripts" / "determinex_pb_autodrive.py").read_text(encoding="utf-8")
    body = src[src.index("def drive_one(") :]

    route_idx = body.index('route_from_corpus({**consult0, "slug": slug})')
    repack_idx = body.index("tarball = _repack(slug)")
    fresh_idx = body.index("data, c, v = _fresh_eval(slug, tarball)")

    assert route_idx < repack_idx < fresh_idx


def test_ask_corpus_global_class_patterns_apply_to_every_tool():
    import determinex_pb_ask_corpus as ask

    assert ask._pattern_applies("csview", ["*"]) is True
    assert ask._pattern_applies("ov", ["__all__"]) is True
    assert ask._pattern_applies("xh", ["all"]) is True
    assert ask._pattern_applies("csview", ["ov"]) is False


def test_build_knowledge_patches_merge_into_ask_corpus():
    import determinex_pb_ask_corpus as ask

    kb = ask._load_build_knowledge()

    assert "corpus_pre_eval_gate" in kb["class_patterns"]
    assert "corpus_pre_eval_gate_2026_06_30" in kb


def test_build_knowledge_loader_salvages_first_json_object_with_trailing_junk():
    import determinex_pb_ask_corpus as ask

    kb = ask._loads_knowledge_json('{"class_patterns": {}, "per_tool": {}}\nTRAILING')

    assert kb["class_patterns"] == {}
    assert kb["per_tool"] == {}
    assert kb["_load_warning"].startswith("build_knowledge.json had trailing data")
