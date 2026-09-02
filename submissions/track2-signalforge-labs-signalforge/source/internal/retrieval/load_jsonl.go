package retrieval

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

func LoadChunksJSONL(path string) ([]Chunk, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	chunks := make([]Chunk, 0)
	seen := make(map[string]struct{})
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var chunk Chunk
		if err := json.Unmarshal(scanner.Bytes(), &chunk); err != nil {
			return nil, fmt.Errorf("decode chunk line %d: %w", len(chunks)+1, err)
		}
		if err := ValidateChunk(chunk); err != nil {
			return nil, fmt.Errorf("validate chunk %q: %w", chunk.ChunkID, err)
		}
		if _, duplicate := seen[chunk.ChunkID]; duplicate {
			return nil, fmt.Errorf("duplicate chunk_id %q", chunk.ChunkID)
		}
		seen[chunk.ChunkID] = struct{}{}
		chunks = append(chunks, chunk)
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(chunks) == 0 {
		return nil, fmt.Errorf("chunk corpus is empty")
	}
	return chunks, nil
}
