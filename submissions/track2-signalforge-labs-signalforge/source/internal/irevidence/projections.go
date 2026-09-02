package irevidence

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

const SemanticProjectionSchemaV1 = "signalforge/ir-semantic-projection/v1"

type SemanticProjection struct {
	SchemaVersion       string   `json:"schema_version"`
	ProjectionID        string   `json:"projection_id"`
	ChunkID             string   `json:"chunk_id"`
	DocumentID          string   `json:"document_id"`
	CompanyID           string   `json:"company_id"`
	Text                string   `json:"text"`
	SourceContentSHA256 string   `json:"source_content_sha256"`
	ProjectionSHA256    string   `json:"projection_sha256"`
	ProjectionVersion   string   `json:"projection_version"`
	NumericSpanCount    int      `json:"numeric_span_count"`
	NumericReferences   []string `json:"numeric_references"`
}

func LoadSemanticProjectionsJSONL(path string) (map[string]SemanticProjection, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	projections := make(map[string]SemanticProjection)
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		var projection SemanticProjection
		if err := json.Unmarshal(scanner.Bytes(), &projection); err != nil {
			return nil, err
		}
		if projection.SchemaVersion != SemanticProjectionSchemaV1 || projection.ProjectionID == "" || projection.ChunkID == "" || projection.Text == "" || projection.NumericSpanCount < 0 {
			return nil, fmt.Errorf("invalid projection %q", projection.ProjectionID)
		}
		if _, duplicate := projections[projection.ChunkID]; duplicate {
			return nil, fmt.Errorf("duplicate projection for chunk %q", projection.ChunkID)
		}
		digest := sha256.Sum256([]byte(projection.Text))
		if hex.EncodeToString(digest[:]) != projection.ProjectionSHA256 {
			return nil, fmt.Errorf("projection hash mismatch for chunk %q", projection.ChunkID)
		}
		projections[projection.ChunkID] = projection
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(projections) == 0 {
		return nil, fmt.Errorf("projection corpus is empty")
	}
	return projections, nil
}
