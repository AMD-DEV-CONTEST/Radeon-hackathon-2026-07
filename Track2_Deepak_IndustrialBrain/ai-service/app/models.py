from pydantic import BaseModel, Field


class QuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    asset_tag: str = ""
    desired_format: str = "quick_answer"


class RcaRequest(BaseModel):
    asset_tag: str = Field(min_length=2, max_length=100)
    desired_format: str = "report"


class ProcessPathRequest(BaseModel):
    file_path: str
    document_id: str
    original_name: str


class RcaExportRequest(BaseModel):
    asset_tag: str = Field(min_length=2, max_length=100)
    export_format: str = "docx"

