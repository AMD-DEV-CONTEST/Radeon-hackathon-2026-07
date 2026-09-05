# Argos Test Scripts

This directory contains all test and simulation scripts for the Argos AI Companion project.

## Test Scripts

| Script | Description | API Calls | Tests |
|--------|-------------|-----------|-------|
| `test_chatbox_sim.py` | Chatbox UI simulation: message rendering, scroll behavior, thinking indicator, tool tags, history management, streaming display | None | 115 |
| `test_rag_sim.py` | Basic RAG pipeline simulation: TF-IDF indexing, cosine similarity, context injection, ranking quality, edge cases | Optional* | 55 |
| `test_rag_modern.py` | **Modern RAG pipeline**: Hybrid TF-IDF + BM25 + RRF fusion + reranking + contextual chunking + hierarchical chunking + persistent memory | None | 82 |
| `test_rag_evaluation.py` | **RAG evaluation metrics**: Precision@K, Recall@K, MRR, NDCG, MAP comparing TF-IDF vs BM25 vs Hybrid vs Hybrid+Reranking across 18 queries with ground truth | None | 4 methods |
| `test_api_new.py` | API connectivity test for the AMD Radeon cloud endpoint | 1 | 1 |
| `test_api.py` | Basic API interaction test (original) | 1 | 1 |
| `test_all_providers.py` | Multi-provider API compatibility test | Multiple | Multiple |

*`test_rag_sim.py` automatically detects if the API is available and skips API-dependent tests if not.

## Running Tests

```bash
# Run all tests from the cpp directory
python testscripts\test_chatbox_sim.py
python testscripts\test_rag_sim.py
python testscripts\test_api_new.py

# Or run from this directory
cd testscripts
python test_chatbox_sim.py
python test_rag_sim.py
```

## Test Categories

### Chatbox Simulation (`test_chatbox_sim.py`)
- **Category 1**: Basic message rendering (25 tests)
- **Category 2**: Thinking indicator animation (15 tests)
- **Category 3**: Scroll behavior preservation (15 tests)
- **Category 4**: Tool tag stripping and detection (15 tests)
- **Category 5**: History management and overflow (15 tests)
- **Category 6**: API integration — simulated (10 tests)
- **Category 7**: Edge cases and stress tests (20 tests)

### RAG Simulation (`test_rag_sim.py`)
- **Category 1**: Document indexing and basic search (13 tests)
- **Category 2**: TF-IDF ranking quality (11 tests)
- **Category 3**: RAG context injection format (11 tests)
- **Category 4**: End-to-end API + RAG integration (10 tests, skipped if API unavailable)
- **Category 5**: Edge cases and stress tests (10 tests)

## Requirements

- Python 3.6+
- No external dependencies (uses only standard library)
- Internet access required only for API tests
