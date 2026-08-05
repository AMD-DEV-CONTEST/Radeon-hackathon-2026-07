import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))


def test_all_queue_skips_alias_locks_and_ceilings_by_default():
    from determinex_pb_churn import queue_from_eval_rows

    rows = [
        {"slug": "locked__tool.1111111", "status": "strict_lock"},
        {"slug": "alias__tool.2222222", "alias_of": "locked__tool.1111111"},
        {"slug": "ceil__tool.3333333", "status": "ceiling_certified"},
        {"slug": "open__tool.4444444", "status": "pending_unlock", "official_score_pct": 99.1},
        {"slug": "lower__tool.5555555", "status": "pending_unlock", "official_score_pct": 10.0},
    ]

    assert queue_from_eval_rows(rows) == ["open__tool.4444444", "lower__tool.5555555"]


def test_all_queue_cools_down_recent_timeout_without_blocking_other_tools():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "rs__jplot.2a54bcc", "status": "pending_unlock", "official_score_pct": 100.0},
        {
            "slug": "rust-embedded__svd2rust.1760b5e",
            "status": "pending_unlock",
            "official_score_pct": 88.0,
        },
    ]
    state = {
        "runs": {
            "rs__jplot.2a54bcc": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "write-native-reimpl"},
                "result": {"rc": 124},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["rust-embedded__svd2rust.1760b5e"]


def test_all_queue_cools_down_short_alias_for_recent_full_slug_failure():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "yj", "status": "pending_unlock", "official_score_pct": 100.0},
        {
            "slug": "yoav-lavi__melody.1234567",
            "status": "pending_unlock",
            "official_score_pct": 88.0,
        },
    ]
    state = {
        "runs": {
            "sclevine__yj.8016400": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "write-native-reimpl"},
                "result": {"rc": 1},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["yoav-lavi__melody.1234567"]


def test_all_queue_cools_down_hashless_author_slug_after_full_slug_failure():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "yoav-lavi__melody", "status": "board_cache_only", "official_score_pct": 99.9},
        {
            "slug": "rust-embedded__svd2rust",
            "status": "board_cache_only",
            "official_score_pct": 88.0,
        },
    ]
    state = {
        "runs": {
            "yoav-lavi__melody.f4af9b4": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "write-native-reimpl"},
                "result": {"rc": 124},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["rust-embedded__svd2rust"]


def test_all_queue_keeps_successful_stage_transition_eligible(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    # A stage transition is "successful" only if it produced a USABLE spec —
    # pin one, so this doesn't depend on the host's real corpus contents.
    monkeypatch.setattr(churn, "SPECS", tmp_path)
    (tmp_path / "rs__jplot.2a54bcc.json").write_text(
        '{"n_examples": 12, "examples": [{"test": "t"}]}', encoding="utf-8"
    )

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "rs__jplot.2a54bcc", "status": "pending_unlock", "official_score_pct": 100.0},
    ]
    state = {
        "runs": {
            "rs__jplot.2a54bcc": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "extract-spec"},
                "result": {"rc": 0},
            }
        }
    }

    assert churn.queue_from_eval_rows(rows, state, now=now) == ["rs__jplot.2a54bcc"]


def test_successful_reimpl_without_candidate_cools_down_as_no_progress():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 21, 10, tzinfo=dt.UTC)
    rows = [
        {
            "slug": "blake3-team__blake3.15e83a5",
            "status": "pending_unlock",
            "official_score_pct": 100.0,
        },
        {"slug": "codesnap-rs__codesnap", "status": "pending_unlock", "official_score_pct": 99.0},
    ]
    state = {
        "runs": {
            "blake3-team__blake3.15e83a5": {
                "slug": "blake3-team__blake3.15e83a5",
                "executed": True,
                "ts": now.isoformat(),
                "candidate_path": None,
                "action": {"name": "write-native-reimpl"},
                "result": {"rc": 0, "stdout": "[drive] workshop run failed; stopping\n"},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["codesnap-rs__codesnap"]


def test_productive_bias_ready_work_before_cold_breadth(tmp_path, monkeypatch):
    # UPDATED 2026-07-10: breadth is only a tie-breaker inside the same readiness
    # tier. On a paid host, a spec/candidate that can spend model/oracle work must
    # outrank a never-touched tool that would only harvest another free spec.
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    (tmp_path / "blake3-team__blake3.15e83a5.json").write_text(
        '{"n_examples": 12, "examples": [{"test": "t"}]}', encoding="utf-8"
    )

    now = dt.datetime(2026, 6, 30, 21, 10, tzinfo=dt.UTC)
    rows = [
        {
            "slug": "blake3-team__blake3.15e83a5",
            "status": "pending_unlock",
            "official_score_pct": 100.0,
        },
        {"slug": "codesnap-rs__codesnap", "status": "pending_unlock", "official_score_pct": 99.0},
    ]
    state = {
        "runs": {
            "blake3-team__blake3.15e83a5": {
                "slug": "blake3-team__blake3.15e83a5",
                "executed": True,
                "ts": now.isoformat(),
                "candidate_path": "logs/reimpl/blake3_drive.py",
                "action": {"name": "write-native-reimpl"},
                "result": {"rc": 0},
            }
        }
    }

    q = churn.queue_from_eval_rows(rows, state, now=now)
    assert q[0] == "blake3-team__blake3.15e83a5"  # ready work before cold breadth
    assert "codesnap-rs__codesnap" in q  # untouched tool remains eligible


def test_breadth_bias_still_orders_within_same_readiness_tier(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    monkeypatch.setattr(churn, "ROOT", tmp_path)

    now = dt.datetime(2026, 6, 30, 21, 10, tzinfo=dt.UTC)
    rows = [
        {
            "slug": "blake3-team__blake3.15e83a5",
            "status": "pending_unlock",
            "official_score_pct": 100.0,
        },
        {"slug": "codesnap-rs__codesnap", "status": "pending_unlock", "official_score_pct": 99.0},
    ]
    state = {
        "runs": {
            "blake3-team__blake3.15e83a5": {
                "slug": "blake3-team__blake3.15e83a5",
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "extract-spec"},
                "result": {"rc": 124},
            }
        }
    }

    q = churn.queue_from_eval_rows(rows, state, now=now, cooldown_s=0)
    assert q[0] == "codesnap-rs__codesnap"  # breadth still breaks ties
    assert "blake3-team__blake3.15e83a5" in q  # just-run tool still eligible, not dropped


def test_zero_example_local_oracle_cools_down_as_no_signal():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 23, 25, tzinfo=dt.UTC)
    rows = [
        {
            "slug": "ast-grep__ast-grep.dde0fe0",
            "status": "pending_unlock",
            "official_score_pct": 99.0,
        },
        {"slug": "naggie__dstask", "status": "pending_unlock", "official_score_pct": 80.0},
    ]
    state = {
        "runs": {
            "ast-grep__ast-grep.dde0fe0": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "local-oracle"},
                "result": {"rc": 0},
                "oracle_result_saved": {"passed": 0, "total": 0, "rc": 0},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["naggie__dstask"]


def test_all_queue_prioritizes_ready_candidate_over_cold_high_score(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "ROOT", tmp_path)
    monkeypatch.setattr(churn, "SPECS", tmp_path / "corpus" / "programbench" / "specs")
    monkeypatch.setattr(
        churn, "ORACLE_RESULTS", tmp_path / "corpus" / "programbench" / "oracle_results"
    )
    monkeypatch.setattr(
        churn, "OVERRIDES", tmp_path / "corpus" / "programbench" / "per_tool_overrides"
    )

    churn.SPECS.mkdir(parents=True)
    (tmp_path / "logs" / "reimpl").mkdir(parents=True)
    (churn.SPECS / "wfxr__csview.8ac4de0.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs" / "reimpl" / "csview_drive.py").write_text(
        "print('ready')\n", encoding="utf-8"
    )

    rows = [
        {
            "slug": "hush-shell__hush.560c33a",
            "status": "pending_unlock",
            "official_score_pct": 99.9,
        },
        {"slug": "wfxr__csview.8ac4de0", "status": "pending_unlock", "official_score_pct": 80.0},
    ]

    assert churn.queue_from_eval_rows(rows)[0] == "wfxr__csview.8ac4de0"


def test_all_queue_prioritizes_existing_spec_over_candidate_without_spec(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "ROOT", tmp_path)
    monkeypatch.setattr(churn, "SPECS", tmp_path / "corpus" / "programbench" / "specs")
    monkeypatch.setattr(
        churn, "ORACLE_RESULTS", tmp_path / "corpus" / "programbench" / "oracle_results"
    )
    monkeypatch.setattr(
        churn, "OVERRIDES", tmp_path / "corpus" / "programbench" / "per_tool_overrides"
    )

    churn.SPECS.mkdir(parents=True)
    (tmp_path / "logs" / "reimpl").mkdir(parents=True)
    (tmp_path / "logs" / "reimpl" / "walk_drive.py").write_text(
        "print('candidate')\n", encoding="utf-8"
    )
    (churn.SPECS / "gabotechs__dep-tree.json").write_text("{}", encoding="utf-8")

    rows = [
        {"slug": "antonmedv__walk", "status": "pending_unlock", "official_score_pct": 99.0},
        {"slug": "gabotechs__dep-tree", "status": "pending_unlock", "official_score_pct": 70.0},
    ]

    assert churn.queue_from_eval_rows(rows)[0] == "gabotechs__dep-tree"


def test_all_queue_pushes_broad_specs_behind_small_specs(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    monkeypatch.setenv("DETERMINEX_PB_CLOUD_REIMPL_MAX_EXAMPLES", "80")
    (tmp_path / "ariga__atlas.6d81150.json").write_text(
        '{"n_examples": 353, "examples": [{"test": "t"}]}', encoding="utf-8"
    )
    (tmp_path / "ducaale__xh.4a6e44f.json").write_text(
        '{"n_examples": 18, "examples": [{"test": "t"}]}', encoding="utf-8"
    )

    rows = [
        {"slug": "ariga__atlas.6d81150", "status": "pending_unlock", "official_score_pct": 99.9},
        {"slug": "ducaale__xh.4a6e44f", "status": "pending_unlock", "official_score_pct": 50.0},
    ]

    assert churn.queue_from_eval_rows(rows)[0] == "ducaale__xh.4a6e44f"


def test_local_spec_path_accepts_hashless_slug_for_hashed_spec(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    spec = tmp_path / "gabotechs__dep-tree.60a95a2.json"
    spec.write_text("{}", encoding="utf-8")

    assert churn._local_spec_path("gabotechs__dep-tree") == str(spec)


def test_local_spec_path_treats_confirmed_empty_harvest_as_absent(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    empty = tmp_path / "quinn-rs__quinn.bb359cc.json"
    empty.write_text(
        '{"slug": "quinn-rs__quinn.bb359cc", "n_examples": 0, "examples": []}', encoding="utf-8"
    )

    assert churn._local_spec_path("quinn-rs__quinn.bb359cc") is None
    # A placeholder spec WITHOUT the n_examples field stays usable (unknown != empty).
    placeholder = tmp_path / "wfxr__csview.8ac4de0.json"
    placeholder.write_text("{}", encoding="utf-8")
    assert churn._local_spec_path("wfxr__csview.8ac4de0") == str(placeholder)


def test_extract_spec_producing_empty_harvest_cools_down_as_no_progress(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    (tmp_path / "quinn-rs__quinn.bb359cc.json").write_text(
        '{"n_examples": 0, "examples": []}', encoding="utf-8"
    )

    now = dt.datetime(2026, 7, 10, 2, 0, tzinfo=dt.UTC)
    run = {
        "executed": True,
        "ts": now.isoformat(),
        "action": {"name": "extract-spec"},
        "result": {"rc": 0},
    }
    # Empty harvest -> no usable spec -> the rc=0 extract pass made no progress.
    assert churn.should_cool_down_run(run, slug="quinn-rs__quinn.bb359cc", now=now)

    # A successful harvest with real examples stays eligible for the next stage.
    (tmp_path / "lz4__lz4.1519f46.json").write_text(
        '{"n_examples": 377, "examples": [{"test": "t"}]}', encoding="utf-8"
    )
    assert not churn.should_cool_down_run(run, slug="lz4__lz4.1519f46", now=now)


def test_candidate_for_skips_generation_error_placeholder(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "ROOT", tmp_path)
    (tmp_path / "logs" / "reimpl").mkdir(parents=True)
    bad = tmp_path / "logs" / "reimpl" / "dep-tree_drive.py"
    bad.write_text("__generation_error__ = 'model failed'\n", encoding="utf-8")

    assert churn._candidate_for("gabotechs__dep-tree") is None


def test_plan_only_result_does_not_replace_executed_state():
    from determinex_pb_churn import record_run_in_state

    state = {
        "runs": {
            "yoav-lavi__melody.f4af9b4": {
                "executed": True,
                "result": {"rc": 124},
            }
        }
    }
    plan_only = {
        "slug": "yoav-lavi__melody.f4af9b4",
        "executed": False,
        "action": {"name": "write-native-reimpl"},
    }

    assert record_run_in_state(state, "yoav-lavi__melody.f4af9b4", plan_only) is False
    assert state["runs"]["yoav-lavi__melody.f4af9b4"]["executed"] is True
    assert state["runs"]["yoav-lavi__melody.f4af9b4"]["result"]["rc"] == 124


def test_executed_events_repair_plan_only_state():
    from determinex_pb_churn import merge_executed_events_into_state

    slug = "yoav-lavi__melody.f4af9b4"
    state = {
        "runs": {
            slug: {
                "slug": slug,
                "executed": False,
                "action": {"name": "write-native-reimpl"},
            }
        }
    }
    events = [
        {
            "slug": slug,
            "executed": True,
            "ts": "2026-06-30T14:43:45+00:00",
            "action": {"name": "write-native-reimpl"},
            "result": {"rc": 124},
        }
    ]

    assert merge_executed_events_into_state(state, events) is True
    assert state["runs"][slug]["executed"] is True
    assert state["runs"][slug]["result"]["rc"] == 124


def test_watch_lock_rejects_live_pid(tmp_path):
    import json
    import os

    from determinex_pb_churn import acquire_watch_lock

    lock = tmp_path / "pb_churn_watch.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}) + "\n", encoding="utf-8")

    locked, fd, reason = acquire_watch_lock(lock)

    assert locked is False
    assert fd is None
    assert "watch lock held" in reason


def test_watch_lock_reclaims_stale_pid(tmp_path, monkeypatch):
    import json
    import os

    import determinex_pb_churn as churn

    lock = tmp_path / "pb_churn_watch.lock"
    lock.write_text(json.dumps({"pid": 42424242}) + "\n", encoding="utf-8")
    monkeypatch.setattr(churn, "_pid_running", lambda pid: False)

    locked, fd, reason = churn.acquire_watch_lock(lock)
    try:
        assert locked is True
        assert fd is not None
        assert reason == ""
        data = json.loads(lock.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
    finally:
        churn.release_watch_lock(fd, lock)


def test_all_queue_cools_down_recent_hold_action():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "ducaale__xh.4a6e44f", "status": "pending_unlock", "official_score_pct": 99.0},
        {"slug": "wfxr__csview.8ac4de0", "status": "pending_unlock", "official_score_pct": 98.0},
    ]
    state = {
        "runs": {
            "ducaale__xh.4a6e44f": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "hold-official-eval"},
                "result": {"rc": None, "skipped": True},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["wfxr__csview.8ac4de0"]


def test_upstream_source_without_spec_extracts_before_reimpl():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "noborus__ov.b96c2ba",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
        }
    )

    action = next_action(ChurnContext(slug=route.slug, route=route, spec_path=None))

    spec = tmp_path / "gabotechs__dep-tree.60a95a2.json"
    spec.write_text("{}", encoding="utf-8")

    assert churn._local_spec_path("gabotechs__dep-tree") == str(spec)


def test_local_spec_path_treats_confirmed_empty_harvest_as_absent(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    empty = tmp_path / "quinn-rs__quinn.bb359cc.json"
    empty.write_text(
        '{"slug": "quinn-rs__quinn.bb359cc", "n_examples": 0, "examples": []}', encoding="utf-8"
    )

    assert churn._local_spec_path("quinn-rs__quinn.bb359cc") is None
    # A placeholder spec WITHOUT the n_examples field stays usable (unknown != empty).
    placeholder = tmp_path / "wfxr__csview.8ac4de0.json"
    placeholder.write_text("{}", encoding="utf-8")
    assert churn._local_spec_path("wfxr__csview.8ac4de0") == str(placeholder)


def test_extract_spec_producing_empty_harvest_cools_down_as_no_progress(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    (tmp_path / "quinn-rs__quinn.bb359cc.json").write_text(
        '{"n_examples": 0, "examples": []}', encoding="utf-8"
    )

    now = dt.datetime(2026, 7, 10, 2, 0, tzinfo=dt.UTC)
    run = {
        "executed": True,
        "ts": now.isoformat(),
        "action": {"name": "extract-spec"},
        "result": {"rc": 0},
    }
    # Empty harvest -> no usable spec -> the rc=0 extract pass made no progress.
    assert churn.should_cool_down_run(run, slug="quinn-rs__quinn.bb359cc", now=now)

    # A successful harvest with real examples stays eligible for the next stage.
    (tmp_path / "lz4__lz4.1519f46.json").write_text(
        '{"n_examples": 377, "examples": [{"test": "t"}]}', encoding="utf-8"
    )
    assert not churn.should_cool_down_run(run, slug="lz4__lz4.1519f46", now=now)


def test_candidate_for_skips_generation_error_placeholder(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "ROOT", tmp_path)
    (tmp_path / "logs" / "reimpl").mkdir(parents=True)
    bad = tmp_path / "logs" / "reimpl" / "dep-tree_drive.py"
    bad.write_text("__generation_error__ = 'model failed'\n", encoding="utf-8")

    assert churn._candidate_for("gabotechs__dep-tree") is None


def test_plan_only_result_does_not_replace_executed_state():
    from determinex_pb_churn import record_run_in_state

    state = {
        "runs": {
            "yoav-lavi__melody.f4af9b4": {
                "executed": True,
                "result": {"rc": 124},
            }
        }
    }
    plan_only = {
        "slug": "yoav-lavi__melody.f4af9b4",
        "executed": False,
        "action": {"name": "write-native-reimpl"},
    }

    assert record_run_in_state(state, "yoav-lavi__melody.f4af9b4", plan_only) is False
    assert state["runs"]["yoav-lavi__melody.f4af9b4"]["executed"] is True
    assert state["runs"]["yoav-lavi__melody.f4af9b4"]["result"]["rc"] == 124


def test_executed_events_repair_plan_only_state():
    from determinex_pb_churn import merge_executed_events_into_state

    slug = "yoav-lavi__melody.f4af9b4"
    state = {
        "runs": {
            slug: {
                "slug": slug,
                "executed": False,
                "action": {"name": "write-native-reimpl"},
            }
        }
    }
    events = [
        {
            "slug": slug,
            "executed": True,
            "ts": "2026-06-30T14:43:45+00:00",
            "action": {"name": "write-native-reimpl"},
            "result": {"rc": 124},
        }
    ]

    assert merge_executed_events_into_state(state, events) is True
    assert state["runs"][slug]["executed"] is True
    assert state["runs"][slug]["result"]["rc"] == 124


def test_watch_lock_rejects_live_pid(tmp_path):
    import json
    import os

    from determinex_pb_churn import acquire_watch_lock

    lock = tmp_path / "pb_churn_watch.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}) + "\n", encoding="utf-8")

    locked, fd, reason = acquire_watch_lock(lock)

    assert locked is False
    assert fd is None
    assert "watch lock held" in reason


def test_watch_lock_reclaims_stale_pid(tmp_path, monkeypatch):
    import json
    import os

    import determinex_pb_churn as churn

    lock = tmp_path / "pb_churn_watch.lock"
    lock.write_text(json.dumps({"pid": 42424242}) + "\n", encoding="utf-8")
    monkeypatch.setattr(churn, "_pid_running", lambda pid: False)

    locked, fd, reason = churn.acquire_watch_lock(lock)
    try:
        assert locked is True
        assert fd is not None
        assert reason == ""
        data = json.loads(lock.read_text(encoding="utf-8"))
        assert data["pid"] == os.getpid()
    finally:
        churn.release_watch_lock(fd, lock)


def test_all_queue_cools_down_recent_hold_action():
    from determinex_pb_churn import queue_from_eval_rows

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "ducaale__xh.4a6e44f", "status": "pending_unlock", "official_score_pct": 99.0},
        {"slug": "wfxr__csview.8ac4de0", "status": "pending_unlock", "official_score_pct": 98.0},
    ]
    state = {
        "runs": {
            "ducaale__xh.4a6e44f": {
                "executed": True,
                "ts": now.isoformat(),
                "action": {"name": "hold-official-eval"},
                "result": {"rc": None, "skipped": True},
            }
        }
    }

    assert queue_from_eval_rows(rows, state, now=now) == ["wfxr__csview.8ac4de0"]


def test_upstream_source_without_spec_extracts_before_reimpl():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "noborus__ov.b96c2ba",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
        }
    )

    action = next_action(ChurnContext(slug=route.slug, route=route, spec_path=None))

    assert action.name == "extract-spec"
    assert action.official_eval is False
    assert "pb_bulk_spec.py" in action.command
    assert "pb_eval_unified.py" not in action.command


def test_stale_needs_spec_route_with_existing_spec_and_candidate_runs_oracle():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "astaxie__bat",
            "engine": "extract-spec-first",
            "source_shape": {"class": "unknown", "source_files": 0},
        }
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/astaxie__bat.17d1080.json",
            candidate_path="corpus/programbench/per_tool_overrides/astaxie__bat",
        )
    )

    assert action.name == "local-oracle"
    assert "determinex_local_oracle.py" in action.command
    assert "pb_bulk_spec.py" not in action.command


def test_stale_needs_spec_route_with_existing_spec_runs_reimpl(monkeypatch):
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    monkeypatch.setenv("DETERMINEX_PB_CHURN_ALLOW_BROAD_CLOUD", "1")

    route = route_from_corpus(
        {
            "slug": "astaxie__bat",
            "engine": "extract-spec-first",
            "source_shape": {"class": "unknown", "source_files": 0},
        }
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            model="gemini-3.1-flash-lite",
            spec_path="corpus/programbench/specs/astaxie__bat.17d1080.json",
        )
    )

    assert action.name == "write-native-reimpl"
    assert "--no-decompose" in action.command
    assert "pb_bulk_spec.py" not in action.command


def test_upstream_source_with_spec_runs_free_reimpl_no_official():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "noborus__ov.b96c2ba",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
            "spec": {
                "path": "corpus/programbench/specs/noborus__ov.b96c2ba.json",
                "language": "go",
            },
        }
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/noborus__ov.b96c2ba.json",
            model="local/qwen2.5-coder:3b",
        )
    )

    assert action.name == "write-native-reimpl"
    assert action.official_eval is False
    assert "determinex_reimpl_drive.py" in action.command
    assert "--models local/qwen2.5-coder:3b" in action.command
    assert "--no-official" in action.command


def test_cloud_reimpl_holds_broad_spec_by_default(tmp_path, monkeypatch):
    import determinex_pb_churn as churn
    from determinex_pb_corpus_router import route_from_corpus

    spec = tmp_path / "ast-grep.json"
    spec.write_text(
        '{"language": "python", "n_examples": 250, "examples": [{"test": "t"}]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("DETERMINEX_PB_CHURN_ALLOW_BROAD_CLOUD", raising=False)

    route = route_from_corpus(
        {
            "slug": "ast-grep__ast-grep.dde0fe0",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
            "spec": {"path": str(spec), "language": "python"},
        }
    )

    action = churn.next_action(
        churn.ChurnContext(
            slug=route.slug,
            route=route,
            model="huggingface/Qwen/Qwen2.5-Coder-32B-Instruct",
            spec_path=str(spec),
            k=8,
            rounds=3,
        )
    )

    assert action.name == "hold-low-roi-cloud-reimpl"
    assert action.command == ""
    assert "250 examples" in action.reason


def test_cloud_reimpl_allows_small_spec(tmp_path, monkeypatch):
    import determinex_pb_churn as churn
    from determinex_pb_corpus_router import route_from_corpus

    spec = tmp_path / "xh.json"
    spec.write_text(
        '{"language": "python", "n_examples": 18, "examples": [{"test": "t"}]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("DETERMINEX_PB_CHURN_ALLOW_BROAD_CLOUD", raising=False)

    route = route_from_corpus(
        {
            "slug": "ducaale__xh.4a6e44f",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 10},
            "spec": {"path": str(spec), "language": "python"},
        }
    )

    action = churn.next_action(
        churn.ChurnContext(
            slug=route.slug,
            route=route,
            model="huggingface/Qwen/Qwen2.5-Coder-32B-Instruct",
            spec_path=str(spec),
            k=8,
            rounds=3,
        )
    )

    assert action.name == "write-native-reimpl"
    assert "determinex_reimpl_drive.py" in action.command


def test_upstream_source_with_spec_and_candidate_runs_local_oracle_before_reimpl():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "yoav-lavi__melody.f4af9b4",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 68},
            "spec": {
                "path": "corpus/programbench/specs/yoav-lavi__melody.f4af9b4.json",
                "language": "python",
            },
        }
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/yoav-lavi__melody.f4af9b4.json",
            candidate_path="logs/reimpl/melody_drive.py",
        )
    )

    assert action.name == "local-oracle"
    assert action.official_eval is False
    assert "determinex_local_oracle.py" in action.command
    assert "melody_drive.py" in action.command
    assert "determinex_reimpl_drive.py" not in action.command


def test_gemini_reimpl_uses_monolithic_cloud_call_not_station_conveyor(monkeypatch):
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    monkeypatch.setenv("DETERMINEX_PB_CHURN_ALLOW_BROAD_CLOUD", "1")

    route = route_from_corpus(
        {
            "slug": "rust-ethereum__ethabi.b1710ad",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 20},
            "spec": {"path": "corpus/programbench/specs/rust-ethereum__ethabi.b1710ad.json"},
        }
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            model="gemini-3.1-flash-lite",
            spec_path="corpus/programbench/specs/rust-ethereum__ethabi.b1710ad.json",
        )
    )

    assert action.name == "write-native-reimpl"
    assert "--no-decompose" in action.command
    assert action.timeout_s == 240


def test_local_reimpl_keeps_station_conveyor():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "rust-ethereum__ethabi.b1710ad",
            "engine": "native-reimpl-loop",
            "source_shape": {"class": "upstream-source-prohibited", "source_files": 20},
            "spec": {"path": "corpus/programbench/specs/rust-ethereum__ethabi.b1710ad.json"},
        }
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            model="qwen2.5-coder:3b",
            spec_path="corpus/programbench/specs/rust-ethereum__ethabi.b1710ad.json",
        )
    )

    assert action.name == "write-native-reimpl"
    assert "--no-decompose" not in action.command
    assert action.timeout_s == 7200


def test_oracle_tail_runs_local_oracle_not_official_eval():
    from determinex_pb_churn import ChurnContext, next_action
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

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/wfxr__csview.8ac4de0.json",
            candidate_path="logs/reimpl/csview_drive.py",
        )
    )

    assert action.name == "local-oracle"
    assert action.official_eval is False
    assert "determinex_local_oracle.py" in action.command
    assert "pb_eval_unified.py" not in action.command


def test_native_source_candidate_is_staged_for_local_oracle(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "ROOT", tmp_path)
    source = tmp_path / "logs" / "reimpl" / "csview_drive.py"
    source.parent.mkdir(parents=True)
    source.write_text("use std::env;\nfn main() { let _ = env::args(); }\n", encoding="utf-8")

    staged = Path(churn._candidate_for_oracle(str(source), "rust", "wfxr__csview.8ac4de0"))

    assert staged.is_dir()
    assert (staged / "main.rs").read_text(encoding="utf-8").startswith("use std::env;")
    assert "rustc -O -o executable main.rs" in (staged / "compile.sh").read_text(encoding="utf-8")


def test_official_eval_uses_staged_native_source_file(tmp_path):
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    staged = tmp_path / "candidate"
    staged.mkdir()
    (staged / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (staged / "compile.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    route = route_from_corpus(
        {
            "slug": "wfxr__csview.8ac4de0",
            "engine": "spec-local-oracle",
            "source_shape": {"class": "reimpl-candidate", "source_files": 1},
            "spec": {"path": "corpus/programbench/specs/wfxr__csview.8ac4de0.json"},
        },
        oracle_result={"passed": 117, "total": 117},
    )

    action = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/wfxr__csview.8ac4de0.json",
            candidate_path=str(staged),
            allow_official=True,
            lang="rust",
        )
    )

    assert action.name == "official-eval"
    assert "main.rs" in action.command
    assert "--lang rust" in action.command


def test_oracle_green_holds_official_eval_unless_allowed():
    from determinex_pb_churn import ChurnContext, next_action
    from determinex_pb_corpus_router import route_from_corpus

    route = route_from_corpus(
        {
            "slug": "ducaale__xh.4a6e44f",
            "engine": "spec-local-oracle",
            "source_shape": {"class": "reimpl-candidate", "source_files": 3},
            "spec": {"path": "corpus/programbench/specs/ducaale__xh.4a6e44f.json"},
        },
        oracle_result={"passed": 12, "total": 12},
    )

    held = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/ducaale__xh.4a6e44f.json",
            candidate_path="logs/reimpl/xh_drive.py",
            allow_official=False,
        )
    )
    allowed = next_action(
        ChurnContext(
            slug=route.slug,
            route=route,
            spec_path="corpus/programbench/specs/ducaale__xh.4a6e44f.json",
            candidate_path="logs/reimpl/xh_drive.py",
            allow_official=True,
        )
    )

    assert held.name == "hold-official-eval"
    assert held.official_eval is False
    assert allowed.name == "official-eval"
    assert allowed.official_eval is True
    assert "determinex_pb_official_eval.py" in allowed.command


def test_handoff_line_is_raw_evidence_not_lock_claim():
    from determinex_pb_churn import ChurnAction, format_handoff_event

    line = format_handoff_event(
        slug="noborus__ov.b96c2ba",
        action=ChurnAction(
            name="write-native-reimpl",
            command="python scripts/determinex_reimpl_drive.py noborus__ov.b96c2ba --no-official",
            reason="native reimpl required",
        ),
        rc=0,
        log_path="logs/pb_churn.log",
    )

    assert "slug=noborus__ov.b96c2ba" in line
    assert "action=write-native-reimpl" in line
    assert "rc=0" in line
    assert "LOCKED" not in line


def test_reimpl_model_ladder_accepts_ollama_tags_with_colons():
    from determinex_pb_reimpl import parse_model_ladder

    ladder = parse_model_ladder(
        "local/qwen2.5-coder:7b-instruct,local/qwen2.5-coder:3b,deepseek-chat:3:2"
    )

    assert ladder == [
        ("local/qwen2.5-coder:7b-instruct", 1, 1.0),
        ("local/qwen2.5-coder:3b", 1, 1.0),
        ("deepseek-chat", 3, 2.0),
    ]


def test_reimpl_model_ladder_keeps_local_deepseek_coder_as_ollama_model():
    from determinex_pb_reimpl import parse_model_ladder, uses_raw_deepseek_api

    ladder = parse_model_ladder("local/deepseek-coder-v2:16b,deepseek-chat:3:2")

    assert ladder[0] == ("local/deepseek-coder-v2:16b", 1, 1.0)
    assert uses_raw_deepseek_api(ladder[0][0]) is False
    assert uses_raw_deepseek_api(ladder[1][0]) is True


def test_reimpl_gemini_models_use_raw_gemini_api():
    from determinex_pb_reimpl import uses_raw_gemini_api

    assert uses_raw_gemini_api("gemini-3.1-flash-lite") is True
    assert uses_raw_gemini_api("gemini/gemini-3.1-flash-lite") is True
    assert uses_raw_gemini_api("local/gemini-pretend") is False


def test_reimpl_gemini_generator_requires_key(monkeypatch):
    import determinex_pb_reimpl as reimpl

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(reimpl, "_api_key", lambda name: "")

    gen = reimpl.gemini_generator("gemini-3.1-flash-lite")

    assert "GEMINI_API_KEY" in gen("prompt", 0.2)


def test_reimpl_generation_error_text_is_not_candidate():
    import determinex_pb_reimpl as reimpl

    assert reimpl._is_generation_error_text("__generation_error__: HTTP Error 429") is True
    assert reimpl._is_generation_error_text("print('ok')") is False


def test_reimpl_gemini_generator_posts_generate_content(monkeypatch):
    import json

    import determinex_pb_reimpl as reimpl

    captured = {}

    def fake_post(url, headers, data, *, deadline, attempts):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json.loads(data.decode("utf-8"))
        captured["deadline"] = deadline
        captured["attempts"] = attempts
        return {"candidates": [{"content": {"parts": [{"text": "```python\nprint(1)\n```"}]}}]}

    monkeypatch.setattr(
        reimpl, "_api_key", lambda name: "test-key" if name == "GEMINI_API_KEY" else ""
    )
    monkeypatch.setattr(reimpl, "_post_json_hard", fake_post)

    gen = reimpl.gemini_generator("gemini-3.1-flash-lite")

    assert gen("write code", 0.3).startswith("```python")
    assert "models/gemini-3.1-flash-lite:generateContent" in captured["url"]
    assert captured["url"].endswith("?key=test-key")
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["body"]["generationConfig"]["temperature"] == 0.3
    assert captured["body"]["contents"][0]["parts"][0]["text"] == "write code"


_LOCAL_LADDER = "ollama/qwen2.5-coder:7b-instruct:1:1,ollama/qwen2.5-coder:14b-instruct:2:3"


def test_churn_default_model_is_local_only_unless_cloud_explicitly_allowed(tmp_path, monkeypatch):
    # 2026-07-02: the free Gemini lane forces k=1/rounds=1 + a 240s timeout to survive
    # rate limits, which disables VerifiedSearch amplification. Local is now the default
    # even when a Gemini key is present; cloud requires an explicit opt-in. The local
    # lane is the 7b->14b ESCALATION LADDER (router semantics: 7b clears the cheap bulk
    # fully on-GPU, 14b only the missed tail), not a flat single model.
    import determinex_pb_churn as churn

    monkeypatch.delenv("DETERMINEX_PB_CHURN_MODEL", raising=False)
    monkeypatch.delenv("DETERMINEX_PB_CHURN_ALLOW_CLOUD", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # OPENROUTER_API_KEY leaks into os.environ for the whole pytest process via
    # determinex_providers._load_env_once() reading the real repo .env at import time --
    # must be cleared per-test or this false-positives into the openrouter lane.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(churn, "ROOT", tmp_path)
    assert churn.default_model_ladder() == _LOCAL_LADDER

    monkeypatch.setenv("GEMINI_API_KEY", "present")
    assert churn.default_model_ladder() == _LOCAL_LADDER

    monkeypatch.setenv("DETERMINEX_PB_CHURN_ALLOW_CLOUD", "1")
    assert churn.default_model_ladder() == f"gemini-3.1-flash-lite,{_LOCAL_LADDER}"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("GOOGLE_API_KEY=present\n", encoding="utf-8")
    assert churn.default_model_ladder() == f"gemini-3.1-flash-lite,{_LOCAL_LADDER}"


def test_churn_openrouter_lane_keeps_local_ladder_fallback(tmp_path, monkeypatch):
    import determinex_pb_churn as churn

    monkeypatch.delenv("DETERMINEX_PB_CHURN_MODEL", raising=False)
    monkeypatch.delenv("DETERMINEX_PB_CHURN_ALLOW_CLOUD", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "present")
    monkeypatch.setattr(churn, "ROOT", tmp_path)
    assert churn.default_model_ladder() == f"openrouter/qwen/qwen3-coder:free,{_LOCAL_LADDER}"


def test_reimpl_ollama_generator_defaults_to_unload_after_call(monkeypatch):
    import json
    import urllib.request

    import determinex_pb_reimpl as reimpl

    captured = {}

    class _Resp:
        def read(self):
            return b'{"response":"ok"}'

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.delenv("DETERMINEX_REIMPL_OLLAMA_KEEP_ALIVE", raising=False)
    monkeypatch.setattr(reimpl, "_model_ctx_len", lambda model, host: 32768)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    gen = reimpl.ollama_generator("qwen2.5-coder:7b-instruct", host="http://ollama")

    assert gen("prompt", 0.2) == "ok"
    assert captured["body"]["keep_alive"] == "0"


def test_reimpl_ollama_generator_keep_alive_can_be_overridden(monkeypatch):
    import json
    import urllib.request

    import determinex_pb_reimpl as reimpl

    captured = {}

    class _Resp:
        def read(self):
            return b'{"response":"ok"}'

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(reimpl, "_model_ctx_len", lambda model, host: 32768)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    gen = reimpl.ollama_generator("qwen2.5-coder:7b-instruct", keep_alive="30m")

    assert gen("prompt", 0.2) == "ok"
    assert captured["body"]["keep_alive"] == "30m"


def test_reimpl_ollama_generator_honors_resource_caps(monkeypatch):
    import json
    import urllib.request

    import determinex_pb_reimpl as reimpl

    captured = {}

    class _Resp:
        def read(self):
            return b'{"response":"ok"}'

    def fake_urlopen(req, timeout):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setenv("DETERMINEX_REIMPL_OLLAMA_CTX_CAP", "4096")
    monkeypatch.setenv("DETERMINEX_REIMPL_OLLAMA_OUT_CAP", "1024")
    monkeypatch.setattr(reimpl, "_model_ctx_len", lambda model, host: 32768)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    gen = reimpl.ollama_generator("qwen2.5-coder:3b")

    assert gen("prompt", 0.2) == "ok"
    assert captured["body"]["options"]["num_ctx"] == 4096
    assert captured["body"]["options"]["num_predict"] == 1024


def test_reimpl_drive_reports_error_when_workshop_produces_no_candidate(tmp_path, monkeypatch):
    import determinex_reimpl_drive as drive

    monkeypatch.setattr(drive, "ROOT", tmp_path)
    monkeypatch.setattr(drive.R, "_image_for", lambda slug: "programbench/example:task")
    monkeypatch.setattr(drive.R, "_docs_and_help", lambda image: ("docs", "help"))
    monkeypatch.setattr(drive.OBS, "mine_flags", lambda helptext: [])
    monkeypatch.setattr(drive, "_run_workshop", lambda *args, **kwargs: False)

    result = drive.drive("owner__tool.1234567", official=False, iters=1)

    assert result["error"] == "no candidate"


def test_argv_from_command_strips_posix_quotes_on_windows_paths():
    # LOCK (2026-07-03, first unattended night): _cmd() quotes with shlex.quote
    # (POSIX single quotes); splitting with posix=False on Windows kept the quotes
    # LITERAL in each arg, so every subprocess got "'C:\...\spec.json'" (quotes
    # included) and crashed with OSError 22. All nine first-night local-oracle
    # "rc=1" results were this crash, not oracle verdicts.
    import determinex_pb_churn as churn

    cmd = churn._cmd(
        [
            "python3",
            "scripts/determinex_local_oracle.py",
            r"C:\Dev\Determinex\corpus\programbench\specs\x.json",
            "--spec",
            r"C:\Dev\with space\spec.json",
        ]
    )
    argv = churn._argv_from_command(cmd)
    assert argv[2] == r"C:\Dev\Determinex\corpus\programbench\specs\x.json"
    assert argv[4] == r"C:\Dev\with space\spec.json"
    assert not any(a.startswith("'") or a.endswith("'") for a in argv)


def test_oracle_red_verdict_routes_to_reimpl_not_rejudge(tmp_path):
    # LOCK (2026-07-03): with a candidate present, oracle-red-needs-tail looped on
    # local-oracle forever (re-judging the SAME stale candidate); the only action
    # that invokes a model (write-native-reimpl) was unreachable. A red verdict on
    # a candidate not newer than the verdict must spend the pass on reimpl.
    import determinex_pb_churn as churn

    class _Route:
        verdict = "oracle-red-needs-tail"

    cand = tmp_path / "main.rs"
    cand.write_text("fn main(){}", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text('{"language": "rust"}', encoding="utf-8")
    ctx = churn.ChurnContext(
        slug="t__t.abc",
        route=_Route(),
        spec_path=str(spec),
        candidate_path=str(cand),
        lang="rust",
        oracle_ts="2099-01-01T00:00:00+00:00",  # verdict newer than candidate
    )
    action = churn.next_action(ctx)
    assert action.name == "write-native-reimpl"

    # ...but a candidate written AFTER the verdict is re-validated first
    ctx2 = churn.ChurnContext(
        slug="t__t.abc",
        route=_Route(),
        spec_path=str(spec),
        candidate_path=str(cand),
        lang="rust",
        oracle_ts="2020-01-01T00:00:00+00:00",  # candidate newer than verdict
    )
    action2 = churn.next_action(ctx2)
    assert action2.name == "local-oracle"


def test_timeout_drain_is_bounded(monkeypatch):
    # LOCK (2026-07-03): post-kill communicate() had no timeout -- an orphan
    # grandchild holding the stdout pipe (corpus class: eval_orphan_pipe_hang)
    # wedged the whole churn lane. The drain must abandon the pipes, not hang.
    import subprocess as sp

    import determinex_pb_churn as churn

    class _Proc:
        pid = 4242
        returncode = None
        calls = {"n": 0}

        def communicate(self, timeout=None):
            self.calls["n"] += 1
            if self.calls["n"] == 1:
                raise sp.TimeoutExpired(cmd="x", timeout=1)  # the action timeout
            assert timeout is not None  # the drain MUST be bounded
            raise sp.TimeoutExpired(cmd="x", timeout=timeout)  # pipes never close

        def kill(self):
            pass

    monkeypatch.setattr(churn.subprocess, "Popen", lambda *a, **k: _Proc())
    res = churn.execute_action(
        churn.ChurnAction(name="t", command="python3 -c pass", reason="", timeout_s=1)
    )
    assert res["rc"] == 124
    assert "abandoned" in res["stderr"]


def test_pid_running_dead_pid_returns_false_not_crash():
    # LOCK (2026-07-03, unattended night): on Windows os.kill(dead_pid, 0) raises
    # SystemError ("returned a result with an exception set"), NOT ProcessLookupError,
    # so _pid_running CRASHED on a stale lock -> the supervisor could never reclaim
    # its own watch lock after a restart (every respawn died rc=1). A dead pid must
    # return False cleanly on every platform.
    import determinex_pb_churn as churn

    assert churn._pid_running(999999) is False  # (almost certainly) dead
    assert churn._pid_running(0) is False  # guard
    assert churn._pid_running(-5) is False  # guard
    import os as _os

    assert churn._pid_running(_os.getpid()) is True  # this test process is alive


def test_go_native_compile_sh_inits_module(tmp_path, monkeypatch):
    # LOCK (2026-07-03, unattended night): churn's Go compile.sh ran `go build .`
    # with NO go.mod in the candidate dir, so Go module mode walked up and failed on
    # the repo's own .git ("cannot find main module, but found .git/config") --
    # silently red'ing EVERY Go tool's local oracle. The in-search compile and the
    # official eval already `go mod init` first; this path must too.
    import determinex_pb_churn as churn

    src_name, compile_cmd = churn._NATIVE_SOURCE["go"]
    assert src_name == "main.go"
    assert "go mod init" in compile_cmd  # module root established in the dir
    assert "go build -o executable" in compile_cmd
    # and _candidate_for_oracle must bake that into the generated compile.sh
    monkeypatch.setattr(churn, "ROOT", tmp_path)
    gof = tmp_path / "cand.go"
    gof.write_text("package main\nfunc main(){}\n", encoding="utf-8")
    out = churn._candidate_for_oracle(str(gof), "go", "x__y.abc")
    csh = (Path(out) / "compile.sh").read_text(encoding="utf-8")
    assert "go mod init" in csh


def test_executed_run_ts_is_stamped_at_completion(monkeypatch, tmp_path):
    # LOCK (2026-07-03): the cooldown ts was stamped at run START, but a reimpl runs
    # up to 2h -- longer than the 90-min cooldown -- so an always-times-out hard tool
    # (atlas) was already "past cooldown" the instant it finished, never yielding. The
    # executed-run ts must reflect COMPLETION so the yield window is real.
    import time as _t

    import determinex_pb_churn as churn

    stamps = []
    real_now = churn._now

    def _slow_exec(action):
        _t.sleep(0.05)
        stamps.append(("during", real_now()))
        return {"rc": 124, "stdout": "", "stderr": "timeout", "skipped": False}

    monkeypatch.setattr(churn, "execute_action", _slow_exec)
    monkeypatch.setattr(churn, "acquire_lease", lambda *a, **k: (True, None))
    monkeypatch.setattr(churn, "release_lease", lambda *a, **k: None)
    # ISOLATION (2026-07-10): run_slug persists to STATE_PATH/EVENTS_PATH — without
    # patching these, every pytest run on the box appended a fake t__t.abc run to the
    # PRODUCTION churn state/events (7 phantom write-native-reimpl entries found live).
    monkeypatch.setattr(churn, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(churn, "EVENTS_PATH", tmp_path / "events.jsonl")

    class _Ans(dict):
        pass

    monkeypatch.setattr(churn, "ask_corpus", lambda s: {"slug": s}, raising=False)
    # Drive a minimal run_slug through a stubbed router/next_action:
    import types

    fake = types.SimpleNamespace(
        verdict="needs-native-reimpl", to_dict=lambda: {"verdict": "needs-native-reimpl"}
    )
    monkeypatch.setattr(churn, "load_oracle_result", lambda s: None)
    monkeypatch.setattr(churn, "_local_spec_path", lambda s, a=None: str(tmp_path / "s.json"))
    (tmp_path / "s.json").write_text('{"language":"go"}', encoding="utf-8")
    monkeypatch.setattr(churn, "_candidate_for", lambda s, a=None: str(tmp_path / "c"))
    monkeypatch.setattr(churn, "_candidate_for_oracle", lambda *a, **k: str(tmp_path / "c"))
    import determinex_pb_corpus_router as router

    monkeypatch.setattr(router, "route_from_corpus", lambda *a, **k: fake)
    import determinex_pb_ask_corpus as ask

    monkeypatch.setattr(ask, "ask_corpus", lambda s: {"slug": s})
    monkeypatch.setattr(
        churn,
        "next_action",
        lambda ctx: churn.ChurnAction(
            name="write-native-reimpl", command="x", reason="r", timeout_s=1
        ),
    )

    t0 = real_now()
    ev = churn.run_slug(
        "t__t.abc",
        execute=True,
        model="m",
        allow_official=False,
        append_to_handback=False,
        worker="w",
        lease_ttl_s=10,
        iters=1,
        fuzz=1,
        k=1,
        rounds=1,
    )
    # the recorded ts must be >= the moment execution was running (completion-stamped)
    assert ev.get("ts") and ev["ts"] >= stamps[0][1]


def test_test_oracle_snapshot_root_is_portable(monkeypatch, tmp_path):
    # LOCK (2026-07-03): determinex_test_oracle hardcoded the Linux /root/.cache HF path,
    # so seed_corpus pulled 0 official-test inputs on the Windows dev box -> the oracle
    # never deepened past the front-of-suite literal examples ('million examples of the
    # front, not the end'). Roots must resolve portably (HF_HOME / ~/.cache / override).
    import importlib

    import determinex_test_oracle as TO

    importlib.reload(TO)
    fake = tmp_path / "hub" / "datasets--programbench--ProgramBench-Tests" / "snapshots"
    fake.mkdir(parents=True)
    monkeypatch.setenv("DETERMINEX_PB_TESTS_SNAPSHOT", str(fake))
    roots = TO._hf_snapshot_roots()
    assert str(fake) in roots  # explicit override honored
    # and HF_HOME is honored too
    monkeypatch.delenv("DETERMINEX_PB_TESTS_SNAPSHOT", raising=False)
    hf = tmp_path / "hfhome"
    (hf / "hub" / "datasets--programbench--ProgramBench-Tests" / "snapshots").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(hf))
    assert any("hfhome" in r for r in TO._hf_snapshot_roots())


def test_breadth_touch_key_is_slug_variant_aware(tmp_path, monkeypatch):
    # LOCK (2026-07-03): the queue yields SHORT slugs (`bore`) but state records FULL
    # slugs (`ekzhang__bore.8e059cd`). A naive runs.get(slug) saw every short-slug tool
    # as never-touched and kept re-surfacing it at the front -- defeating the breadth
    # bias (the "we keep doing the same tools" bug). Touch ranking must resolve variants.
    import determinex_pb_churn as churn

    monkeypatch.setattr(churn, "SPECS", tmp_path)
    monkeypatch.setattr(churn, "ROOT", tmp_path)

    now = dt.datetime(2026, 6, 30, 12, 0, tzinfo=dt.UTC)
    rows = [
        {"slug": "bore", "status": "pending_unlock", "official_score_pct": 100.0},
        {"slug": "never-touched-tool", "status": "pending_unlock", "official_score_pct": 10.0},
    ]
    # recorded under the FULL slug, off-cooldown (25h ago), rc=0 so not cooldown-blocked
    old = (now - dt.timedelta(hours=25)).isoformat()
    state = {
        "runs": {
            "ekzhang__bore.8e059cd": {
                "executed": True,
                "ts": old,
                "action": {"name": "local-oracle"},
                "result": {"rc": 0},
                "oracle_result_saved": {"passed": 5, "total": 10},
            }
        }
    }
    q = churn.queue_from_eval_rows(rows, state, now=now, cooldown_s=5400)
    # `bore` must be recognized as TOUCHED (via its full-slug run) and sort BEHIND the
    # genuinely never-touched tool -- not treated as fresh and pinned to the front.
    assert q == ["never-touched-tool", "bore"]
