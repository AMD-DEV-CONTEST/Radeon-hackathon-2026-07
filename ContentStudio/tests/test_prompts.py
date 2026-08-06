from content_studio.core.prompts import build_wechat_prompt, build_xhs_prompt


def test_wechat_prompt_contains_material():
    system, user = build_wechat_prompt("我的素材")
    assert "公众号" in system
    assert "json" in system.lower()
    assert "我的素材" in user


def test_xhs_prompt_contains_material():
    system, user = build_xhs_prompt("我的素材")
    assert "小红书" in system
    assert "json" in system.lower()
    assert "我的素材" in user


def test_prompts_return_two_strings():
    for fn in (build_wechat_prompt, build_xhs_prompt):
        system, user = fn("x")
        assert isinstance(system, str) and isinstance(user, str)


from content_studio.styles.registry import get_preset


def test_wechat_prompt_with_style_includes_tone():
    style = get_preset("anime")
    system, user = build_wechat_prompt("我的素材", style)
    assert style.llm_tone in system
    assert "image_prompts" in system
    assert "我的素材" in user
