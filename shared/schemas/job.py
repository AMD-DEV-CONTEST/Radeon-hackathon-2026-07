from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    input_image_path: str = Field(..., description="Relative path returned by /upload")
    style: str = Field(default="realistic", description="Style template key")
    prompt: str = Field(default="", description="Additional text description")
    output_mode: str = Field(default="fullcolor_3d", description="fullcolor_3d | relief_2d5")


class JobResponse(BaseModel):
    id: str
    status: str
    input_image_path: str
    style: str
    prompt: str
    output_mode: str
    result_model_path: str | None = None
    result_preview_path: str | None = None
    multiview_image_paths: list[str] | None = None
    print_report: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
