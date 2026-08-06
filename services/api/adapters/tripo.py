import asyncio
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from adapters.base import ThreeDProvider, MeshAsset


class TripoProvider(ThreeDProvider):
    """Tripo3D cloud API adapter.

    Supports both single-image and multi-view image-to-3D generation.
    See: https://github.com/VAST-AI-Research/tripo-python-sdk
    """

    name = "tripo"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def generate_3d_from_text(self, prompt: str, style: str, output_path: Path | None = None, **kwargs) -> MeshAsset:
        return asyncio.run(self._generate_from_text(prompt, style, output_path))

    def generate_3d_from_images(
        self, images: list[Path], prompt: str, style: str, output_path: Path | None = None, **kwargs
    ) -> MeshAsset:
        return asyncio.run(self._generate_from_images(images, prompt, style, output_path))

    async def _generate_from_text(
        self, prompt: str, style: str, output_path: Path | None
    ) -> MeshAsset:
        from tripo3d import TripoClient

        async with TripoClient(api_key=self.api_key) as client:
            task_id = await client.text_to_model(
                prompt=prompt,
                texture=True,
                pbr=False,
                model_version="v2.5-20250123",
            )
            return await self._wait_download(client, task_id, output_path)

    async def _generate_from_images(
        self, images: list[Path], prompt: str, style: str, output_path: Path | None
    ) -> MeshAsset:
        from tripo3d import TripoClient

        async with TripoClient(api_key=self.api_key) as client:
            tokens = [await client.upload_file(str(p)) for p in images]
            if len(tokens) == 1:
                task_id = await client.image_to_model(
                    image=tokens[0],
                    texture=True,
                    pbr=False,
                    model_version="v2.5-20250123",
                )
            else:
                task_id = await client.multiview_to_model(
                    images=tokens,
                    texture=True,
                    pbr=False,
                    model_version="v2.5-20250123",
                )
            return await self._wait_download(client, task_id, output_path)

    async def _wait_download(self, client, task_id: str, output_path: Path | None) -> MeshAsset:
        task = await client.wait_for_task(task_id, timeout=600, verbose=True)
        if task.status != "success":
            raise RuntimeError(f"Tripo task {task_id} failed: {task.error_msg}")

        with TemporaryDirectory() as tmpdir:
            files = await client.download_task_models(task, output_dir=tmpdir)
            downloaded = Path(files.get("model") or files.get("base_model"))
            if not downloaded or not downloaded.exists():
                raise RuntimeError(f"Tripo task {task_id} returned no model file")

            if output_path is None:
                output_path = downloaded
            else:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(downloaded, output_path)

            texture_path = files.get("pbr_model")
            if texture_path:
                texture_path = Path(texture_path)
            return MeshAsset(mesh_path=output_path, texture_path=texture_path)
