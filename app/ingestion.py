"""
Document ingestion: PDF → text → chunks → embeddings → ChromaDB.
"""
import os
import shutil
import logging
from typing import List
from PyPDF2 import PdfReader
from langchain_text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from app.vectorstore import get_vectorstore
from config import CHUNK_SIZE, CHUNK_OVERLAP, UPLOAD_DIR

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_path: str) -> str:
    """Extract raw text from a single PDF file."""
    text_parts = []
    
    try:
        reader = PdfReader(file_path)
        for page_num, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
            except Exception as e:
                logger.warning(f"Failed to extract text from page {page_num} of {file_path}: {e}")
    except Exception as e:
        logger.error(f"Failed to read PDF '{file_path}': {e}")
        return ""
    
    full_text = "\n".join(text_parts)
    logger.info(f"Extracted {len(full_text)} characters from '{os.path.basename(file_path)}'.")
    return full_text


def chunk_text(text: str, source_name: str) -> List[Document]:
    """Split text into overlapping chunks with metadata."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    raw_chunks = splitter.split_text(text)
    
    documents = [
        Document(
            page_content=chunk,
            metadata={"source": source_name, "chunk_index": i},
        )
        for i, chunk in enumerate(raw_chunks)
    ]
    
    logger.info(f"Split '{source_name}' into {len(documents)} chunks.")
    return documents


def ingest_documents(files: List[str]) -> str:
    """
    Full ingestion pipeline for uploaded PDFs.
    Returns a status string for the UI.
    """
    if not files:
        return "No files provided."
    
    vectorstore = get_vectorstore()
    total_chunks = 0
    processed_files = []
    failed_files = []
    
    for file_path in files:
        try:
            filename = os.path.basename(file_path)
            dest_path = os.path.join(UPLOAD_DIR, filename)
            
            if os.path.abspath(file_path) != os.path.abspath(dest_path):
                shutil.copy(file_path, dest_path)
            
            text = extract_text_from_pdf(dest_path)
            if not text.strip():
                logger.warning(f"No extractable text found in '{filename}'. Skipping.")
                failed_files.append(filename)
                continue
            
            chunks = chunk_text(text, source_name=filename)
            if chunks:
                vectorstore.add_documents(chunks)
                total_chunks += len(chunks)
                processed_files.append(filename)
        
        except Exception as e:
            logger.error(f"Error processing '{file_path}': {e}")
            failed_files.append(os.path.basename(file_path))
    
    try:
        vectorstore.persist()
    except Exception as e:
        logger.error(f"Failed to persist vector store: {e}")
    
    status_lines = []
    if processed_files:
        status_lines.append(
            f"✅ Indexed {len(processed_files)} file(s): {', '.join(processed_files)} "
            f"({total_chunks} chunks total)."
        )
    if failed_files:
        status_lines.append(f"❌ Failed/empty: {', '.join(failed_files)}.")
    if not status_lines:
        status_lines.append("Nothing was indexed.")
    
    result = " ".join(status_lines)
    logger.info(result)
    return result