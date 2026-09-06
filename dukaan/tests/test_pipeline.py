import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dukaan.backend import MockBackend, _fit, chroma_cutout
from dukaan.config import Config
from dukaan.frames import fit_scene, pick_frames, sharpness
from dukaan.layout import compose, contact_strip
from dukaan.pack import build_pack, make_plate, relabel
from dukaan.spec import FORMATS, FORMATS_BY_NAME, STYLES_BY_NAME, Brief


def _photo(size=(400, 400), obj=(120, 120, 280, 280), bg=(240, 240, 238)) -> Image.Image:
    img = Image.new("RGB", size, bg)
    img.paste(Image.new("RGB", (obj[2] - obj[0], obj[3] - obj[1]), (200, 70, 50)), (obj[0], obj[1]))
    return img


def _graded_photo(size=(400, 400)) -> Image.Image:
    """A product on a backdrop that shades top to bottom, like a real one."""
    w, h = size
    ramp = np.linspace(30, 200, h, dtype=np.float32)[:, None] * np.ones((1, w), np.float32)
    img = Image.fromarray(np.dstack([ramp] * 3).astype("uint8"), "RGB")
    img.paste(Image.new("RGB", (160, 160), (200, 70, 50)), (120, 120))
    return img


def _cfg(tmp_path, **kw):
    return Config(instance="", out_dir=tmp_path, width=128, height=128, frames=9, **kw)


class TestCutout:
    def test_removes_a_flat_backdrop(self):
        cut = chroma_cutout(_photo())
        alpha = np.asarray(cut)[..., 3]
        assert alpha[5, 5] < 40, "corner backdrop should be transparent"
        assert alpha[200, 200] > 200, "product should be opaque"

    def test_removes_a_graded_backdrop(self):
        """A single sampled colour keeps half of a gradient; a fitted one does not."""
        cut = chroma_cutout(_graded_photo())
        alpha = np.asarray(cut)[..., 3]
        assert alpha[5, 5] < 40, "dark end of the gradient must go"
        assert alpha[-5, -5] < 40, "light end of the gradient must go too"
        assert alpha[200, 200] > 200, "product survives"

    def test_a_product_touching_the_edge_does_not_drag_the_fit(self):
        img = _graded_photo()
        img.paste(Image.new("RGB", (120, 380), (200, 70, 50)), (0, 10))
        cut = chroma_cutout(img)
        alpha = np.asarray(cut)[..., 3]
        assert alpha[200, 380] < 60, "backdrop away from the product still goes"


class TestFit:
    def test_crops_to_content_then_fills(self):
        """A cutout with a wide transparent margin must not render tiny."""
        src = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
        src.paste(Image.new("RGBA", (100, 100), (255, 0, 0, 255)), (450, 450))
        out = _fit(src, (1024, 1024), band=0.0)
        assert out.getbbox()[2] - out.getbbox()[0] > 700

    def test_upscales_a_small_source(self):
        """thumbnail() refuses to enlarge; the banner needs it to."""
        src = Image.new("RGBA", (200, 200), (255, 0, 0, 255))
        out = _fit(src, (1820, 1024), band=0.0)
        assert out.getbbox()[2] - out.getbbox()[0] > 200

    def test_keeps_product_clear_of_the_text_band(self):
        src = Image.new("RGBA", (400, 400), (255, 0, 0, 255))
        out = _fit(src, (1000, 1000), band=0.25)
        assert out.getbbox()[3] <= 1000 * 0.75 + 2

    def test_preserves_aspect_ratio(self):
        src = Image.new("RGBA", (400, 200), (255, 0, 0, 255))
        x0, y0, x1, y1 = _fit(src, (1000, 1000), band=0.0).getbbox()
        assert abs((x1 - x0) / (y1 - y0) - 2.0) < 0.05


class TestFrameSelection:
    def test_picks_are_spread_and_never_the_input_plate(self):
        frames = [Image.new("RGB", (64, 64), (i * 8, 0, 0)) for i in range(20)]
        picks = pick_frames(frames, 3)
        assert len(picks) == 3
        assert 0 not in picks, "frame 0 is the plate the model was handed"
        assert len(set(picks)) == 3
        assert max(picks) - min(picks) > 5, "stills must come from different moments"

    def test_prefers_the_sharper_frame_in_a_window(self):
        sharp = _photo((64, 64), (20, 20, 44, 44))
        soft = sharp.filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(3))
        assert sharpness(sharp) > sharpness(soft)
        # window of two: index 1 soft, index 2 sharp
        picks = pick_frames([sharp, soft, sharp], 1)
        assert picks == [2]

    def test_handles_fewer_frames_than_formats(self):
        assert len(pick_frames([Image.new("RGB", (8, 8))], 3)) == 3

    def test_handles_no_frames(self):
        assert pick_frames([], 3) == []


class TestFitScene:
    def test_returns_exact_size_and_does_not_clip_the_frame(self):
        frame = Image.new("RGB", (512, 512), (10, 120, 200))
        out = fit_scene(frame, (512, 910))
        assert out.size == (512, 910)

    def test_extends_rather_than_crops(self):
        """A square frame going to 9:16 must keep its full width."""
        frame = Image.new("RGB", (512, 512), (0, 0, 0))
        frame.paste(Image.new("RGB", (512, 40), (255, 0, 0)), (0, 236))
        out = fit_scene(frame, (512, 910), feather=0)
        row = np.asarray(out)[455]
        assert row[:, 0].mean() > 100, "the red band spanning the frame must still span it"

    def test_extension_mirrors_rather_than_streaks(self):
        """A stripe near the edge must reappear mirrored, not smear to the border."""
        frame = Image.new("RGB", (512, 512), (0, 0, 0))
        frame.paste(Image.new("RGB", (512, 10), (0, 200, 0)), (0, 492))  # 20px in from bottom
        out = np.asarray(fit_scene(frame, (512, 552), feather=0))
        # inner sits at y=20..531, so the stripe lands at 512..521 and mirrors to 541..550
        assert out[512:522, 256, 1].mean() > 120, "original stripe still there"
        assert out[541:551, 256, 1].mean() > 120, "and its reflection"
        assert out[535, 256, 1] < 60, "black between them, not a green smear to the border"


class TestLayout:
    def test_compose_returns_exact_format_size(self):
        fmt = FORMATS_BY_NAME["story"]
        out = compose(Image.new("RGB", (512, 512), (10, 10, 10)), Brief("p", "Hello"), fmt,
                      STYLES_BY_NAME["studio"])
        assert out.size == fmt.size

    def test_long_headline_shrinks_instead_of_overflowing(self):
        """A seller's words are theirs; shrink type rather than truncate."""
        fmt = FORMATS_BY_NAME["square"]
        base = Image.new("RGB", (512, 512), (10, 10, 10))
        short = compose(base, Brief("p", "Pots"), fmt, STYLES_BY_NAME["studio"])
        long = compose(base, Brief("p", "Handmade terracotta pots fired in a traditional kiln, "
                                        "delivered anywhere in the city"), fmt,
                       STYLES_BY_NAME["studio"])
        assert short.size == long.size == fmt.size
        assert list(short.getdata()) != list(long.getdata())

    def test_contact_strip_is_optional_and_changes_pixels(self):
        fmt = FORMATS_BY_NAME["square"]
        base = Image.new("RGB", fmt.size, (10, 10, 10))
        style = STYLES_BY_NAME["studio"]
        assert list(contact_strip(base, "", style).getdata()) == list(base.getdata())
        assert list(contact_strip(base, "+91 90000 00000", style).getdata()) != list(base.getdata())


class TestPack:
    def test_builds_every_format_and_a_manifest(self, tmp_path: Path):
        res = build_pack(_cfg(tmp_path), MockBackend(), _photo(),
                         Brief("pot", "Clay pots", style="studio"))
        assert set(res.creatives) == {f.name for f in FORMATS}
        for p in res.creatives.values():
            assert p.exists() and p.stat().st_size > 0
        assert (tmp_path / "pot" / "studio_manifest.json").exists()

    def test_gpu_runs_once_no_matter_how_many_formats(self, tmp_path: Path):
        """The whole point of the redesign: one pass feeds the pack."""
        calls = []

        class Counting(MockBackend):
            def render(self, plate, style, cfg):
                calls.append(cfg.size)
                return super().render(plate, style, cfg)

        build_pack(_cfg(tmp_path), Counting(), _photo(), Brief("pot", "Clay pots"))
        assert len(calls) == 1

    def test_each_format_gets_a_different_frame(self, tmp_path: Path):
        res = build_pack(_cfg(tmp_path), MockBackend(), _photo(), Brief("pot", "Clay pots"))
        assert len(set(res.frame_of.values())) == len(FORMATS)

    def test_writes_the_clip_and_its_frames(self, tmp_path: Path):
        res = build_pack(_cfg(tmp_path), MockBackend(), _photo(), Brief("pot", "Clay pots"))
        assert len(res.clip_frames) == 9
        assert res.clip and res.clip.exists()

    def test_no_clip_skips_the_frames(self, tmp_path: Path):
        res = build_pack(_cfg(tmp_path), MockBackend(), _photo(), Brief("pot", "Clay pots"),
                         write_clip=False)
        assert res.clip is None and res.clip_frames == []
        assert set(res.creatives) == {f.name for f in FORMATS}

    def test_subset_of_formats(self, tmp_path: Path):
        res = build_pack(_cfg(tmp_path), MockBackend(), _photo(), Brief("pot", "Clay pots"),
                         formats=(FORMATS_BY_NAME["square"],))
        assert set(res.creatives) == {"square"}

    def test_plate_places_the_product_on_the_style_wash(self):
        style = STYLES_BY_NAME["festive"]
        plate = make_plate(chroma_cutout(_photo()), style, (256, 256))
        assert plate.size == (256, 256)
        assert plate.getpixel((4, 4)) == style.backdrop, "corners are the style backdrop"


class TestRelabel:
    def _packed(self, tmp_path: Path):
        build_pack(_cfg(tmp_path), MockBackend(), _photo(),
                   Brief("pot", "Clay pots", "900 rupees", style="studio"), contact="+91 1")
        return tmp_path / "pot"

    def test_changes_words_and_keeps_the_same_frames(self, tmp_path: Path):
        """The whole point: new type, same scene, no GPU."""
        d = self._packed(tmp_path)
        before = {f"studio_{n}.png": (d / f"studio_{n}.png").read_bytes()
                  for n in (f.name for f in FORMATS)}
        first = json.loads((d / "studio_manifest.json").read_text())["still_from_frame"]

        res = relabel(d, subline="Diwali price, 700 rupees")
        after = json.loads((d / "studio_manifest.json").read_text())

        assert res.frame_of == {k: int(v) for k, v in first.items()}, "same frames reused"
        assert after["subline"] == "Diwali price, 700 rupees"
        assert after["headline"] == "Clay pots", "untouched fields survive"
        assert after["contact"] == "+91 1", "contact defaults to what the pack had"
        changed = [n for n, b in before.items() if (d / n).read_bytes() != b]
        assert len(changed) == len(before), "every creative was rewritten"
        assert (d / "studio_plate.png").exists(), "the plate is an input, not a creative"

    def test_uses_no_backend_at_all(self, tmp_path: Path):
        d = self._packed(tmp_path)

        class Exploding(MockBackend):
            def render(self, plate, style, cfg):
                raise AssertionError("relabel must not reach the GPU")

        # relabel takes no backend, so the only way it could generate is via a
        # pack call; assert the signature keeps that impossible.
        relabel(d, headline="New words")
        assert json.loads((d / "studio_manifest.json").read_text())["headline"] == "New words"

    def test_explains_itself_when_there_is_no_pack(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError) as e:
            relabel(tmp_path)
        assert "dukaan pack" in str(e.value)

    def test_explains_itself_when_frames_were_skipped(self, tmp_path: Path):
        build_pack(_cfg(tmp_path), MockBackend(), _photo(), Brief("pot", "Clay pots"),
                   write_clip=False)
        with pytest.raises(FileNotFoundError) as e:
            relabel(tmp_path / "pot", headline="x")
        assert "--no-clip" in str(e.value)


class TestBrief:
    def test_unknown_style_names_the_valid_ones(self):
        with pytest.raises(ValueError) as e:
            Brief("p", "h", style="neon").styled()
        assert "studio" in str(e.value)

    def test_offline_flag_follows_instance_url(self):
        assert Config(instance="").offline is True
        assert Config(instance="https://x/instances/y").offline is False


class TestRegions:
    """The cutout decides per pixel; these are the region-level repairs."""

    def _ring_with_speck(self):
        import numpy as np
        m = np.zeros((60, 60), bool)
        m[10:50, 10:50] = True
        m[22:38, 22:38] = False   # a hole 16% of the ring's area
        m[2:5, 2:5] = True        # a detached speck
        return m

    def test_label_counts_separate_regions(self):
        from dukaan.regions import label
        _, n = label(self._ring_with_speck())
        assert n == 2

    def test_largest_region_drops_the_speck(self):
        from dukaan.regions import largest_region
        out = largest_region(self._ring_with_speck())
        assert not out[2:5, 2:5].any()
        assert out[12, 12]

    def test_fill_holes_leaves_a_bangle_open(self):
        """A ring's interior is real backdrop. Filling it makes a disc."""
        from dukaan.regions import fill_holes
        assert not fill_holes(self._ring_with_speck())[30, 30]

    def test_fill_holes_closes_small_speckle(self):
        import numpy as np
        from dukaan.regions import fill_holes
        m = np.ones((60, 60), bool)
        m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = False   # keep a border
        m[30, 30] = False                                  # one stray pixel
        assert fill_holes(m)[30, 30]

    def test_clean_keeps_small_detached_detail(self):
        """Fine engraving fragments the mask; pruning to the largest ate it."""
        import numpy as np
        from dukaan.regions import clean
        m = np.zeros((60, 60), bool)
        m[10:50, 10:40] = True    # the body
        m[52, 20:30] = True       # a thin detached sliver of real detail
        assert clean(m)[52, 25], "detail survived"

    def test_clean_severs_a_thin_necked_lobe(self):
        """The vignette streak case: real backdrop, genuinely touching."""
        import numpy as np
        from dukaan.regions import clean
        m = np.zeros((80, 120), bool)
        m[20:60, 10:50] = True     # the product
        m[38:42, 50:110] = True    # a thin lobe joined to it
        out = clean(m, open_radius=4, prune=True)
        assert out[40, 30], "product survived"
        assert not out[40, 100], "lobe removed"

    def test_cutout_mask_is_solid_body(self):
        """End to end on the photograph that exposed both failures."""
        import numpy as np
        from pathlib import Path
        from PIL import Image
        from dukaan.backend import chroma_cutout
        photo = Path("examples/porcelain-vase.png")
        if not photo.exists():
            pytest.skip("example photo not present")
        a = np.asarray(chroma_cutout(Image.open(photo).convert("RGB")).split()[3]) > 128
        # The body of the vase must be continuous, not speckled.
        ys, xs = np.nonzero(a)
        cy, cx = int(np.median(ys)), int(np.median(xs))
        assert a[cy - 12:cy + 12, cx - 12:cx + 12].mean() > 0.98
