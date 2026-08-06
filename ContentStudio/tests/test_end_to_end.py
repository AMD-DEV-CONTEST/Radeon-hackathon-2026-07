from pathlib import Path
from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core import exporter, image_pipeline
from content_studio.core.generator import Generator, build_material


class StubClient:
    """模拟 LLM：公众号和小红书各返回固定 JSON。"""
    def __init__(self): self.calls = 0
    def complete_json(self, system, user, images=None):
        self.calls += 1
        if "公众号" in system:
            return '{"title":"公众号标题","summary":"摘要","body_html":"<p>正文</p>","image_captions":["图1"]}'
        return '{"title":"小红书标题","body":"正文✨","hashtags":["#话题"],"cover_text":"封面"}'


def test_end_to_end_material_to_export(tmp_path: Path):
    # 1) 组装素材
    material = build_material("我的素材文字", ocr_text="", image_count=1)
    assert "我的素材文字" in material

    # 2) 生成
    gen = Generator(StubClient())
    wechat = gen.generate_wechat(material)
    xhs = gen.generate_xhs(material)
    assert wechat.title == "公众号标题"
    assert xhs.hashtags == ["#话题"]

    # 3) 图片 + 导出
    imgs = [Image.new("RGB", (1000, 800), (30, 60, 90))]
    art = exporter.export(wechat, xhs, imgs, ImageConfig(), tmp_path / "out")

    # 4) 断言产出齐全
    assert art.wechat_text_path.read_text(encoding="utf-8").startswith("标题：公众号标题")
    assert "小红书标题" in art.xhs_text_path.read_text(encoding="utf-8")
    assert art.wechat_images[0].exists()
    from PIL import Image as PILImage
    assert PILImage.open(art.xhs_images[0]).size == image_pipeline.XHS_COVER_SIZE
    assert PILImage.open(art.wechat_images[0]).size == image_pipeline.WECHAT_COVER_SIZE


def test_one_platform_failure_does_not_block_other():
    class HalfFailingClient:
        def __init__(self): self.n = 0
        def complete_json(self, system, user, images=None):
            self.n += 1
            if "公众号" in system:
                return "### 不是 json ###"   # 两次都坏 -> 降级
            return '{"title":"小红书OK","body":"b","hashtags":[],"cover_text":""}'
    gen = Generator(HalfFailingClient())
    wechat = gen.generate_wechat("素材")
    xhs = gen.generate_xhs("素材")
    assert wechat.fell_back is True          # 公众号降级
    assert xhs.fell_back is False and xhs.title == "小红书OK"   # 小红书正常
