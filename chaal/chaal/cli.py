"""Command line for Chaal.

`doctor` exists because of a specific trap. A ROCm container is normally built
without any OpenGL libraries, and Genesis needs a working offscreen GL context
to build a scene even when nothing is being rendered. Without `libEGL` you get
an `AttributeError` from deep inside PyOpenGL that says nothing about the real
cause. `doctor` checks for it before you spend GPU time finding out.
"""
from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help=__doc__)


@app.command()
def doctor() -> None:
    """Report the GPU, the stack, and whether a scene can actually be built."""
    import torch

    props = torch.cuda.get_device_properties(0)
    print(f"arch:            {props.gcnArchName}")
    print(f"vram_gb:         {props.total_memory / 2**30:.1f}")
    print(f"compute_units:   {props.multi_processor_count}")
    print(f"torch:           {torch.__version__}")

    import genesis as gs

    print(f"genesis:         {gs.__version__}")

    import ctypes

    gl = "missing"
    for lib in ("libEGL.so.1", "libOSMesa.so.8"):
        try:
            ctypes.CDLL(lib)
            gl = lib
            break
        except OSError:
            continue
    print(f"gl_platform:     {gl}")
    if gl == "missing":
        print()
        print("No OpenGL platform. Genesis builds an offscreen renderer even for")
        print("headless training, so scene.build() will fail. Install one with:")
        print("  apt-get install -y libegl1 libegl-mesa0 libgl1-mesa-dri libosmesa6")
        raise typer.Exit(1)
    print("ready")


@app.command()
def train(
    num_envs: int = 4096,
    iterations: int = 300,
    seed: int = 1,
    log_dir: str = "runs/go2",
) -> None:
    """Train a locomotion policy, simulation and updates both on the GPU."""
    from .train import run

    run(num_envs=num_envs, max_iterations=iterations, seed=seed, log_dir=log_dir)


@app.command()
def bench(
    envs: str = "256,512,1024,2048,4096,8192",
    out: str = "bench-results/scaling.json",
) -> None:
    """Sweep environment count against simulation and training throughput."""
    from .bench import sweep

    sweep(env_counts=tuple(int(x) for x in envs.split(",")), out=out)


@app.command()
def evaluate(
    checkpoint: str,
    num_envs: int = 512,
    out: str = "bench-results/robustness.json",
) -> None:
    """Score a trained policy under payload, friction and push perturbations."""
    from .eval import run_all

    run_all(checkpoint=checkpoint, num_envs=num_envs, out=out)


if __name__ == "__main__":
    app()
