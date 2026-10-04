from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core import image_pipeline as ip


def _img(w, h, color=(200, 50, 50)):
    return Image.new("RGB", (w, h), color)


def test_to_cover_3_4_size():
    out = ip.to_cover_3_4(_img(1000, 500))
    assert out.size == ip.XHS_COVER_SIZE


def test_to_cover_3_4_pad_keeps_size():
    out = ip.to_cover_3_4(_img(1000, 500), strategy="pad")
    assert out.size == ip.XHS_COVER_SIZE


def test_to_wechat_cover_size():
    out = ip.to_wechat_cover(_img(1000, 500))
    assert out.size == ip.WECHAT_COVER_SIZE


def test_to_wechat_cover_wide_image():
    # 宽高比 4:1，远大于 2.35:1，触发宽图裁剪分支
    out = ip.to_wechat_cover(_img(2000, 500))
    assert out.size == ip.WECHAT_COVER_SIZE


def test_resize_for_article_caps_width():
    out = ip.resize_for_article(_img(2000, 1000))
    assert out.width == 900
    out2 = ip.resize_for_article(_img(500, 300))
    assert out2.width == 500   # 不放大


def test_watermark_changes_pixels():
    src = _img(800, 600)
    out = ip.add_watermark(src, "@me")
    assert out.size == src.size
    assert out.tobytes() != src.tobytes()


def test_watermark_empty_text_returns_same_pixels():
    src = _img(800, 600)
    out = ip.add_watermark(src, "")
    assert out.tobytes() == src.tobytes()


def test_title_overlay_changes_pixels():
    src = _img(800, 600)
    out = ip.add_title_overlay(src, "主标题")
    assert out.size == src.size
    assert out.tobytes() != src.tobytes()


def test_stitch_grid_dimensions():
    imgs = [_img(400, 300), _img(400, 300), _img(400, 300)]
    out = ip.stitch_grid(imgs, cols=2)
    assert out.size == (800, 600)   # 2 列 2 行，单元 400x300


def test_build_xhs_images_first_is_cover_with_overlay_and_watermark():
    cfg = ImageConfig(watermark_text="@me", crop_strategy="crop", collage=False)
    imgs = [Image.new("RGB", (900, 900), (10, 10, 10))]
    out = ip.build_xhs_images(imgs, cfg, cover_text="封面")
    assert len(out) == 1
    assert out[0].size == ip.XHS_COVER_SIZE


def test_build_xhs_images_collage_when_enabled():
    cfg = ImageConfig(watermark_text="@me", collage=True)
    imgs = [Image.new("RGB", (900, 900)), Image.new("RGB", (900, 900))]
    out = ip.build_xhs_images(imgs, cfg)
    assert len(out) == 1   # collage 只出一张
    assert out[0].size == ip.XHS_COVER_SIZE


def test_build_wechat_images_cover_plus_body():
    cfg = ImageConfig()
    imgs = [Image.new("RGB", (1200, 800)), Image.new("RGB", (2000, 1000))]
    out = ip.build_wechat_images(imgs, cfg)
    assert out[0].size == ip.WECHAT_COVER_SIZE
    assert out[1].width <= ip.WECHAT_ARTICLE_MAX_W


def test_build_empty_returns_empty():
    assert ip.build_xhs_images([], ImageConfig()) == []
    assert ip.build_wechat_images([], ImageConfig()) == []


def test_save_jpeg_writes_file(tmp_path):
    p = ip.save_jpeg(_img(100, 100), tmp_path / "out" / "x.jpg")
    assert p.exists() and p.suffix == ".jpg"
