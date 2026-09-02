"""The direction grid narrows as the interview answers arrive, and says why.

Ryan, 2026-08-03, looking at the setup screen: *"that top part of the setup, where it asks and
all, needs to change to where they can be opened or selected based on the answers and it
narrows down as the user answers questions."*

Two defects were visible in one screenshot: **CLI Tool appeared twice**, and the grid was
computed once at discovery and never touched — so a user could answer "terminal only, no
browser" and keep staring at "Web + Mobile App, 3–6 weeks, high". The cards asked for a
decision and then ignored it.

The narrowing is DETERMINISTIC on purpose. A model could hallucinate a card away, and the user
would watch their own answer remove the wrong one — worse than no narrowing at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from idea_oracle import (  # noqa: E402
    _PATH_TEMPLATES,
    _dedupe_paths,
    _merge_intent_paths,
    narrow_paths,
)

ALL = ["Web + Mobile App", "Web App", "Mobile App", "Backend API", "CLI Tool", "Data Pipeline"]


def paths(*names):
    return [dict(_PATH_TEMPLATES[n]) for n in (names or ALL)]


def names(result):
    return [p["name"] for p in result["paths"]]


# ── the duplicate card ──────────────────────────────────────────────────────────────────


def test_the_same_direction_never_appears_twice():
    """Seen on screen: two identical CLI Tool cards, same description, same build time."""
    dupes = [{"name": "CLI Tool"}, {"name": "CLI Tool"}, {"name": "Backend API"}]
    assert [p["name"] for p in _dedupe_paths(dupes)] == ["CLI Tool", "Backend API"]


def test_dedupe_runs_even_when_no_intent_regex_matches():
    """The actual bug. Dedup lived inside `_merge_intent_paths`, which EARLY-RETURNS when the
    idea matches no intent pattern -- so on an unrecognised idea the model's raw paths passed
    through untouched and a doubled name rendered twice."""
    out = _merge_intent_paths(
        {"paths": [{"name": "CLI Tool"}, {"name": "CLI Tool"}]},
        "something no regex in this module knows about",
    )
    assert [p["name"] for p in out["paths"]] == ["CLI Tool"]


def test_a_differently_named_direction_is_not_collapsed():
    """"Command-Line Tool" is the same thing; "Calendar Merge CLI Tool" is not."""
    out = _dedupe_paths(
        [{"name": "CLI Tool"}, {"name": "Command-Line Tool"}, {"name": "Calendar Merge CLI Tool"}]
    )
    assert [p["name"] for p in out] == ["CLI Tool", "Calendar Merge CLI Tool"]


# ── narrowing on the answers ────────────────────────────────────────────────────────────


def test_saying_it_is_terminal_only_removes_the_web_and_mobile_directions():
    r = narrow_paths(paths(), "a thing that merges calendars", ["it is a terminal tool, no browser at all"])
    assert "CLI Tool" in names(r)
    assert "Web App" not in names(r)
    assert "Mobile App" not in names(r)


def test_a_negated_component_also_removes_the_composite_containing_it():
    """"no mobile app" removed `Mobile App` and left `Web + Mobile App` standing -- the same
    direction wearing a longer name, so the user's answer visibly did nothing."""
    r = narrow_paths(paths(), "a scheduling product", ["a web dashboard for the team, no mobile app"])
    assert "Web App" in names(r)
    assert "Mobile App" not in names(r)
    assert "Web + Mobile App" not in names(r)


def test_nothing_is_removed_before_the_user_has_said_anything():
    r = narrow_paths(paths(), "a thing that merges calendars", [])
    assert len(r["paths"]) == len(ALL)
    assert r["ruled_out"] == []


def test_answers_that_name_no_surface_remove_nothing():
    """Removing everything because the extractor recognised nothing would be inventing a
    decision the user never made."""
    r = narrow_paths(paths(), "a thing", ["I am not sure yet", "whatever you think"])
    assert len(r["paths"]) == len(ALL)


def test_narrowing_never_empties_the_grid():
    """A user cannot choose from nothing. If the rules would remove every direction, they are
    wrong about this idea, not the user."""
    r = narrow_paths(paths("Mobile App"), "x", ["definitely no mobile, no phone, no ios"])
    assert len(r["paths"]) >= 1
    assert "would have removed every direction" in r["reason"]


# ── it must say WHY ─────────────────────────────────────────────────────────────────────


def test_every_removed_card_carries_a_reason():
    """A card that vanishes without explanation reads as a bug, not as the system listening."""
    r = narrow_paths(paths(), "a scheduling product", ["terminal only, no browser"])
    assert r["ruled_out"]
    for x in r["ruled_out"]:
        assert x["name"] and x["why"].strip()


def test_an_explicit_no_is_reported_differently_from_never_mentioned():
    """"You said this is not part of it" and "nothing you have said points at this" are
    different facts, and the second is not a decision the user made."""
    r = narrow_paths(paths(), "a scheduling product", ["a web dashboard, no mobile app"])
    whys = {x["name"]: x["why"] for x in r["ruled_out"]}
    assert "not part of it" in whys.get("Mobile App", "")
    assert any("nothing you have said" in w for n, w in whys.items() if n != "Mobile App")


def test_surviving_directions_are_ordered_by_what_the_user_asked_for():
    r = narrow_paths(paths(), "x", ["a website and a mobile app sharing one account"])
    assert names(r)[0] == "Web + Mobile App"
