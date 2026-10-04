from pathlib import Path
from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core.exporter import export, format_wechat
from content_studio.core.generator import WeChatContent, XHSContent


def test_export_writes_text_and_images(tmp_path: Path):
    wc = WeChatContent(title="标题", summary="摘要", body_html="<p>正文</p>", image_captions=["c1"])
    xh = XHSContent(title="小红书标题", body="正文", hashtags=["#a"], cover_text="封面")
    imgs = [Image.new("RGB", (900, 900), (20, 20, 20))]
    art = export(wc, xh, imgs, ImageConfig(), tmp_path / "out")
    assert art.wechat_text_path.exists()
    assert art.xhs_text_path.exists()
    assert len(art.wechat_images) == 1
    assert len(art.xhs_images) == 1
    assert all(Path(p).exists() for p in art.wechat_images + art.xhs_images)
    assert "标题" in art.wechat_text_path.read_text(encoding="utf-8")
    assert "小红书标题" in art.xhs_text_path.read_text(encoding="utf-8")
    assert "#a" in art.xhs_text_path.read_text(encoding="utf-8")


def test_export_no_images_still_writes_text(tmp_path: Path):
    wc = WeChatContent(title="T")
    xh = XHSContent(title="X")
    art = export(wc, xh, [], ImageConfig(), tmp_path / "out")
    assert art.wechat_images == [] and art.xhs_images == []
    assert art.wechat_text_path.exists() and art.xhs_text_path.exists()


def test_format_wechat_includes_fallback_marker():
    wc = WeChatContent(title="标题", body_html="<原始返回>", fell_back=True)
    text = format_wechat(wc)
    assert "解析失败" in text
    assert "标题" in text
