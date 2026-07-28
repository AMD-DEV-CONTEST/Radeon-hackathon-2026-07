"""
Unit tests for RAG index builder and retriever.
Uses a small in-memory corpus — no real ROCm docs required.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rag.index_builder import build_index, _split_by_section, _split_by_paragraph
from src.rag.retriever import retrieve, _tfidf_retrieve, _build_tfidf_index, _tokenize


MINI_CORPUS = {
    "hip_guide.md": """# HIP Porting Guide

## Memory Coalescing

Memory coalescing means adjacent threads access adjacent addresses.
Non-coalesced access causes multiple VRAM transactions per wavefront.
Fix: use x.contiguous() before kernel launch.

## Wavefront Size

AMD GPUs use a wavefront size of 64 threads, not 32 like NVIDIA warps.
Block sizes should be multiples of 64 for full utilization.
""",
    "rocm_smi.md": """# rocm-smi Reference

## GPU Utilization

GPU use percentage shows how busy the compute units are.
Low utilization under 50 percent suggests memory-bound workload.
High utilization over 90 percent suggests compute-bound workload.

## VRAM Usage

Total VRAM used divided by total VRAM shows memory pressure.
Near 100 percent risks out-of-memory errors.
""",
    "optimization.md": """# Optimization Patterns

## LDS Bank Conflicts

LDS is organized into 32 banks on AMD hardware.
Multiple threads hitting the same bank are serialized.
Fix: add padding of 1 to shared memory arrays.

## Occupancy

Occupancy is active wavefronts divided by maximum wavefronts.
Low occupancy means register pressure or too much shared memory per block.
Use launch_bounds hint to guide compiler register allocation.
""",
}


class TestIndexBuilder(unittest.TestCase):

    def setUp(self):
        self.corpus_dir = tempfile.mkdtemp()
        self.index_dir = tempfile.mkdtemp()

        # Write mini corpus to temp dir
        for filename, content in MINI_CORPUS.items():
            with open(os.path.join(self.corpus_dir, filename), "w") as f:
                f.write(content)

    def test_build_index_returns_chunk_count(self):
        result = build_index(
            corpus_dir=self.corpus_dir,
            index_dir=self.index_dir,
            backend="json_tfidf",  # no FAISS required
        )
        self.assertIsNone(result.get("error"))
        self.assertGreater(result["num_chunks"], 0)

    def test_build_index_creates_chunks_json(self):
        build_index(corpus_dir=self.corpus_dir, index_dir=self.index_dir)
        chunks_path = os.path.join(self.index_dir, "chunks.json")
        self.assertTrue(os.path.exists(chunks_path))

    def test_split_by_section_produces_sections(self):
        text = """# Title
Introduction text here.

## Section A
Content of section A with details.

## Section B
Content of section B with other details.
"""
        sections = _split_by_section(text, "test.md")
        self.assertGreater(len(sections), 1)
        section_titles = [s["section"] for s in sections]
        self.assertTrue(any("Section A" in t for t in section_titles))

    def test_split_by_paragraph_respects_max(self):
        long_text = "\n\n".join(["A paragraph of text. " * 20] * 10)
        chunks = _split_by_paragraph(long_text, max_chars=500)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 600)  # some tolerance


class TestRetriever(unittest.TestCase):

    def setUp(self):
        self.chunks = [
            {"source": "hip_guide.md", "section": "Memory Coalescing",
             "text": "Memory coalescing means adjacent threads access adjacent addresses. "
                     "Non-coalesced access causes multiple VRAM transactions per wavefront. "
                     "Fix: use x.contiguous() before kernel launch."},
            {"source": "hip_guide.md", "section": "Wavefront Size",
             "text": "AMD GPUs use a wavefront size of 64 threads, not 32 like NVIDIA warps. "
                     "Block sizes should be multiples of 64 for full utilization."},
            {"source": "rocm_smi.md", "section": "GPU Utilization",
             "text": "GPU use percentage shows how busy the compute units are. "
                     "Low utilization under 50 percent suggests memory-bound workload."},
            {"source": "optimization.md", "section": "LDS Bank Conflicts",
             "text": "LDS is organized into 32 banks on AMD hardware. "
                     "Multiple threads hitting the same bank are serialized. "
                     "Fix: add padding of 1 to shared memory arrays."},
        ]

    def test_tfidf_retrieval_returns_results(self):
        results = _tfidf_retrieve("memory coalescing wavefront", top_k=2, chunks=self.chunks)
        self.assertEqual(len(results), 2)
        self.assertIn("source", results[0])
        self.assertIn("text", results[0])
        self.assertIn("score", results[0])

    def test_tfidf_retrieval_ranks_relevant_first(self):
        results = _tfidf_retrieve("LDS bank conflicts shared memory", top_k=3, chunks=self.chunks)
        # The LDS document should rank highest
        self.assertIn("LDS", results[0]["text"])

    def test_tfidf_retrieval_respects_top_k(self):
        results = _tfidf_retrieve("memory", top_k=2, chunks=self.chunks)
        self.assertLessEqual(len(results), 2)

    def test_tokenizer_lowercases(self):
        tokens = _tokenize("Memory COALESCING AMD GPU")
        self.assertTrue(all(t == t.lower() for t in tokens))

    def test_tokenizer_strips_punctuation(self):
        tokens = _tokenize("hello, world! this is a test.")
        self.assertNotIn(",", tokens)
        self.assertNotIn("!", tokens)

    def test_tfidf_index_structure(self):
        index = _build_tfidf_index(self.chunks)
        self.assertIn("tf", index)
        self.assertIn("idf", index)
        self.assertIn("memory", index["idf"])


if __name__ == "__main__":
    unittest.main()
