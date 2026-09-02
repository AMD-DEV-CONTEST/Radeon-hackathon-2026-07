from radeon_home.orchestrator import preview_task
from radeon_home.semantic_world import observe_room


def test_semantic_observation_is_explicitly_simulated() -> None:
    result = observe_room()
    assert result["source"] == "simulator_ground_truth_adapter"
    assert {item["object_id"] for item in result["objects"]} >= {"trash", "cup", "tray"}


def test_preview_connects_language_perception_and_navigation() -> None:
    result = preview_task("Put the trash in the bin and the keys on the tray.")
    assert result["mode"] == "preview_only"
    assert len(result["routes"]) == 2
    assert result["routes"][0]["pickup_path"]
    assert {event["phase"] for event in result["events"]} >= {
        "perceive", "navigate", "grasp", "place"
    }
