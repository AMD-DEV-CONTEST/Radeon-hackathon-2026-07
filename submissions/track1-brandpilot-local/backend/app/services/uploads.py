import io
from pathlib import Path
from uuid import uuid4
import aiofiles
from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from app.core.config import ALLOWED_TYPES, MAX_UPLOAD_SIZE

async def validate_and_store(file: UploadFile, directory: Path) -> dict:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only PNG, JPEG, and WebP images are supported")
    data = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Image exceeds the upload limit")
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image is empty")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            detected = image.format
            width, height = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail="Malformed or unsupported image") from exc
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[file.content_type]
    if detected != expected:
        raise HTTPException(status_code=400, detail="Image signature does not match its content type")
    directory.mkdir(parents=True, exist_ok=True)
    asset_id = str(uuid4())
    safe_name = f"{asset_id}.{ALLOWED_TYPES[file.content_type]}"
    async with aiofiles.open(directory / safe_name, "wb") as output:
        await output.write(data)
    return {"asset_id": asset_id, "storage_name": safe_name, "content_type": file.content_type, "size_bytes": len(data), "width": width, "height": height, "url": f"/projects/{directory.parent.name}/assets/{safe_name}"}
