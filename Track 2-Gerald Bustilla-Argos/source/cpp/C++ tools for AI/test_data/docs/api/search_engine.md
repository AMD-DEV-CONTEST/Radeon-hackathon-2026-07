# Search Engine API

## Overview
The search engine provides TF-IDF vectorized text search with cosine similarity ranking.

## Features
- Text chunking with overlapping windows
- TF-IDF vectorization
- Inverted index for fast retrieval
- Cosine similarity scoring
- Image fingerprinting with base64 and perceptual hashes

## Usage
```cpp
VectorStore store;
store.add_chunk("some text content");
store.finalize();
auto results = store.search("query text", 10);
```
