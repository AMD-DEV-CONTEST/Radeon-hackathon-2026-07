from pydantic import BaseModel


class StyleTemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    output_mode: str
    style_prompt: str
    negative_prompt: str
    postprocess_params: dict
    sample_image_url: str

    class Config:
        from_attributes = True
