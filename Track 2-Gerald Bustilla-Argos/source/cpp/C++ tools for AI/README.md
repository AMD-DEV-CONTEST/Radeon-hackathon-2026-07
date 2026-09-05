# AI Search Tool

A C++ tool that maps files and folders, indexes text content with TF-IDF vectorization (RAG-style retrieval), and fingerprints images with base64 hashes and perceptual hashing. Designed for AI agents to easily search and retrieve file contents.

## Features

- **File/Folder Mapping**: Recursively scans directories, classifies files by type (text, image, binary), and collects metadata (size, modified time, content hash).
- **Text Content Search (RAG-style)**:
  - Text files are chunked into overlapping segments
  - Each chunk is vectorized using TF-IDF (Term Frequency - Inverse Document Frequency)
  - An inverted index enables fast retrieval
  - Cosine similarity ranks results by relevance
- **Image Search**:
  - Each image gets a **base64 hash** (exact identification - if two images have the same content, they share the same base64 hash)
  - Each image gets a **perceptual hash** (64-bit hash for finding similar images even if not identical)
  - Hamming distance measures similarity between perceptual hashes
- **JSON Output**: All output is structured JSON, ready for AI consumption.

## Building

### Requirements
- C++17 compatible compiler (MSVC 2019+, GCC 9+, or Clang 10+)
- CMake 3.14+

### Build Instructions

```bash
mkdir build
cd build
cmake ..
cmake --build . --config Release
```

On Windows with MSVC:
```powershell
mkdir build
cd build
cmake .. -G "Visual Studio 17 2022"
cmake --build . --config Release
```

The executable `aisearch` (or `aisearch.exe`) will be in the build directory.

## Usage

### Map a directory (file listing only)
```bash
aisearch map ./my-project
```

### Index a directory (full content indexing)
```bash
aisearch index ./my-project --hidden
```

### Search text content
```bash
aisearch search ./my-project --query "error handling authentication"
```

### Search for an image by base64 hash (exact match)
```bash
aisearch search-image ./images --hash "iVBORw0KGgo="
```

### Find similar images
```bash
aisearch search-similar ./images --image ./test.png --max-distance 15
```

### Combined search (text + images)
```bash
aisearch search-all ./my-project --query "database schema" --top-k 20
```

### Full index map (complete JSON for AI consumption)
```bash
aisearch full-map ./my-project > index.json
```

### Fingerprint a single image
```bash
aisearch fingerprint ./photo.jpg
```

### View statistics
```bash
aisearch stats ./my-project
```

## How It Works

### Text Indexing (RAG-style)
1. **Chunking**: Text files are split into overlapping chunks (~512 chars, 64 char overlap) at word boundaries.
2. **Tokenization**: Each chunk is tokenized into lowercase words, with stop words removed.
3. **TF-IDF Vectorization**: Each chunk gets a sparse vector where each dimension is a term weighted by TF-IDF.
4. **Inverted Index**: Maps each term to the chunks containing it, enabling fast lookup.
5. **Retrieval**: Query text is vectorized the same way, and cosine similarity ranks chunks.

### Image Fingerprinting
1. **Content Hash (FNV-1a)**: A 64-bit hash of the raw file bytes for exact identification.
2. **Base64 Hash**: The first 48 bytes of the file encoded as base64. This serves as a unique fingerprint - images with identical content will have identical base64 hashes.
3. **Perceptual Hash**: A 64-bit hash computed by sampling bytes at regular intervals and comparing to the average. Similar images produce similar hashes (small Hamming distance).
4. **Format Detection**: Detects PNG, JPEG, BMP, GIF, WebP, TIFF, ICO, HEIC from magic bytes.
5. **Dimension Extraction**: Reads image width/height from headers when possible.

## JSON Output Format

All commands output JSON to stdout. Example `full-map` output:

```json
{
  "version": "1.0.0",
  "type": "full_index_map",
  "root_path": "./my-project",
  "statistics": {
    "total_files": 150,
    "total_text_files": 80,
    "total_image_files": 20,
    "total_chunks": 350,
    "total_images_indexed": 20,
    "vocabulary_size": 5000
  },
  "files": [...],
  "text_chunks": [
    {
      "id": 0,
      "file_path": "./my-project/src/main.cpp",
      "text": "...",
      "chunk_index": 0,
      "start_pos": 0,
      "end_pos": 512
    }
  ],
  "images": [
    {
      "file_path": "./my-project/logo.png",
      "fingerprint": {
        "base64_hash": "iVBORw0KGgo...",
        "hex_hash": "a1b2c3d4e5f6a7b8",
        "perceptual_hash": "f1e2d3c4b5a69788",
        "file_format": "PNG",
        "width": 256,
        "height": 256
      }
    }
  ]
}
```

## Architecture

```
src/
├── main.cpp              - CLI interface and command dispatch
├── text_utils.h/cpp      - Tokenization, base64, chunking, file type detection
├── image_hasher.h/cpp    - Image fingerprinting (content hash, base64, perceptual hash)
├── file_mapper.h/cpp     - Recursive directory scanning and file metadata
├── vector_store.h/cpp    - TF-IDF vectorization, inverted index, cosine similarity
├── content_indexer.h/cpp - Orchestrates indexing of text + images
├── search_engine.h/cpp   - Query interface for text/image/combined search
└── json_writer.h/cpp     - JSON serialization for all output types
```

## Supported File Types

**Text**: .txt, .md, .c, .cpp, .h, .py, .js, .ts, .java, .go, .rs, .json, .yaml, .xml, .html, .css, .csv, .sql, .sh, .bat, and 40+ more.

**Images**: .png, .jpg, .jpeg, .bmp, .gif, .webp, .tiff, .ico, .heic, and more.

**Binary**: All other files are cataloged with metadata but not content-indexed.
