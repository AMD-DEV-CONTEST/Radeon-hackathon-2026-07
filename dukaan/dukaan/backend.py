"""Where inference happens.

Two implementations behind one protocol:

- RadeonBackend runs LTX-2.3 on the Radeon GPU. This is the one that satisfies
  the rule that a key inference process runs on AMD hardware.
- MockBackend synthesises plausible outputs on the CPU so the pipeline, the
  compositor and the CLI stay testable without spending GPU credits. It is a
  development aid, never a fallback in a real run: if a real backend is
  configured and fails, the error surfaces rather than being quietly replaced
  by a fake.

Both expose one generative call, `render`, because that is what the hardware
allows. LTX-2.3 is the only generative model on the instance and it produces a
short audio-video clip per pass, so a pack is derived from a single pass rather
than one call per output. See pack.py for how the stills fall out of that.
"""
from __future__ import annotations

import io
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageFilter

from .config import Config
from .instance import Instance
from . import regions
from .spec import Style


@dataclass
class Clip:
    """One generative pass: the frames, and the sound that goes with them."""

    frames: list[Image.Image]
    audio: bytes | None = None
    meta: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.frames)


class Backend(Protocol):
    name: str

    def remove_background(self, image: Image.Image) -> Image.Image: ...

    def render(self, plate: Image.Image, style: Style, cfg: Config) -> Clip: ...

    def render_batch(self, items: list[tuple[str, Image.Image, Style]],
                     cfg: Config) -> dict[str, Clip]: ...


class MockBackend:
    """CPU stand-in. Deterministic, so tests can assert on it."""

    name = "mock"

    def remove_background(self, image: Image.Image) -> Image.Image:
        return chroma_cutout(image)

    def render(self, plate: Image.Image, style: Style, cfg: Config) -> Clip:
        # A slow push-in. Enough motion to prove the frame plumbing, and enough
        # frame-to-frame difference that the still picker has something to
        # choose between.
        out = []
        w, h = plate.size
        for i in range(cfg.frames):
            z = 1.0 + 0.06 * (i / max(cfg.frames - 1, 1))
            cw, ch = int(w / z), int(h / z)
            box = ((w - cw) // 2, (h - ch) // 2, (w + cw) // 2, (h + ch) // 2)
            out.append(plate.crop(box).resize((w, h), Image.LANCZOS))
        return Clip(frames=out, meta={"backend": self.name, "frames": cfg.frames})

    def render_batch(self, items, cfg: Config) -> dict:
        return {key: self.render(plate, style, cfg) for key, plate, style in items}


def chroma_cutout(image: Image.Image, tolerance: int = 34, feather: float = 1.2,
                  margin: float = 0.03) -> Image.Image:
    """Drop the backdrop by fitting it rather than assuming one flat colour.

    Backdrops are rarely one colour. A phone photo on a shop counter shades off
    as window light falls away, and a catalogue sweep is graded on purpose.
    Differencing against a single sampled colour keeps whichever half of the
    backdrop drifted furthest from the sample, which on a museum-style gradient
    means keeping most of it.

    So the border ring is used to fit a smooth surface per channel, and the
    image is differenced against that fit. The basis is quadratic rather than
    linear: a plane handles a top-to-bottom wash but leaves an elliptical pool
    of backdrop behind on the pooled-light sweep that catalogue photography
    uses, and that pool is exactly where the product sits. A flat backdrop is
    just the case where every non-constant term fits near zero, so one path
    covers all three. The fit is repeated once with the worst quarter of
    residuals dropped, because a product that runs off the edge of the frame
    puts its own pixels in the ring and would otherwise drag the surface
    towards itself.

    This is still a cutout, not a segmentation model. It assumes the product
    stands clear of a reasonably plain background. A matting model would be
    better and is the obvious upgrade, but it would spend GPU credits on the
    one step that does not need them.
    """
    import numpy as np

    rgba = image.convert("RGBA")
    arr = np.asarray(rgba.convert("RGB"), dtype=np.float32)
    h, w = arr.shape[:2]

    yy, xx = np.mgrid[0:h, 0:w]
    m = max(int(round(min(h, w) * margin)), 1)
    ring = np.zeros((h, w), dtype=bool)
    ring[:m, :] = ring[-m:, :] = ring[:, :m] = ring[:, -m:] = True

    # Normalised so the squared terms stay the same order as the linear ones
    # and lstsq does not have to fight the conditioning.
    u, v = (xx / w) - 0.5, (yy / h) - 0.5

    def basis(sel=None):
        cols = [u, v, u * u, v * v, u * v, np.ones_like(u)]
        cols = [c[sel] if sel is not None else c.reshape(-1) for c in cols]
        return np.stack(cols, axis=-1)

    def fit(sel):
        coef, *_ = np.linalg.lstsq(basis(sel), arr[sel], rcond=None)
        return coef

    coef = fit(ring)
    resid = np.abs(arr[ring] - basis(ring) @ coef).max(axis=1)
    keep = resid <= np.quantile(resid, 0.75)
    if keep.sum() >= 24:
        idx = np.argwhere(ring)
        trimmed = np.zeros_like(ring)
        trimmed[tuple(idx[keep].T)] = True
        coef = fit(trimmed)

    surface = (basis() @ coef).reshape(h, w, 3)
    keep_px = np.abs(arr - surface).max(axis=-1) > tolerance

    # Deciding per pixel is not enough information, and the two ways it fails
    # are both visible in a finished creative: a light product on a lit sweep
    # comes back full of holes, and a vignette the fit cannot see survives as a
    # streak stuck to the product. Both are obvious once whole regions are
    # considered rather than pixels. See dukaan/regions.py.
    keep_px = regions.clean(keep_px)
    mask = keep_px.astype(np.uint8) * 255

    alpha = Image.fromarray(mask, "L")
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))

    out = rgba.copy()
    out.putalpha(alpha)
    return out


def _fit(image: Image.Image, size: tuple[int, int], band: float = 0.0, fill: float = 0.86) -> Image.Image:
    """Place the product in the area the headline will not cover.

    Three things this has to get right, each of which looked wrong when it
    was missing:

    - Crop to the cutout's actual content first. A transparent cutout usually
      carries a wide empty margin from the original photo, so scaling the
      whole frame leaves the product looking tiny.
    - Scale to fill, not `thumbnail`, which silently refuses to enlarge. A
      900px source on a 1820px banner has to grow.
    - Centre inside the region above the text band, not the whole canvas,
      or the product drifts up and leaves a dead middle.
    """
    src = image.convert("RGBA")
    bbox = src.getbbox() if src.mode == "RGBA" else None
    if bbox:
        src = src.crop(bbox)

    w, h = size
    safe_h = max(int(h * (1.0 - band)), 1)
    target_w, target_h = int(w * fill), int(safe_h * fill)

    scale = min(target_w / src.width, target_h / src.height)
    new = src.resize((max(int(src.width * scale), 1), max(int(src.height * scale), 1)), Image.LANCZOS)

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(new, ((w - new.width) // 2, (safe_h - new.height) // 2), new)
    return canvas


#: Watermarks are the one artefact that would embarrass a seller, and LTX has
#: clearly seen a lot of captioned stock footage: an early run put a craft
#: channel's watermark across the bottom of the frame. Naming the shapes it
#: reaches for costs nothing and it stopped recurring.
NEGATIVE = (
    "text, caption, subtitle, watermark, logo, channel name, signature, "
    "distorted product, morphing shape, warping, jitter, extra objects, "
    "cartoon, childish, ugly"
)


class RadeonBackend:
    """LTX-2.3 on the Radeon GPU, driven over the JupyterLab API.

    The work happens in scripts/radeon_ltx.py on the instance, in two processes
    that never overlap: the 43 GB checkpoint and the 23 GB text encoder do not
    fit in the container's 55 GB together. See that file for why.

    This class is the client half: it puts the plate up, starts each phase
    detached so a culled kernel cannot kill it, waits on the log, and pulls the
    frames back.
    """

    name = "radeon-ltx"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.inst = Instance(cfg.instance, timeout=cfg.job_timeout_s)
        self.dir = cfg.remote_dir.rstrip("/")

    def remove_background(self, image: Image.Image) -> Image.Image:
        # Cutout is cheap, deterministic and exact on the CPU. Keeping it off
        # the GPU leaves credits for the step that has no CPU equivalent.
        return chroma_cutout(image)

    def render(self, plate: Image.Image, style: Style, cfg: Config) -> Clip:
        buf = io.BytesIO()
        plate.convert("RGB").save(buf, format="PNG")
        self.inst.put_bytes(buf.getvalue(), f"{self.dir}/plate.png")

        runner = f"/workspace/{self.dir}/radeon_ltx.py"
        prompt = f"{style.motion_prompt} {style.prompt}"

        self.inst.shell(f"rm -rf /workspace/{self.dir}/frames /workspace/{self.dir}/*.log")
        self.inst.detach(
            f"/opt/venv/bin/python3 {runner} encode"
            f" --positive {shlex.quote(prompt)} --negative {shlex.quote(NEGATIVE)}"
            f" --conditioning /workspace/{self.dir}/cond.pt",
            f"/workspace/{self.dir}/encode.log",
        )
        self.inst.wait_for(f"/workspace/{self.dir}/encode.log", "conditioning ->",
                           timeout=cfg.job_timeout_s)

        self.inst.detach(
            f"env PYTORCH_ALLOC_CONF=expandable_segments:True /opt/venv/bin/python3 {runner} sample"
            f" --image /workspace/{self.dir}/plate.png --out /workspace/{self.dir}/frames"
            f" --width {cfg.width} --height {cfg.height} --frames {cfg.frames}"
            f" --fps {cfg.fps} --seed {cfg.seed} --strength {cfg.strength}"
            + (" --refine" if cfg.refine else ""),
            f"/workspace/{self.dir}/sample.log",
        )
        log = self.inst.wait_for(f"/workspace/{self.dir}/sample.log", '"frames"',
                                 timeout=cfg.job_timeout_s)

        files = self.inst.get_dir(f"{self.dir}/frames", f"/workspace/{self.dir}/frames")
        frames = [Image.open(io.BytesIO(files[n])).convert("RGB")
                  for n in sorted(n for n in files if n.endswith(".png"))]
        if not frames:
            raise RuntimeError(
                "the GPU run reported success but returned no frames. Tail of the run:\n"
                + "\n".join(log.splitlines()[-15:])
            )
        meta = json.loads(files["meta.json"]) if "meta.json" in files else {}
        meta["backend"] = self.name
        return Clip(frames=frames, audio=files.get("audio.wav"), meta=meta)

    def render_batch(self, items: list[tuple[str, Image.Image, Style]], cfg: Config) -> dict[str, Clip]:
        """Render several plates against a single pair of model loads.

        Loading the checkpoint costs about 14 seconds and loading the text
        encoder about 5, every time. Per photo that is most of a small run; a
        shop with fifty items would pay it fifty times for nothing. Batching
        pays it once, so throughput rises with the size of the catalogue.
        """
        if not items:
            return {}
        runner = f"/workspace/{self.dir}/radeon_ltx.py"
        base = f"/workspace/{self.dir}"

        self.inst.shell(f"rm -rf {base}/batch && mkdir -p {base}/batch")
        encode_jobs, sample_jobs = [], []
        for key, plate, style in items:
            buf = io.BytesIO()
            plate.convert("RGB").save(buf, format="PNG")
            self.inst.put_bytes(buf.getvalue(), f"{self.dir}/batch/{key}.png")
            encode_jobs.append({"positive": f"{style.motion_prompt} {style.prompt}",
                                "conditioning": f"{base}/batch/{key}.pt"})
            sample_jobs.append({"image": f"{base}/batch/{key}.png",
                                "out": f"{base}/batch/{key}",
                                "conditioning": f"{base}/batch/{key}.pt"})

        self.inst.put_bytes(json.dumps(encode_jobs).encode(), f"{self.dir}/batch/encode.json")
        self.inst.put_bytes(json.dumps(sample_jobs).encode(), f"{self.dir}/batch/sample.json")

        self.inst.detach(
            f"/opt/venv/bin/python3 {runner} encode --jobs {base}/batch/encode.json"
            f" --negative {shlex.quote(NEGATIVE)}",
            f"{base}/encode.log",
        )
        self.inst.wait_for(f"{base}/encode.log", f"encoded {len(encode_jobs)}/{len(encode_jobs)}",
                           timeout=cfg.job_timeout_s)

        self.inst.detach(
            f"env PYTORCH_ALLOC_CONF=expandable_segments:True /opt/venv/bin/python3 {runner} sample"
            f" --jobs {base}/batch/sample.json"
            f" --width {cfg.width} --height {cfg.height} --frames {cfg.frames}"
            f" --fps {cfg.fps} --seed {cfg.seed} --strength {cfg.strength}"
            + (" --refine" if cfg.refine else ""),
            f"{base}/sample.log",
        )
        log = self.inst.wait_for(f"{base}/sample.log", f"decoded {len(sample_jobs)}/{len(sample_jobs)}",
                                 timeout=cfg.job_timeout_s)

        out: dict[str, Clip] = {}
        for key, _, _ in items:
            files = self.inst.get_dir(f"{self.dir}/batch/{key}", f"{base}/batch/{key}")
            frames = [Image.open(io.BytesIO(files[n])).convert("RGB")
                      for n in sorted(n for n in files if n.endswith(".png"))]
            if not frames:
                raise RuntimeError(
                    f"the GPU run returned no frames for {key}. Tail of the run:\n"
                    + "\n".join(log.splitlines()[-15:])
                )
            meta = json.loads(files["meta.json"]) if "meta.json" in files else {}
            meta["backend"] = self.name
            out[key] = Clip(frames=frames, audio=files.get("audio.wav"), meta=meta)
        return out

    def deploy(self, runner: Path) -> None:
        """Put the runner on the instance's persistent volume.

        The notebook root is not persistent and the contents API cannot write
        outside it, so the persistent directory is linked into the root and
        written through the link.
        """
        self.inst.run(
            "import os, pathlib\n"
            f"target = pathlib.Path('/workspace/{self.dir}')\n"
            "target.mkdir(parents=True, exist_ok=True)\n"
            f"link = pathlib.Path(os.getcwd()) / {self.dir!r}\n"
            "if not link.exists():\n"
            "    link.symlink_to(target)\n"
            "print('ready', target)\n"
        )
        self.inst.put(runner, f"{self.dir}/{runner.name}")


def make_backend(cfg: Config) -> Backend:
    return MockBackend() if cfg.offline else RadeonBackend(cfg)
