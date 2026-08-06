"""Text splitter"""

import logging
from typing import List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Text chunk"""
    content: str
    metadata: dict


# Import Document type
from .loader import Document


class TextSplitter:
    """Text splitter"""
    
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 128):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
    
    def split(self, documents: List[Document]) -> List[Chunk]:
        """Split documents into chunks"""
        chunks = []
        
        for doc in documents:
            doc_chunks = self._split_text(doc.content, doc.metadata)
            chunks.extend(doc_chunks)
        
        logger.info(f"分块完成: {len(documents)} 文档 -> {len(chunks)} 块")
        return chunks
    
    def _split_text(self, text: str, metadata: dict) -> List[Chunk]:
        """Split by size, keep paragraphs intact"""
        if len(text) <= self.chunk_size:
            return [Chunk(content=text, metadata=metadata)]

        chunks = []
        start = 0

        while start < len(text):
            # Find suitable end position
            end = start + self.chunk_size

            if end >= len(text):
                chunk_text = text[start:]
            else:
                # Try to split at sentence or paragraph boundary
                chunk_text = text[start:end]
                # Find last period or newline
                for sep in ['\n\n', '\n', '. ', '。', '；']:
                    last_sep = chunk_text.rfind(sep)
                    if last_sep > self.chunk_size * 0.5:  # Keep at least half
                        end = start + last_sep + len(sep)
                        chunk_text = text[start:end]
                        break

            chunks.append(Chunk(
                content=chunk_text.strip(),
                metadata={**metadata, "chunk_index": len(chunks)}
            ))

            # Move window, consider overlap
            start = end - self.chunk_overlap if end < len(text) else len(text)
        
        return chunks