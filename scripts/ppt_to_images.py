"""
InventoryDoc Agent — PPT 转图片工具 (Step 2)

将 PPTX 导出为 1920×1080 PNG 图片。
Linux 使用 LibreOffice headless + pdftoppm，
Windows 使用 PowerPoint COM 自动化。
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _libreoffice_convert(pptx_path: str, slides_dir: str) -> int:
    """Linux: LibreOffice → PDF → pdftoppm → PNG"""
    print("使用 LibreOffice headless 导出...")

    # 先转 PDF
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--norestore",
                "--convert-to", "pdf",
                "--outdir", tmpdir,
                pptx_path,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"LibreOffice 错误: {result.stderr}")
            return -1

        # 找到 PDF
        pdf_files = list(Path(tmpdir).glob("*.pdf"))
        if not pdf_files:
            print("错误: 未生成 PDF 文件")
            return -1
        pdf_path = pdf_files[0]

        # pdftoppm 转 PNG
        print("使用 pdftoppm 导出 PNG...")
        os.makedirs(slides_dir, exist_ok=True)
        result = subprocess.run(
            [
                "pdftoppm", "-png", "-r", "150",
                "-scale-to-x", "1920", "-scale-to-y", "1080",
                str(pdf_path), os.path.join(slides_dir, "slide"),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"pdftoppm 错误: {result.stderr}")
            return -1

    # 重命名 slide-01.png → slide_01.png
    png_files = sorted(Path(slides_dir).glob("slide-*.png"))
    for f in png_files:
        new_name = f.name.replace("slide-", "slide_")
        f.rename(f.parent / new_name)

    return len(png_files)


def _check_dependencies():
    """检查依赖工具是否可用"""
    if shutil.which("libreoffice"):
        return "libreoffice"
    if sys.platform == "win32":
        try:
            import comtypes.client  # noqa
            return "powerpoint"
        except ImportError:
            pass
    print("错误: 未找到 libreoffice 或 comtypes。")
    print("Linux: sudo apt install libreoffice-impress poppler-utils")
    print("Windows: pip install comtypes (需要安装 PowerPoint)")
    return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="将 PPTX 导出为 PNG 图片")
    parser.add_argument("--input", required=True, help="输入的 PPTX 文件路径")
    parser.add_argument("--output", default="output/slides", help="输出的图片目录")
    args = parser.parse_args()

    pptx_path = Path(args.input)
    if not pptx_path.exists():
        print(f"错误: 找不到文件 {pptx_path}")
        sys.exit(1)

    slides_dir = Path(args.output)
    slides_dir.mkdir(parents=True, exist_ok=True)

    engine = _check_dependencies()
    if not engine:
        sys.exit(1)

    if engine == "libreoffice":
        count = _libreoffice_convert(str(pptx_path.resolve()), str(slides_dir.resolve()))
    else:
        print("错误: 当前环境不支持 PowerPoint COM 自动化")
        sys.exit(1)

    if count and count > 0:
        print(f"成功! 共导出 {count} 张幻灯片到 {slides_dir}")
    else:
        print("错误: 导出失败")
        sys.exit(1)


if __name__ == "__main__":
    main()