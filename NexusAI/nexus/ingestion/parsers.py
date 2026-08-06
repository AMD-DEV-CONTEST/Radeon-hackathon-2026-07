import io
import json
from pathlib import Path
from docx import Document
from pypdf import PdfReader

class UnsupportedFileType(ValueError):
    pass

def parse_bytes(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()

    if suffix == ".txt":
        return content.decode("utf-8", errors="replace")

    if suffix == ".json":
        data = json.loads(content.decode("utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)

    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix == ".docx":
        document = Document(io.BytesIO(content))
        return "\n".join(p.text for p in document.paragraphs)

    raise UnsupportedFileType(f"Unsupported file type: {suffix or 'unknown'}")
