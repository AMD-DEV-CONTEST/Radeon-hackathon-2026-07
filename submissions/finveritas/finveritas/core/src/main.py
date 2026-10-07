#!/usr/bin/env python3
"""
Bloomberg OCR Ingestion Agent — CLI entry point.

Usage:
    python -m src.main [--input INPUT_DIR] [--output OUTPUT_DIR] [--verbose]

Scans INPUT_DIR for PDF files, extracts and parses financial statement data
(Income Statements / Balance Sheets), and writes one structured JSON file per
company into OUTPUT_DIR.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .builder import aggregate_and_write
from .extractor import extract_pdf
from .parser import ParsedStatement, parse_statement

logger = logging.getLogger("bloomberg_ocr")


def discover_pdfs(input_dir: Path) -> list[Path]:
    """Return all PDF files in *input_dir* (non-recursive)."""
    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        pdfs = sorted(input_dir.glob("*.PDF"))
    return pdfs


def run_pipeline(input_dir: Path, output_dir: Path) -> None:
    """Execute the full ingestion pipeline."""
    pdfs = discover_pdfs(input_dir)
    if not pdfs:
        logger.error("No PDF files found in %s", input_dir)
        sys.exit(1)

    logger.info("Found %d PDF(s) in %s", len(pdfs), input_dir)

    statements: list[ParsedStatement] = []

    for pdf_path in pdfs:
        logger.info("Processing: %s", pdf_path.name)

        # Step 1 — Extract text & tables
        content = extract_pdf(pdf_path)
        if not content.pages:
            logger.warning("Skipping %s — no pages extracted", pdf_path.name)
            continue

        # Step 2 — Parse into structured data
        parsed = parse_statement(content)

        if not parsed.data:
            logger.warning(
                "Skipping %s — no recognised financial data", pdf_path.name
            )
            continue

        logger.info(
            "  → %s | %s | %s | %d fields | periods: %s",
            parsed.company,
            parsed.statement_type or "??",
            parsed.currency,
            len(parsed.data),
            ", ".join(parsed.periods) if parsed.periods else "none",
        )
        statements.append(parsed)

    if not statements:
        logger.error("No usable financial data extracted from any PDF.")
        sys.exit(1)

    # Step 3 — Build JSON output per company
    written = aggregate_and_write(statements, output_dir)
    logger.info(
        "Done — wrote %d JSON file(s) to %s",
        len(written),
        output_dir,
    )
    for p in written:
        logger.info("  • %s", p.name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bloomberg PDF → structured JSON ingestion agent",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("input_pdfs"),
        help="Directory containing Bloomberg PDF exports (default: input_pdfs/)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directory for JSON output files (default: output/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug-level logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # pdfplumber uses pdfminer under the hood; its DEBUG logs are extremely noisy
    # and make --verbose hard to use.
    logging.getLogger("pdfminer").setLevel(logging.WARNING)

    input_dir: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_dir.is_dir():
        logger.error("Input directory does not exist: %s", input_dir)
        sys.exit(1)

    run_pipeline(input_dir, output_dir)


if __name__ == "__main__":
    main()
