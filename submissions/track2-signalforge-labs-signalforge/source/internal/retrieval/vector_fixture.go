package retrieval

import (
	"encoding/json"
	"errors"
	"os"
	"regexp"
)

const VectorFixtureSchemaV1 = "signalforge/retrieval-vectors/v1"

var modelRevisionPattern = regexp.MustCompile(`^[a-f0-9]{40,64}$`)

type NamedVector struct {
	ID     string    `json:"id"`
	Vector []float32 `json:"vector"`
}

type VectorFixture struct {
	SchemaVersion string        `json:"schema_version"`
	ModelID       string        `json:"model_id"`
	Revision      string        `json:"revision"`
	Dimension     int           `json:"dimension"`
	DatasetSHA256 string        `json:"dataset_sha256"`
	Chunks        []NamedVector `json:"chunks"`
	Questions     []NamedVector `json:"questions"`
}

func LoadVectorFixture(path string, chunks []Chunk, eval EvalSet) (VectorFixture, error) {
	payload, err := os.ReadFile(path)
	if err != nil {
		return VectorFixture{}, err
	}
	var fixture VectorFixture
	if err := json.Unmarshal(payload, &fixture); err != nil {
		return VectorFixture{}, err
	}
	if fixture.SchemaVersion != VectorFixtureSchemaV1 || fixture.ModelID == "" || !modelRevisionPattern.MatchString(fixture.Revision) || fixture.Dimension <= 0 || !validSHA(fixture.DatasetSHA256) {
		return VectorFixture{}, errors.New("invalid vector fixture identity")
	}
	wantChunks := make(map[string]bool, len(chunks))
	for _, chunk := range chunks {
		wantChunks[chunk.ChunkID] = true
	}
	wantQuestions := make(map[string]bool, len(eval.Questions))
	for _, question := range eval.Questions {
		wantQuestions[question.QuestionID] = true
	}
	if err := validateNamedVectors(fixture.Chunks, wantChunks, fixture.Dimension); err != nil {
		return VectorFixture{}, err
	}
	if err := validateNamedVectors(fixture.Questions, wantQuestions, fixture.Dimension); err != nil {
		return VectorFixture{}, err
	}
	return fixture, nil
}

func validateNamedVectors(vectors []NamedVector, wanted map[string]bool, dimension int) error {
	seen := make(map[string]bool, len(vectors))
	for _, vector := range vectors {
		if !wanted[vector.ID] || seen[vector.ID] || len(vector.Vector) != dimension || norm(vector.Vector) == 0 {
			return errors.New("vector fixture population, dimension, or norm is invalid")
		}
		seen[vector.ID] = true
	}
	if len(seen) != len(wanted) {
		return errors.New("vector fixture population is incomplete")
	}
	return nil
}
