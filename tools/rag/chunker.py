from langchain.schema import Document
from langchain.text_splitter import SentenceTransformersTokenTextSplitter

from .config import CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_MODEL_NAME


def chunk_documents(
    docs: list[Document],
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[Document]:
    """Split documents into chunks sized against the embedding model's own
    tokenizer (not raw characters) — this is what your evaluation notebook
    used, and it's more faithful than a character-count splitter since the
    embedding model sees tokens, not characters.
    """
    splitter = SentenceTransformersTokenTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        model_name=EMBEDDING_MODEL_NAME,
    )
    chunks = splitter.split_documents(docs)

    # chunk_id is assigned per resulting chunk; source/page metadata is
    # already carried over from the parent Document by the splitter.
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i

    return chunks