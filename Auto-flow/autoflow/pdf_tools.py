"""Reliable PDF-to-text conversion for local AutoFlow commands."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass(slots=True)
class PDFConversionItem:
    source: str
    output: str
    status: str
    pages: int = 0
    characters: int = 0
    message: str = ""


class PDFTextConverter:
    """Extract text from one PDF or every PDF in a directory."""

    def discover(self, source: str | Path) -> list[Path]:
        path = Path(source).expanduser()
        if not path.exists():
            raise ValueError(f"找不到源文件或文件夹：{path}")
        if path.is_file():
            if path.suffix.lower() != ".pdf":
                raise ValueError("源文件不是 PDF。")
            return [path.resolve()]
        return sorted(
            (item.resolve() for item in path.rglob("*.pdf") if item.is_file()),
            key=lambda item: str(item).lower(),
        )

    def preview(self, source: str | Path, destination: str | Path) -> dict[str, Any]:
        files = self.discover(source)
        output_dir = Path(destination).expanduser().resolve()
        conflicts = [str(output_dir / f"{item.stem}.txt") for item in files if (output_dir / f"{item.stem}.txt").exists()]
        return {
            "source": str(Path(source).expanduser().resolve()),
            "destination": str(output_dir),
            "files": [str(item) for item in files],
            "file_count": len(files),
            "conflicts": conflicts,
        }

    def convert(
        self,
        source: str | Path,
        destination: str | Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        preview = self.preview(source, destination)
        output_dir = Path(preview["destination"])
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[PDFConversionItem] = []

        for filename in preview["files"]:
            pdf_path = Path(filename)
            output_path = output_dir / f"{pdf_path.stem}.txt"
            if output_path.exists() and not overwrite:
                results.append(PDFConversionItem(str(pdf_path), str(output_path), "skipped", message="TXT 已存在，未覆盖。"))
                continue
            try:
                reader = PdfReader(str(pdf_path))
                pages: list[str] = []
                for page_number, page in enumerate(reader.pages, start=1):
                    extracted = (page.extract_text() or "").strip()
                    pages.append(f"--- 第 {page_number} 页 ---\n{extracted}")
                text = "\n\n".join(pages).strip() + "\n"
                meaningful = sum(char.isalnum() for char in text.split("---", 1)[-1])
                if meaningful < 8:
                    results.append(PDFConversionItem(str(pdf_path), str(output_path), "needs_ocr", pages=len(reader.pages), message="没有检测到可提取文字，可能是扫描版 PDF，需要 OCR。"))
                    continue
                output_path.write_text(text, encoding="utf-8")
                verified = output_path.read_text(encoding="utf-8")
                if not verified.strip():
                    raise RuntimeError("输出文件验证失败。")
                results.append(PDFConversionItem(str(pdf_path), str(output_path), "converted", pages=len(reader.pages), characters=len(verified)))
            except Exception as exc:  # One bad PDF must not stop a whole batch.
                results.append(PDFConversionItem(str(pdf_path), str(output_path), "failed", message=str(exc)))

        data = [asdict(item) for item in results]
        converted = sum(item.status == "converted" for item in results)
        return {
            "destination": str(output_dir),
            "converted": converted,
            "skipped": sum(item.status == "skipped" for item in results),
            "needs_ocr": sum(item.status == "needs_ocr" for item in results),
            "failed": sum(item.status == "failed" for item in results),
            "items": data,
        }
