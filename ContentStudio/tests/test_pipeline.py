from PIL import Image

from content_studio.config import AppConfig, ComfyConfig, ImageConfig
from content_studio.core.comfy import ComfyError
from content_studio.core.generator import WeChatContent, XHSContent
from content_studio.core.pipeline import run_pipeline, PipelineResult, BuiltArticle, BuiltXHS, weave_images
from content_studio.styles.registry import get_preset


def _cfg():
    cfg = AppConfig()
    cfg.comfy = ComfyConfig(enabled=True, t2i_count=1)
    cfg.image = ImageConfig()
    return cfg


class FakeGen:
    def __init__(self, wc, xh=None):
        self._wc = wc
        self._xh = xh
    def generate_wechat(self, material, style=None, images=None):
        return self._wc
    def generate_xhs(self, material):
        return self._xh or XHSContent(title="小红书标题", body="正文", hashtags=["#话题"], cover_text="封面")


def _img_file(tmp_path, name="a.png"):
    p = tmp_path / name
    Image.new("RGB", (900, 900), (5, 6, 7)).save(p, "PNG")
    return str(p)


class FakeComfy:
    def style_transfer(self, path, style):
        return Image.new("RGB", (1000, 700), (1, 1, 1))


def test_pipeline_wechat_target_only(tmp_path):
    wc = WeChatContent(title="T", summary="S", body_html="<p>x</p>", image_captions=["c"])
    res = run_pipeline("m", [_img_file(tmp_path)], [get_preset("anime")], _cfg(), FakeGen(wc), FakeComfy())
    assert isinstance(res, PipelineResult)
    assert res.target == "wechat"
    assert res.wechat.title == "T" and res.wechat.images[0].width <= 900
    assert res.xhs.images == [] and res.xhs.title == ""                          # 未生成
    assert res.used_comfyui is True


def test_pipeline_xhs_target_only(tmp_path):
    xh = XHSContent(title="X", body="b", hashtags=["#a"], cover_text="封面")
    res = run_pipeline("m", [_img_file(tmp_path)], [get_preset("anime")], _cfg(),
                       FakeGen(None, xh), FakeComfy(), target="xhs")
    assert res.target == "xhs"
    assert res.xhs.title == "X" and res.xhs.cover_text == "封面"
    assert res.xhs.images[0].size == (1242, 1656)                                # 3:4
    assert res.wechat.images == []                                               # 未生成
    assert res.used_comfyui is True


def test_pipeline_none_style_skips_comfy(tmp_path):
    wc = WeChatContent(title="T")
    class SpyComfy:
        def style_transfer(self, path, style):
            raise AssertionError("无风格不应调 ComfyUI")
    res = run_pipeline("m", [_img_file(tmp_path)], [None], _cfg(), FakeGen(wc), SpyComfy())
    assert res.used_comfyui is False
    assert len(res.wechat.images) == 1


def test_pipeline_mixed_styles(tmp_path):
    wc = WeChatContent(title="T")
    n = {"n": 0}
    class CountComfy:
        def style_transfer(self, path, style):
            n["n"] += 1
            return Image.new("RGB", (1000, 700), (2, 2, 2))
    paths = [_img_file(tmp_path, "a.png"), _img_file(tmp_path, "b.png")]
    res = run_pipeline("m", paths, [get_preset("anime"), None], _cfg(), FakeGen(wc), CountComfy())
    assert n["n"] == 1
    assert res.used_comfyui is True
    assert len(res.wechat.images) == 2


def test_pipeline_per_image_degrade(tmp_path):
    wc = WeChatContent(title="T")
    class BrokenComfy:
        def style_transfer(self, path, style):
            raise ComfyError("down")
    res = run_pipeline("m", [_img_file(tmp_path)], [get_preset("anime")], _cfg(), FakeGen(wc), BrokenComfy())
    assert res.used_comfyui is False
    assert any("原图" in w for w in res.warnings)
    assert len(res.wechat.images) == 1


def test_pipeline_no_comfy_client(tmp_path):
    wc = WeChatContent(title="T")
    res = run_pipeline("m", [_img_file(tmp_path)], [get_preset("anime")], _cfg(), FakeGen(wc), comfy=None)
    assert res.used_comfyui is False
    assert len(res.wechat.images) == 1


def test_pipeline_t2i_generates_extra_images(tmp_path):
    wc = WeChatContent(title="T", image_prompts=["a cat", "a robot"])
    class T2iComfy:
        def style_transfer(self, path, style):
            return Image.new("RGB", (1000, 700), (1, 1, 1))
        def text_to_image(self, prompt, style):
            return Image.new("RGB", (512, 512), (2, 2, 2))
    res = run_pipeline("m", [_img_file(tmp_path)], [None], _cfg(), FakeGen(wc), T2iComfy(), t2i_count=2)
    assert len(res.wechat.images) == 3   # 1 张照片(原图) + 2 张 AI 生成


def test_pipeline_t2i_skipped_without_comfy(tmp_path):
    wc = WeChatContent(title="T", image_prompts=["a cat", "a robot"])
    res = run_pipeline("m", [_img_file(tmp_path)], [None], _cfg(), FakeGen(wc), comfy=None, t2i_count=2)
    assert len(res.wechat.images) == 1   # 没 ComfyUI 就不生成


def test_weave_images_replaces_markers_in_order():
    out = weave_images("A[[IMG]]B[[IMG]]C", ["u1", "u2"])
    assert out.index("u1") < out.index("u2")
    assert "A" in out and "B" in out and "C" in out


def test_weave_images_appends_leftover_images():
    out = weave_images("X[[IMG]]Y", ["u1", "u2", "u3"])
    assert out.count("<img") == 3            # 1 个占位 + 2 张追加
    assert out.index("u1") < out.index("u2") < out.index("u3")


def test_weave_images_no_markers_appends_all():
    out = weave_images("正文", ["u1", "u2"])
    assert out.count("<img") == 2
    assert "正文" in out


def test_weave_images_explicit_index_places_specific_photo():
    out = weave_images("A[[IMG:2]]B[[IMG:1]]C", ["u1", "u2"])
    assert out.index("u2") < out.index("u1")   # [[IMG:2]] 在 [[IMG:1]] 之前出现


def test_weave_images_handles_attr_wrapped_marker():
    out = weave_images('<img src="[[IMG:1]]" alt="x">', ["u1"])
    assert 'src="u1"' in out
    assert "[[IMG" not in out
    assert out.count("<img") == 1
