# character-workshop/tests/test_orchestrator.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.orchestrator import JobState, generate_card_job, revise_job


def test_generate_card_job_mock():
    result = generate_card_job(
        user_text="A Void traveler in teal robes carrying a lantern",
        affinity_pref="Void",
        ref_image=None,
        mock=True,
    )
    assert result.state == JobState.READY
    assert result.job_dir.exists()
    assert (result.job_dir / "character.json").exists()
    assert (result.job_dir / "portrait.png").exists()
    assert (result.job_dir / "card.png").exists()
    assert result.card is not None
    assert result.error is None


def test_revise_mock():
    base = generate_card_job("A Mind boy with black hair", affinity_pref="Mind", mock=True)
    rev = revise_job(base.job_id, "change to short golden hair", mock=True)
    assert rev.state == JobState.READY
    assert "golden" in rev.card.appearance or "golden" in rev.card.image_prompt
