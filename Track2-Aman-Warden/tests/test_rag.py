"""Tests for ChromaDB WardenRetriever."""

import os
from warden.rag.retriever import WardenRetriever


class TestWardenRetriever:
    def setup_method(self):
        self.db_path = "test_rag_db"
        self.retriever = WardenRetriever(db_path=self.db_path)
        # We mock chromadb so this runs without needing it installed
        # if chromadb is missing, initialize() returns False.
        self.has_chroma = False
        try:
            import chromadb
            self.has_chroma = True
        except ImportError:
            pass

    def test_initialize(self):
        if self.has_chroma:
            assert self.retriever.initialize()
            assert self.retriever.is_available()
        else:
            assert not self.retriever.initialize()
            assert not self.retriever.is_available()

    def test_retrieve_for_check_when_unavailable(self):
        # Should gracefully return empty string
        assert self.retriever.retrieve_for_check("test query") == ""

    def test_add_patterns_when_unavailable(self):
        assert self.retriever.add_patterns([{"text": "test"}]) == 0
