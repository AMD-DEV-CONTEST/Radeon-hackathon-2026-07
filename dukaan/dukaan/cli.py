"""CLI: dukaan pack / styles / doctor."""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import typer
from PIL import Image
from rich.console import Console
from rich.table import Table

from .backend import RadeonBackend, make_backend
from .config import load
from .instance import InstanceError
from .pack import build_catalogue, build_pack, relabel as relabel_pack
from .spec import FORMATS, FORMATS_BY_NAME, STYLES, Brief

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _masked(url: str) -> str:
    """Show enough of the instance URL to identify it, not enough to use it.

    The tunnel in front of the instance takes no credentials, so the URL is the
    credential: anyone who reads one off a screenshot or a CI log can spend the
    GPU budget behind it. The host is useful to see, the instance id is not.
    """
    head, _, tail = url.rstrip("/").rpartition("/")
    return f"{head}/{tail[:6]}..." if len(tail) > 6 else url


@app.command()
def styles() -> None:
    """Looks a seller can pick without writing a prompt."""
    table = Table(title="Styles")
    table.add_column("name")
    table.add_column("what it looks like")
    for s in STYLES:
        table.add_row(s.name, s.prompt.split(",")[0])
    console.print(table)

    fmt_table = Table(title="Formats")
    for col in ("name", "size", "used for"):
        fmt_table.add_column(col)
    for f in FORMATS:
        fmt_table.add_row(f.name, f"{f.width}x{f.height}", f.note)
    console.print(fmt_table)


@app.command()
def doctor() -> None:
    """Say plainly which backend a run would use, before it costs anything."""
    cfg = load()
    if cfg.offline:
        console.print("[yellow]No DUKAAN_INSTANCE set.[/yellow] Runs use the mock CPU backend.")
        console.print("Point it at the Radeon instance for real generation:")
        console.print("  [dim]export DUKAAN_INSTANCE=https://<host>/instances/<instance-id>[/dim]")
        raise typer.Exit(0)

    console.print(f"instance: {_masked(cfg.instance)}")
    backend = RadeonBackend(cfg)
    try:
        # rocm-smi cannot reach libdrm inside this container and torch returns
        # an empty device name, so the architecture, the PCI model id and the
        # compute-unit count stand in. They are what the driver will actually
        # tell you, and they identify the part without guessing at its
        # marketing name.
        report = backend.inst.run(
            "import subprocess, os\n"
            "def sh(c):\n"
            "    return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()\n"
            "print(sh(\"/opt/venv/bin/python3 -c \\\"import torch;p=torch.cuda.get_device_properties(0);\"\n"
            "         \"print('arch:', p.gcnArchName);print('vram_gb:', round(p.total_memory/2**30,1));\"\n"
            "         \"print('compute_units:', p.multi_processor_count);\"\n"
            "         \"print('torch:', torch.__version__)\\\"\"))\n"
            "print('card_model:', sh(\"rocm-smi --showproductname 2>/dev/null | \"\n"
            "      \"grep -i 'card model' | head -1 | awk '{print $NF}'\") or 'unknown')\n"
            "print('container_ram_cap_gb:', round(int(open('/sys/fs/cgroup/memory.max').read())/2**30, 1))\n"
            "print('runner:', 'yes' if os.path.exists('/workspace/%s/radeon_ltx.py') else 'MISSING')\n"
            % cfg.remote_dir,
            timeout=180,
        )
    except InstanceError as exc:
        console.print(f"[red]unreachable:[/red] {exc}")
        raise typer.Exit(1)

    for line in report.strip().splitlines():
        console.print(f"  {line}")
    if "MISSING" in report:
        console.print("[yellow]runner not deployed.[/yellow] Run [bold]dukaan deploy[/bold] first.")
        raise typer.Exit(1)
    console.print("[green]ready[/green]")


@app.command()
def deploy() -> None:
    """Copy the GPU runner onto the instance's persistent volume."""
    cfg = load()
    if cfg.offline:
        raise typer.BadParameter("set DUKAAN_INSTANCE first")
    runner = Path(__file__).resolve().parent.parent / "scripts" / "radeon_ltx.py"
    if not runner.exists():
        raise typer.BadParameter(f"runner not found at {runner}")
    RadeonBackend(cfg).deploy(runner)
    console.print(f"[green]deployed[/green] {runner.name} -> /workspace/{cfg.remote_dir}/")


@app.command()
def pack(
    photo: Path = typer.Argument(..., exists=True, help="One product photo"),
    headline: str = typer.Option(..., "--headline", "-h", help="The line that sells it"),
    subline: str = typer.Option("", "--subline", "-s", help="Price, offer, or detail"),
    style: str = typer.Option("studio", "--style", help="See `dukaan styles`"),
    product: str = typer.Option("", "--product", help="Folder name for the output"),
    contact: str = typer.Option("", "--contact", help="Phone or handle, rendered exactly"),
    formats: str = typer.Option("", "--formats", help="Comma list, default all"),
    no_clip: bool = typer.Option(False, "--no-clip", help="Skip writing the clip and its frames"),
) -> None:
    """Build a campaign pack from one photo."""
    cfg = load()
    chosen = FORMATS
    if formats:
        names = [n.strip() for n in formats.split(",") if n.strip()]
        unknown = [n for n in names if n not in FORMATS_BY_NAME]
        if unknown:
            raise typer.BadParameter(f"unknown format(s): {', '.join(unknown)}")
        chosen = tuple(FORMATS_BY_NAME[n] for n in names)

    brief = Brief(
        product=product or photo.stem,
        headline=headline,
        subline=subline,
        style=style,
    )
    try:
        brief.styled()
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    backend = make_backend(cfg)
    if cfg.offline:
        console.print("[yellow]mock backend[/yellow] (no DUKAAN_INSTANCE), output is a layout preview")

    image = Image.open(photo)
    with console.status("building pack ..."):
        result = build_pack(
            cfg,
            backend,
            image,
            brief,
            formats=chosen,
            contact=contact,
            write_clip=not no_clip,
            on_step=lambda m: console.print(f"[dim]  {m}[/dim]"),
        )
    console.print(result.summary())



@app.command()
def relabel(
    pack_dir: Path = typer.Argument(..., exists=True, file_okay=False,
                                    help="A directory a previous `pack` wrote"),
    headline: str = typer.Option(None, "--headline", "-h", help="New headline"),
    subline: str = typer.Option(None, "--subline", "-s", help="New price or offer line"),
    contact: str = typer.Option(None, "--contact", help="New phone or handle"),
) -> None:
    """Change the words on a pack without regenerating it.

    Prices move and offers end. The scene was already right, so this recomposes
    the same stills with new type and never touches the GPU.
    """
    if headline is None and subline is None and contact is None:
        raise typer.BadParameter("give at least one of --headline, --subline or --contact")
    try:
        result = relabel_pack(pack_dir, headline, subline, contact,
                              on_step=lambda m: console.print(f"[dim]  {m}[/dim]"))
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc))
    console.print(result.summary())
    console.print("[green]no GPU time used[/green]")


@app.command()
def bench(
    photo: Path = typer.Argument(..., exists=True, help="Product photo to benchmark with"),
    out: Path = typer.Option(Path("bench-results"), "--out", help="Where to write the JSON"),
) -> None:
    """Time the GPU pipeline across settings and write the raw numbers out.

    The interesting axis on this box is not raw speed but what fits: the models
    are larger than the container, so every row here also records peak resident
    memory. `refine` is the row that shows the cost of the second pass.
    """
    cfg = load()
    if cfg.offline:
        raise typer.BadParameter("set DUKAAN_INSTANCE; benchmarking the mock proves nothing")

    from .backend import RadeonBackend
    from .pack import make_plate
    from .spec import STYLES_BY_NAME

    matrix = [
        {"label": "512x512, 25 frames", "width": 512, "height": 512, "frames": 25, "refine": False},
        {"label": "768x768, 25 frames", "width": 768, "height": 768, "frames": 25, "refine": False},
        {"label": "768x768, 49 frames", "width": 768, "height": 768, "frames": 49, "refine": False},
        {"label": "768x768, 49 frames, refined to 1536", "width": 768, "height": 768,
         "frames": 49, "refine": True},
    ]

    backend = RadeonBackend(cfg)
    style = STYLES_BY_NAME["studio"]
    cut = backend.remove_background(Image.open(photo))
    rows = []
    for spec in matrix:
        run_cfg = replace(cfg, width=spec["width"], height=spec["height"],
                          frames=spec["frames"], refine=spec["refine"])
        console.print(f"[dim]  {spec['label']} ...[/dim]")
        plate = make_plate(cut, style, run_cfg.size)
        started = time.time()
        clip = backend.render(plate, style, run_cfg)
        wall = time.time() - started
        meta = clip.meta
        pixels = meta["size"][0] * meta["size"][1] * meta["frames"]
        rows.append({
            "label": spec["label"],
            "request": {k: spec[k] for k in ("width", "height", "frames", "refine")},
            "output_size": meta["size"],
            "frames": meta["frames"],
            "gpu_seconds": meta["seconds"],
            "wall_seconds": round(wall, 1),
            "peak_container_gb": meta.get("peak_cgroup_gb"),
            "megapixel_frames_per_gpu_second": round(pixels / 1e6 / meta["seconds"], 2),
        })
        console.print(f"    {meta['size'][0]}x{meta['size'][1]}  {meta['seconds']}s GPU")

    # Batching is the one lever that changes the shape of the cost rather than
    # trading quality for time, so it gets measured against the same settings
    # as the single run above.
    console.print("[dim]  3 products in one batch (same settings as row 3) ...[/dim]")
    batch_cfg = replace(cfg, width=768, height=768, frames=49, refine=False)
    items = [(f"bench{i}", make_plate(cut, style, batch_cfg.size), style) for i in range(3)]
    started = time.time()
    clips = backend.render_batch(items, batch_cfg)
    batch_wall = time.time() - started
    first = next(iter(clips.values())).meta
    single = next((r for r in rows if r["request"] == {"width": 768, "height": 768,
                                                       "frames": 49, "refine": False}), None)
    batch = {
        "label": "3 products, one batch",
        "products": len(clips),
        "model_load_seconds": first.get("model_load_seconds"),
        "sample_seconds": [c.meta.get("sample_seconds") for c in clips.values()],
        "wall_seconds": round(batch_wall, 1),
        "peak_container_gb": max(c.meta.get("peak_cgroup_gb", 0) for c in clips.values()),
        "one_at_a_time_gpu_seconds": round(single["gpu_seconds"] * 3, 1) if single else None,
        "batched_gpu_seconds": max(c.meta.get("seconds", 0) for c in clips.values()),
    }
    console.print(f"    3 products in {batch['batched_gpu_seconds']}s GPU "
                  f"(one at a time would be {batch['one_at_a_time_gpu_seconds']}s)")

    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "device": {"arch": "gfx1100", "vram_gb": 48.0, "compute_units": 48},
        "model": "ltx-2.3-22b-dev + gemma_3_12B_it",
        "note": "Peak container RAM is the binding constraint on this box, not VRAM: "
                "the two models total 66 GB against a 55 GB cgroup cap, so they are "
                "loaded in separate processes.",
        "runs": rows,
        "batching": batch,
    }
    dest = out / "radeon-ltx.json"
    dest.write_text(json.dumps(payload, indent=2))

    table = Table(title="LTX-2.3 on Radeon gfx1100")
    for col in ("setting", "output", "GPU s", "peak RAM", "MPx-frames/s"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["label"], f"{r['output_size'][0]}x{r['output_size'][1]}",
                      f"{r['gpu_seconds']}", f"{r['peak_container_gb']} GB",
                      f"{r['megapixel_frames_per_gpu_second']}")
    console.print(table)
    console.print(f"[green]wrote[/green] {dest}")

@app.command()
def catalogue(
    folder: Path = typer.Argument(..., exists=True, file_okay=False,
                                  help="Folder of product photos"),
    style: str = typer.Option("studio", "--style", help="See `dukaan styles`"),
    contact: str = typer.Option("", "--contact", help="Phone or handle for every creative"),
    subline: str = typer.Option("", "--subline", help="Shared price or offer line"),
    limit: int = typer.Option(0, "--limit", help="Only the first N photos"),
    no_clip: bool = typer.Option(False, "--no-clip", help="Skip clips and their frames"),
) -> None:
    """Pack a whole folder of photos against one pair of model loads.

    A shop has a catalogue, not a photo. Loading the checkpoint costs about 14
    seconds and the text encoder about 5, every single time, so doing this one
    photo at a time pays that toll per item for nothing. The headline is
    derived from each filename, which is what a seller's folder already
    encodes; `dukaan relabel` fixes any the guess got wrong, without the GPU.
    """
    cfg = load()
    photos = sorted(p for p in folder.iterdir()
                    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
    if limit:
        photos = photos[:limit]
    if not photos:
        raise typer.BadParameter(f"no images in {folder}")

    jobs = []
    for photo in photos:
        headline = photo.stem.replace("-", " ").replace("_", " ").strip().capitalize()
        brief = Brief(product=photo.stem, headline=headline, subline=subline, style=style)
        try:
            brief.styled()
        except ValueError as exc:
            raise typer.BadParameter(str(exc))
        jobs.append((photo, brief, contact))

    backend = make_backend(cfg)
    if cfg.offline:
        console.print("[yellow]mock backend[/yellow] (no DUKAAN_INSTANCE), output is a layout preview")
    console.print(f"{len(jobs)} product(s), one batch")

    with console.status("building catalogue ..."):
        results = build_catalogue(cfg, backend, jobs, write_clip=not no_clip,
                                  on_step=lambda m: console.print(f"[dim]  {m}[/dim]"))

    table = Table(title=f"{len(results)} pack(s) via {backend.name}")
    for col in ("product", "creatives", "stills from", "GPU s"):
        table.add_column(col)
    for r in results:
        table.add_row(r.brief.product, str(len(r.creatives)),
                      ", ".join(str(v) for v in r.frame_of.values()),
                      str(r.meta.get("sample_seconds", r.meta.get("seconds", "?"))))
    console.print(table)
    load_s = results[0].meta.get("model_load_seconds") if results else None
    if load_s:
        console.print(f"[green]one model load of {load_s}s[/green] shared across "
                      f"{len(results)} product(s)")


@app.command()
def serve(
    port: int = typer.Option(7860, "--port", help="Port to serve the UI on"),
    share: bool = typer.Option(False, "--share", help="Public gradio.live link"),
) -> None:
    """Open the browser UI: pick a photo, type the words, press the button.

    Same pipeline as `dukaan pack`, so the two surfaces cannot drift apart.
    """
    try:
        from .web import build_ui
    except ImportError:
        raise typer.BadParameter(
            "the UI needs gradio, which is an optional extra so the CLI stays "
            "dependency-light. Install it with: pip install -e '.[web]'"
        )
    cfg = load()
    if cfg.offline:
        console.print("[yellow]No DUKAAN_INSTANCE set.[/yellow] The UI will use the CPU preview backend.")
    else:
        console.print(f"Generating on [green]{_masked(cfg.instance)}[/green]")
    # Gradio will not serve a file outside its own cache, the cwd or the
    # system temp dir, and DUKAAN_OUT is frequently none of those.
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    build_ui(cfg).launch(server_port=port, share=share, inbrowser=False,
                         allowed_paths=[str(cfg.out_dir.resolve())])


if __name__ == "__main__":
    app()
