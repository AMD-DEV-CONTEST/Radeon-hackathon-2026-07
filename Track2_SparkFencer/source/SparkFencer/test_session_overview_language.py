from webui.pipeline import _session_overview_markdown


def _events():
    return {
        "video": {"duration_sec": 180},
        "phrases": [{}, {}],
        "stats": {
            "left": {"coverage": 0.78, "footwork": {"advance_count": 85, "retreat_count": 100, "lunge_count": 47, "peak_speed_ms": 9.0}, "attack_count": 86, "defense_count": 12},
            "right": {"coverage": 0.80, "footwork": {"advance_count": 103, "retreat_count": 96, "lunge_count": 27, "peak_speed_ms": 9.0}, "attack_count": 30, "defense_count": 39},
        },
        "distance": {"available": True, "mean_m": 6.43, "min_m": 0.433, "max_m": 11.154},
        "style": {
            "profiles": {"left": {"style_label": "机动控距型"}, "right": {"style_label": "防守反击型"}},
            "comparison": {"initiative": "left", "territory_control": "right", "aggression_gap": 0.03,
                           "summary": "左方的中文历史摘要"},
        },
    }


def test_session_overview_uses_english_for_structured_archive_data():
    overview = _session_overview_markdown(_events(), "session-a", "en")
    assert "Duration 180s · Phrases 2" in overview
    assert "**Left fencer** [Distance manager]" in overview
    assert "Tactical comparison" in overview
    assert "左方" not in overview
    assert "中文历史摘要" not in overview


def test_session_overview_keeps_chinese_when_requested():
    overview = _session_overview_markdown(_events(), "session-a", "zh")
    assert "时长 180s · 回合 2" in overview
    assert "**左方**【机动控距型】" in overview
