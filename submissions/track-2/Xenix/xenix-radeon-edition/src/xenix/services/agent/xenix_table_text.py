"""Compatibility re-export for the LLM-owned Xenix Table Text contract.

The formatter is owned by the LLM Tool boundary.  This module remains for
historical imports and does not contain a second implementation.
"""

from ..llm.xenix_table_text import (
    XENIX_TABLE_TEXT_TOOLS_WITH_GENERATED_DATASET_PREVIEW,
    render_xenix_table_tool_result,
)

__all__ = [
    "XENIX_TABLE_TEXT_TOOLS_WITH_GENERATED_DATASET_PREVIEW",
    "render_xenix_table_tool_result",
]
