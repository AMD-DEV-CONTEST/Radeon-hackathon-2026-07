"""Export a distilled PyTorch student through ONNX to MIGraphX."""

from __future__ import annotations

from pathlib import Path

import torch


def export_student(model: torch.nn.Module, observation_dim: int, output_dir: str | Path = "checkpoints/deployment") -> dict[str, Path]:
    """Write PyTorch weights and a static-batch ONNX graph for the student."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    model = model.eval().cpu()
    torch_path, onnx_path = output / "student.pt", output / "student.onnx"
    torch.save(model.state_dict(), torch_path)
    torch.onnx.export(
        model,
        torch.zeros(1, observation_dim),
        onnx_path,
        input_names=["observation"],
        output_names=["action"],
        dynamic_axes={"observation": {0: "batch"}, "action": {0: "batch"}},
        opset_version=17,
    )
    return {"pytorch": torch_path, "onnx": onnx_path}


def compile_migraphx(onnx_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Parse and compile ONNX for the installed ROCm MIGraphX GPU target."""
    try:
        import migraphx
    except ImportError as error:
        raise ImportError("Install ROCm MIGraphX to compile the ONNX deployment model.") from error
    onnx_path = Path(onnx_path)
    output = Path(output_path) if output_path else onnx_path.with_suffix(".mxr")
    program = migraphx.parse_onnx(str(onnx_path))
    program.compile(migraphx.get_target("gpu"))
    migraphx.save(program, str(output))
    return output
