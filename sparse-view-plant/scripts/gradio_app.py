"""Launch the Plant-aware 2DGS Gradio showcase."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

# Gradio resolves its cache location during import.
import gradio as gr

from sparse_view_plant.showcase import (
    DEFAULT_EXAMPLES_MANIFEST,
    DEFAULT_EXAMPLES_ROOT,
    DEFAULT_OUTPUTS_DIR,
    SHOWCASE_CSS,
    build_app,
    configure_local_vggt,
    ensure_localhost_no_proxy,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--inbrowser", action="store_true")
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=DEFAULT_OUTPUTS_DIR,
        help="directory where live reconstruction runs and Model3D caches are stored",
    )
    parser.add_argument(
        "--examples-manifest",
        type=Path,
        default=DEFAULT_EXAMPLES_MANIFEST,
        help="TOML manifest of curated live-reconstruction photo groups",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    ensure_localhost_no_proxy()
    vggt = configure_local_vggt()
    if vggt:
        print(
            "[gradio] VGGT runtime: "
            + ", ".join(f"{name}={path}" for name, path in vggt.items())
        )
    else:
        print(
            "[gradio] VGGT runtime not found; set VGGT_SRC/VGGT_CKPT (or "
            "pointcloud.source_dir/ckpt_path) before reconstructing."
        )
    if "source" in vggt and "checkpoint" not in vggt:
        print(
            "[gradio] VGGT checkpoint not found; set VGGT_CKPT or "
            "pointcloud.ckpt_path before reconstructing."
        )
    outputs_dir = args.outputs_dir.resolve()
    demo = build_app(
        outputs_dir,
        example_manifest=args.examples_manifest,
    )
    allowed_paths = [str(outputs_dir)]
    if DEFAULT_EXAMPLES_ROOT.is_dir():
        allowed_paths.append(str(DEFAULT_EXAMPLES_ROOT))
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        inbrowser=args.inbrowser,
        allowed_paths=allowed_paths,
        max_file_size="1gb",
        theme=gr.themes.Soft(primary_hue="green", neutral_hue="slate"),
        css=SHOWCASE_CSS,
        footer_links=["api"],
    )


if __name__ == "__main__":
    main()
