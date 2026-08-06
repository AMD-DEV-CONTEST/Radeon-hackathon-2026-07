from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/keep-unpostable-release-jury-v1"
DEFAULT_SUBMISSIONS = PACKET / "submissions"
DEFAULT_OUTPUT = PACKET / "verdict.json"


def canonical_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def load_reviews(directory: Path) -> list[tuple[Path, dict]]:
    paths = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if len(paths) != 5:
        raise SystemExit(f"exactly five independent review JSON files are required; found {len(paths)}")
    rows = []
    for path in paths:
        review = json.loads(path.read_text(encoding="utf-8"))
        supplied = review.get("review_content_sha256")
        unsigned = dict(review)
        unsigned.pop("review_content_sha256", None)
        if supplied != canonical_sha256(unsigned):
            raise SystemExit(f"review digest is invalid: {path}")
        if review.get("schema") != "ProofLaunchKeepUnpostableHumanReleaseReviewV1":
            raise SystemExit(f"review schema is invalid: {path}")
        if review.get("human_attestation") != "independent_source_hidden_generation_route_no_model_judge":
            raise SystemExit(f"human attestation is invalid: {path}")
        rows.append((path, review))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submissions", default=str(DEFAULT_SUBMISSIONS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    submissions = Path(args.submissions).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    for path in (submissions, output.parent):
        try:
            path.relative_to(ROOT)
        except ValueError as error:
            raise SystemExit("review import must stay inside the project") from error

    receipt = json.loads((PACKET / "receipt.json").read_text(encoding="utf-8"))
    mapping = json.loads((PACKET / "private/mapping.json").read_text(encoding="utf-8"))
    expected = {row["reviewer_slot"]: row for row in mapping["mappings"]}
    rows = load_reviews(submissions)
    reviews = [row for _, row in rows]
    if {row["reviewer_slot"] for row in reviews} != set(expected):
        raise SystemExit("reviewer slots do not match the sealed packet")
    if len({row["reviewer_pseudonym"] for row in reviews}) != 5:
        raise SystemExit("five distinct stable human pseudonyms are required")
    for review in reviews:
        slot = review["reviewer_slot"]
        if review["task_sha256"] != expected[slot]["task_sha256"]:
            raise SystemExit(f"review task binding is invalid: {slot}")
        if set(review["axis_scores"]) != {
            "first_three_second_stop_power",
            "value_proposition_recall",
            "platform_nativeness",
            "visual_craft",
            "motion_pacing",
            "audio_naturalness",
            "sound_picture_fit",
            "privacy_boundary_comprehension",
            "qualified_action_clarity",
            "originality_without_imitation",
        }:
            raise SystemExit(f"quality-axis set is invalid: {slot}")
        if any(not isinstance(score, int) or not 1 <= score <= 5 for score in review["axis_scores"].values()):
            raise SystemExit(f"axis score is invalid: {slot}")

    voice_votes: dict[str, int] = {}
    resolved_voice_votes = []
    for review in reviews:
        choice = review["preferred_voice"]
        if choice == "abstain":
            resolved = "abstain"
        else:
            resolved = expected[review["reviewer_slot"]]["voice_mapping"].get(choice)
            if not resolved:
                raise SystemExit(f"voice choice is invalid: {review['reviewer_slot']}")
        resolved_voice_votes.append(resolved)
        voice_votes[resolved] = voice_votes.get(resolved, 0) + 1

    axes = tuple(reviews[0]["axis_scores"])
    medians = {
        axis: float(statistics.median(review["axis_scores"][axis] for review in reviews))
        for axis in axes
    }
    video_yes = sum(review["video_direct_release"] == "yes" for review in reviews)
    carousel_yes = sum(review["carousel_direct_release"] == "yes" for review in reviews)
    blocking_defect_count = sum(review["blocking_defect"] != "none" for review in reviews)
    ranked_voice = sorted(voice_votes.items(), key=lambda item: (-item[1], item[0]))
    voice_winner = ranked_voice[0][0] if ranked_voice and ranked_voice[0][0] != "abstain" and ranked_voice[0][1] >= 4 else None
    release_gate_passed = (
        video_yes == 5
        and carousel_yes == 5
        and blocking_defect_count == 0
        and all(score >= 4.0 for score in medians.values())
        and voice_winner is not None
    )
    verdict = seal(
        {
            "schema": "ProofLaunchKeepUnpostableReleaseVerdictV1",
            "packet_content_sha256": receipt["content_sha256"],
            "review_count": 5,
            "unique_reviewer_count": 5,
            "review_files": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path, _ in rows
            ],
            "video_direct_release_yes_count": video_yes,
            "carousel_direct_release_yes_count": carousel_yes,
            "blocking_defect_count": blocking_defect_count,
            "axis_medians": medians,
            "voice_votes": voice_votes,
            "selected_voice_candidate": voice_winner,
            "release_gate_passed": release_gate_passed,
            "external_publish_executed": False,
            "market_effect_observed": False,
            "named_product_win_observed": False,
            "truth_boundary": (
                "This verdict aggregates five bound human release reviews. A passing gate authorizes only a separate named owner "
                "to consider release; it does not publish, establish named-product superiority, predict organic breakout or prove conversion, retention or revenue."
            ),
        }
    )
    atomic_write_text(output, json.dumps(verdict, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "release_gate_passed": release_gate_passed,
                "selected_voice_candidate": voice_winner,
                "content_sha256": verdict["content_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
