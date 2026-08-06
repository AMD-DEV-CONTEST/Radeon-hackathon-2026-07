import pytest
from content_studio.styles.registry import (
    StylePreset, list_presets, get_preset, load_workflow, resolve_style, preset_options, NONE_ID,
)


def test_list_presets_has_all_builtin():
    ids = [p.id for p in list_presets()]
    for sid in ["anime", "cyberpunk", "watercolor", "retro", "minimal", "oil", "ink", "pixel"]:
        assert sid in ids


def test_get_preset_returns_matching():
    p = get_preset("anime")
    assert isinstance(p, StylePreset)
    assert p.id == "anime"
    assert p.llm_tone and p.visual_keywords


def test_get_preset_unknown_raises():
    with pytest.raises(ValueError):
        get_preset("nope")


def test_resolve_style_none_returns_none():
    assert resolve_style(NONE_ID) is None
    assert resolve_style("none") is None


def test_resolve_style_preset_returns_preset():
    assert resolve_style("watercolor").id == "watercolor"


def test_resolve_style_unknown_raises():
    with pytest.raises(ValueError):
        resolve_style("nope")


def test_preset_options_starts_with_none():
    opts = preset_options()
    assert opts[0] == {"id": "none", "name": "无"}
    ids = [o["id"] for o in opts]
    assert "anime" in ids and "pixel" in ids


def test_load_workflow_has_placeholders():
    g = load_workflow("anime.json")
    assert isinstance(g, dict)
    assert any("{positive}" in str(v) for v in g.values())


def test_new_style_workflows_exist_and_have_placeholders():
    for sid in ["watercolor", "retro", "minimal", "oil", "ink", "pixel"]:
        g = load_workflow(f"{sid}.json")
        assert any("{positive}" in str(v) for v in g.values())
        assert any("{input_image}" in str(v) for v in g.values())
