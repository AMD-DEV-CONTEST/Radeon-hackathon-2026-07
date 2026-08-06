import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class RecursiveCharacterTextSplitter:
    """Recursively splits text into chunks using a list of hierarchy-ordered separators."""

    DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        separators: Optional[List[str]] = None,
    ):
        """Initializes the splitter.

        Args:
            chunk_size: Maximum character count per chunk.
            chunk_overlap: Overlap between consecutive chunks.
            separators: List of separator strings ordered by preference.
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

    def split_text(self, text: str) -> List[str]:
        """Splits text into chunks respecting chunk_size and chunk_overlap.

        Args:
            text: Input string.

        Returns:
            List of chunk strings.
        """
        if not text or not text.strip():
            return []
        return self._split(text, self.separators)

    def _split(self, text: str, separators: List[str]) -> List[str]:
        final_chunks: List[str] = []
        separator = separators[-1]
        new_separators: List[str] = []

        for i, _s in enumerate(separators):
            if _s == "":
                separator = _s
                break
            if _s in text:
                separator = _s
                new_separators = separators[i + 1:]
                break

        splits = text.split(separator) if separator else list(text)

        good_splits: List[str] = []
        for s in splits:
            if len(s) <= self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    merged = self._merge_splits(good_splits, separator)
                    final_chunks.extend(merged)
                    good_splits = []
                if new_separators:
                    other_chunks = self._split(s, new_separators)
                    final_chunks.extend(other_chunks)
                else:
                    final_chunks.append(s)

        if good_splits:
            merged = self._merge_splits(good_splits, separator)
            final_chunks.extend(merged)

        return final_chunks

    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:
        docs: List[str] = []
        current_doc: List[str] = []
        total = 0

        for s in splits:
            len_s = len(s)
            sep_len = len(separator) if current_doc else 0

            if total + len_s + sep_len > self.chunk_size:
                if current_doc:
                    doc_str = separator.join(current_doc).strip()
                    if doc_str:
                        docs.append(doc_str)
                    while current_doc and (
                        total > self.chunk_overlap or total + len_s + sep_len > self.chunk_size
                    ):
                        removed = current_doc.pop(0)
                        total -= len(removed) + (len(separator) if current_doc else 0)
                        if total < 0:
                            total = 0
                current_doc.append(s)
                total += len_s + (len(separator) if len(current_doc) > 1 else 0)
            else:
                current_doc.append(s)
                total += len_s + sep_len

        if current_doc:
            doc_str = separator.join(current_doc).strip()
            if doc_str:
                docs.append(doc_str)

        return docs


class DocumentLoader:
    """File ingestion pipeline supporting PDF, DOCX, and text formats."""

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".py", ".js", ".json"}

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        """Initializes the DocumentLoader.

        Args:
            chunk_size: Maximum size of each chunk.
            chunk_overlap: Overlapping characters between consecutive chunks.
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    def load_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Loads a single file and chunks its contents with metadata.

        Args:
            file_path: Path to the document.

        Returns:
            List of chunk dicts with 'text' and 'metadata'.
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"File not found: {file_path}")
            return []

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            logger.warning(f"Unsupported file extension: {ext}")
            return []

        if ext == ".pdf":
            return self._load_and_chunk_pdf(str(path))

        text = ""
        try:
            if ext == ".docx":
                text = self._load_docx(str(path))
            else:
                with open(str(path), "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return []

        return self.chunk_text(text, source=str(path))

    def load_directory(self, dir_path: str, recursive: bool = True) -> List[Dict[str, Any]]:
        """Loads all supported files in a directory.

        Args:
            dir_path: Path to directory.
            recursive: Whether to scan subdirectories.

        Returns:
            Combined list of all document chunks.
        """
        all_chunks: List[Dict[str, Any]] = []
        path = Path(dir_path)

        if not path.is_dir():
            logger.error(f"Directory not found: {dir_path}")
            return []

        pattern = "**/*" if recursive else "*"
        for file_path in path.glob(pattern):
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                all_chunks.extend(self.load_file(str(file_path)))

        return all_chunks

    def chunk_text(self, text: str, source: str = "", extra_metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Splits text into overlapping chunks using recursive character splitting.

        Args:
            text: Raw document string.
            source: File path or source identifier.
            extra_metadata: Optional dict of additional metadata fields.

        Returns:
            List of chunk dictionaries containing text and metadata.
        """
        if not text or not text.strip():
            return []

        raw_chunks = self.splitter.split_text(text)
        filename = Path(source).name if source else "unknown"
        ext = Path(source).suffix.lower() if source else "unknown"

        results = []
        for idx, chunk_str in enumerate(raw_chunks):
            meta = {
                "source": source,
                "filename": filename,
                "chunk_index": idx,
                "file_type": ext,
            }
            if extra_metadata:
                meta.update(extra_metadata)

            results.append({"text": chunk_str, "metadata": meta})

        return results

    def _load_and_chunk_pdf(self, path: str) -> List[Dict[str, Any]]:
        """Loads PDF using pdf-inspector as primary, PyMuPDF as fallback, raw text as last resort."""
        filename = Path(path).name
        pages_data = self._extract_pdf_pages(path)

        all_chunks: List[Dict[str, Any]] = []
        chunk_index = 0

        for page_info in pages_data:
            page_num = page_info.get("page", 1)
            page_text = page_info.get("text", "")
            if not page_text.strip():
                continue

            raw_chunks = self.splitter.split_text(page_text)
            for c_str in raw_chunks:
                all_chunks.append({
                    "text": c_str,
                    "metadata": {
                        "source": path,
                        "filename": filename,
                        "page": page_num,
                        "chunk_index": chunk_index,
                        "file_type": ".pdf",
                    }
                })
                chunk_index += 1

        return all_chunks

    def _extract_pdf_pages(self, path: str) -> List[Dict[str, Any]]:
        """Extracts text per page from PDF.

        Primary: pdf-inspector
        Fallback: PyMuPDF (fitz)
        Final fallback: raw file read
        """
        # 1. Primary: pdf-inspector
        try:
            import pdf_inspector
            res = None
            if hasattr(pdf_inspector, "extract"):
                res = pdf_inspector.extract(path)
            elif hasattr(pdf_inspector, "to_markdown"):
                res = pdf_inspector.to_markdown(path)
            elif hasattr(pdf_inspector, "inspect"):
                res = pdf_inspector.inspect(path)

            pages = []
            if isinstance(res, list):
                for idx, item in enumerate(res):
                    t = item.get("text", "") if isinstance(item, dict) else str(item)
                    if t.strip():
                        pages.append({"text": t, "page": idx + 1})
            elif isinstance(res, str) and res.strip():
                pages.append({"text": res, "page": 1})
            elif isinstance(res, dict):
                t = res.get("text") or res.get("markdown") or ""
                if t.strip():
                    pages.append({"text": t, "page": 1})

            if pages:
                logger.info(f"Extracted PDF using pdf-inspector: {path}")
                return pages
        except Exception as e:
            logger.warning(f"pdf-inspector unavailable or failed for {path}: {e}. Trying PyMuPDF fallback.")

        # 2. Fallback: PyMuPDF (fitz)
        try:
            import fitz
            doc = fitz.open(path)
            pages = []
            for page_num in range(len(doc)):
                try:
                    page = doc[page_num]
                    t = page.get_text("text") or ""
                    if t.strip():
                        pages.append({"text": t, "page": page_num + 1})
                except Exception as page_err:
                    logger.warning(f"Error reading page {page_num+1} of {path}: {page_err}")
                    continue

            if pages:
                logger.info(f"Extracted PDF using PyMuPDF: {path}")
                return pages
        except Exception as e:
            logger.warning(f"PyMuPDF unavailable or failed for {path}: {e}")

        # 3. Final fallback: raw text reading
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                t = f.read()
                if t.strip():
                    return [{"text": t, "page": 1}]
        except Exception as e:
            logger.error(f"Failed to read PDF {path}: {e}")

        return []

    def _load_docx(self, path: str) -> str:
        """Extracts text from a DOCX file."""
        try:
            import docx
            doc = docx.Document(path)
            return "\n".join([para.text for para in doc.paragraphs])
        except ImportError:
            logger.warning("python-docx not installed. Falling back to raw text reading.")
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read DOCX {path}: {e}")
            return ""
