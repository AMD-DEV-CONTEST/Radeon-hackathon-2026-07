import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import pytest

from nuclear_agent.site import SiteAgent, SiteContext, SiteValidationError


def site_payload(**overrides):
    payload = {
        "site_id": "demo-aquifer-001",
        "event_type": "hypothetical_subsurface_release",
        "radionuclide": "Cs-137",
        "release_pathway": "groundwater",
        "source_description": "Hypothetical maintained release at the aquifer boundary",
        "data_provenance": "demonstration",
        "data_classification": "public",
    }
    payload.update(overrides)
    return payload


def test_site_agent_marks_missing_characterization_as_screening_limitations():
    assessment = SiteAgent().assess(site_payload())
    data = assessment.to_dict()

    assert data["site_id"] == "demo-aquifer-001"
    assert data["screening_only"] is True
    assert "site_specific_kd" in data["missing_critical_data"]
    assert "mineralogy" in data["missing_critical_data"]
    assert data["normalized_context"]["data_provenance"] == "demonstration"
    assert data["warnings"]


def test_site_context_accepts_characterization_and_validates_ranges():
    context = SiteContext.from_dict(
        site_payload(
            mineralogy="illitic sandy soil",
            clay_fraction=0.12,
            ph=6.8,
            cec_cmol_kg=14.0,
            ionic_composition_available=True,
            site_specific_kd_available=True,
        )
    )
    assert context.clay_fraction == 0.12
    assert context.ph == 6.8

    with pytest.raises(SiteValidationError, match="clay_fraction"):
        SiteContext.from_dict(site_payload(clay_fraction=1.2))


def test_site_agent_rejects_unsupported_radionuclide_or_pathway():
    with pytest.raises(SiteValidationError, match="Cs-137"):
        SiteAgent().assess(site_payload(radionuclide="I-131"))
    with pytest.raises(SiteValidationError, match="groundwater"):
        SiteAgent().assess(site_payload(release_pathway="atmosphere"))
