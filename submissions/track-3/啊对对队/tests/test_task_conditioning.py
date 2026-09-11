from parcel_sorter.task_conditioning import (
    build_conditioned_task,
    select_balanced_train_episodes,
)


def test_conditioned_task_names_profile_and_destination() -> None:
    assert build_conditioned_task("mailing_tube", "left") == (
        "Pick the mailing tube and place it in the left sorting bin."
    )


def test_balancing_caps_repetition_and_downsamples_deterministically() -> None:
    assignments = [
        {
            "dataset_episode_index": index,
            "profile_id": "small_carton",
            "split": "train",
        }
        for index in range(5)
    ] + [
        {
            "dataset_episode_index": 10,
            "profile_id": "mailing_tube",
            "split": "train",
        },
        {
            "dataset_episode_index": 99,
            "profile_id": "mailing_tube",
            "split": "heldout",
        },
    ]
    selected = select_balanced_train_episodes(
        assignments,
        target_per_profile=3,
        max_repeats=2,
        seed=11,
    )
    small = [item for item in selected if item.profile_id == "small_carton"]
    tubes = [item for item in selected if item.profile_id == "mailing_tube"]
    assert len(small) == 3
    assert len({item.source_episode_index for item in small}) == 3
    assert [(item.source_episode_index, item.repeat_ordinal) for item in tubes] == [
        (10, 0),
        (10, 1),
    ]
