"""Document analysis tools: parse insurance document structure."""
from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_sections(content: str) -> list[dict]:
    """Extract the section structure from an insurance document.
    
    Args:
        content: document content
        
    Returns:
        section list, each item contains title and content
    """
    # match section titles starting with Chinese numerals or Arabic numerals
    pattern = r"(第[一二三四五六七八九十百]+章|第\d+章|\d+[\.\、])\s*(.+?)(?:\n|$)"
    sections = []
    lines = content.split("\n")
    
    current_title = "概述"
    current_lines = []
    
    for line in lines:
        match = re.match(pattern, line.strip())
        if match:
            if current_lines:
                sections.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = match.group(0).strip()
            current_lines = []
        else:
            current_lines.append(line)
    
    if current_lines:
        sections.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip(),
        })
    
    logger.info("extracted sections: %d", len(sections))
    return sections


def extract_key_terms(content: str) -> list[str]:
    """Extract key clause terms from an insurance document.
    
    Args:
        content: document content
        
    Returns:
        list of key terms
    """
    # common insurance-domain keyword patterns
    patterns = [
        r"保险责任[：:]",
        r"免责条款",
        r"免赔额",
        r"等待期",
        r"理赔",
        r"保费",
        r"保额",
        r"被保险人",
        r"投保人",
        r"受益人",
        r"保险期间",
        r"犹豫期",
    ]
    
    terms = set()
    for pattern in patterns:
        matches = re.findall(pattern, content)
        terms.update(matches)
    
    logger.info("extracted key terms: %d", len(terms))
    return sorted(terms)