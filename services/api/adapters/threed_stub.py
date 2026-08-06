from pathlib import Path

from adapters.base import ThreeDProvider, MeshAsset


class StubThreeDProvider(ThreeDProvider):
    """Stub 3D provider for integration testing without API keys."""

    name = "stub_3d"

    def generate_3d_from_images(
        self, images: list[Path], prompt: str, style: str, output_path: Path | None = None, **kwargs
    ) -> MeshAsset:
        # For integration testing: write a tiny placeholder STL if an output path is requested.
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("solid placeholder\nendsolid placeholder\n")
            return MeshAsset(mesh_path=output_path)
        return MeshAsset(mesh_path=images[0])

    def generate_3d_from_text(self, prompt: str, style: str, output_path: Path | None = None) -> MeshAsset:
        raise NotImplementedError("Stub does not support text-to-3D.")
