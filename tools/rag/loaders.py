from pathlib import Path

from langchain.schema import Document


def load_pdf(path: Path) -> list[Document]:
    """Load a PDF, one Document per non-empty page (page tracked in metadata)."""
    from langchain_community.document_loaders import PyPDFLoader

    loader = PyPDFLoader(str(path))
    pages = loader.load()

    docs = []
    for i, page in enumerate(pages):
        text = page.page_content.strip()
        if not text:
            continue  # skip blank pages rather than indexing empty chunks
        docs.append(Document(page_content=text, metadata={"source": path.name, "page": i}))
    return docs


def load_markdown(path: Path) -> list[Document]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [Document(page_content=text, metadata={"source": path.name, "page": 0})]


def load_text(path: Path) -> list[Document]:
    return load_markdown(path)  # identical handling for plain .txt


def load_file(path: Path) -> list[Document]:
    """Dispatch to the right loader based on file extension.

    Raises ValueError for unsupported types, and ValueError if a PDF has
    no extractable text at all (e.g. a scanned image with no OCR layer) —
    callers should surface this to the user rather than silently indexing
    nothing.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        docs = load_pdf(path)
    elif suffix in (".md", ".markdown"):
        docs = load_markdown(path)
    elif suffix == ".txt":
        docs = load_text(path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    if not docs:
        raise ValueError(
            f"No extractable text found in {path.name}. "
            "If this is a scanned PDF, OCR is not yet supported."
        )
    return docs