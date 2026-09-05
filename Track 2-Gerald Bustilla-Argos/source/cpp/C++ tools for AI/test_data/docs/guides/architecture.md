# Architecture

## Components
1. **FileMapper**: Scans directories, collects metadata
2. **VectorStore**: TF-IDF vectorization, inverted index
3. **ImageHasher**: Perceptual hashing, format detection
4. **SearchEngine**: Combines all search modes
5. **JsonWriter**: Serializes results for AI consumption

## Data Flow
Directory -> FileMapper -> VectorStore + ImageHasher -> SearchEngine -> JSON
