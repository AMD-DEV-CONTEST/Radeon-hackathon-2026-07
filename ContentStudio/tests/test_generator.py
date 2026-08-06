from content_studio.core.generator import (
    Generator, WeChatContent, XHSContent, build_material, _parse_json,
)


def test_parse_json_strips_code_fence():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('```\n{"b": 2}\n```') == {"b": 2}
    assert _parse_json('{"c": 3}') == {"c": 3}


def test_parse_json_extracts_from_surrounding_prose():
    assert _parse_json('这是结果：{"title": "T"} 希望你喜欢') == {"title": "T"}


class FakeClient:
    def __init__(self, outputs): self.outputs = list(outputs); self.calls = 0
    def complete_json(self, system, user, images=None):
        self.calls += 1
        out = self.outputs.pop(0)
        return out


def test_build_material_combines_text_ocr_images():
    m = build_material("正文", "图里文字", image_count=2)
    assert "正文" in m and "图里文字" in m and "2" in m


def test_build_material_empty():
    assert build_material("") != ""


def test_generate_wechat_parses_json():
    c = FakeClient(['{"title":"T","summary":"S","body_html":"<p>x</p>","image_captions":["c1"]}'])
    g = Generator(c)
    r = g.generate_wechat("素材")
    assert isinstance(r, WeChatContent)
    assert r.title == "T" and r.summary == "S" and r.body_html == "<p>x</p>"
    assert r.image_captions == ["c1"]
    assert r.fell_back is False
    assert c.calls == 1


def test_generate_wechat_recovers_on_second_try():
    c = FakeClient(["not json", '{"title":"T2"}'])
    r = Generator(c).generate_wechat("素材")
    assert r.title == "T2"
    assert c.calls == 2


def test_generate_wechat_falls_back_when_both_bad():
    c = FakeClient(["not json", "still not json"])
    r = Generator(c).generate_wechat("素材")
    assert r.fell_back is True
    assert "still not json" in r.body_html
    assert c.calls == 2


def test_generate_xhs_parses_json():
    c = FakeClient(['{"title":"T","body":"b","hashtags":["#a"],"cover_text":"封面"}'])
    r = Generator(c).generate_xhs("素材")
    assert isinstance(r, XHSContent)
    assert r.title == "T" and r.body == "b"
    assert r.hashtags == ["#a"] and r.cover_text == "封面"


from content_studio.styles.registry import get_preset


def test_generate_wechat_with_style_and_image_prompts():
    c = FakeClient(['{"title":"T","summary":"S","body_html":"<p>x</p>",'
                    '"image_captions":["c1"],"image_prompts":["a cat","a robot"]}'])
    r = Generator(c).generate_wechat("素材", get_preset("anime"))
    assert r.title == "T"
    assert r.image_prompts == ["a cat", "a robot"]


def test_generate_wechat_without_image_prompts_is_empty_list():
    c = FakeClient(['{"title":"T"}'])
    r = Generator(c).generate_wechat("素材")
    assert r.image_prompts == []
