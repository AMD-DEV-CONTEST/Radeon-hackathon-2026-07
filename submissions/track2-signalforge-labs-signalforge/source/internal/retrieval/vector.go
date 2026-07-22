package retrieval

import (
	"errors"
	"math"
)

type VectorRecord struct {
	Chunk  Chunk     `json:"chunk"`
	Vector []float32 `json:"vector"`
}

type VectorIndex struct {
	records   []VectorRecord
	dimension int
}

func NewVectorIndex(records []VectorRecord) (*VectorIndex, error) {
	if len(records) == 0 || len(records[0].Vector) == 0 {
		return nil, errors.New("non-empty vector records are required")
	}
	index := &VectorIndex{records: make([]VectorRecord, len(records)), dimension: len(records[0].Vector)}
	for position, record := range records {
		if err := ValidateChunk(record.Chunk); err != nil {
			return nil, err
		}
		if len(record.Vector) != index.dimension || norm(record.Vector) == 0 {
			return nil, errors.New("vectors must share a non-zero dimension")
		}
		index.records[position] = VectorRecord{Chunk: record.Chunk, Vector: append([]float32(nil), record.Vector...)}
	}
	return index, nil
}

func (index *VectorIndex) Search(query Query, vector []float32) ([]Hit, error) {
	if err := ValidateQuery(query); err != nil {
		return nil, err
	}
	if len(vector) != index.dimension || norm(vector) == 0 {
		return nil, errors.New("query vector has invalid dimension or norm")
	}
	hits := make([]Hit, 0, len(index.records))
	for _, record := range index.records {
		if eligible(record.Chunk, query) {
			hits = append(hits, Hit{Chunk: record.Chunk, Score: cosine(vector, record.Vector), Method: "cosine/v1"})
		}
	}
	sortHits(hits)
	if len(hits) > query.TopK {
		hits = hits[:query.TopK]
	}
	for position := range hits {
		hits[position].Rank = position + 1
	}
	return hits, nil
}

func ReciprocalRankFusion(resultSets [][]Hit, topK int, constant float64) []Hit {
	weights := make([]float64, len(resultSets))
	for index := range weights {
		weights[index] = 1
	}
	return WeightedReciprocalRankFusion(resultSets, weights, topK, constant)
}

func WeightedReciprocalRankFusion(resultSets [][]Hit, weights []float64, topK int, constant float64) []Hit {
	if constant <= 0 {
		constant = 60
	}
	if len(weights) != len(resultSets) {
		return nil
	}
	type aggregate struct {
		chunk Chunk
		score float64
	}
	byID := make(map[string]aggregate)
	for setIndex, results := range resultSets {
		if weights[setIndex] <= 0 {
			continue
		}
		for position, hit := range results {
			value := byID[hit.Chunk.ChunkID]
			value.chunk = hit.Chunk
			value.score += weights[setIndex] / (constant + float64(position+1))
			byID[hit.Chunk.ChunkID] = value
		}
	}
	hits := make([]Hit, 0, len(byID))
	for _, value := range byID {
		hits = append(hits, Hit{Chunk: value.chunk, Score: value.score, Method: "rrf/v1"})
	}
	sortHits(hits)
	if topK > 0 && len(hits) > topK {
		hits = hits[:topK]
	}
	for position := range hits {
		hits[position].Rank = position + 1
	}
	return hits
}

func cosine(left, right []float32) float64 {
	dot, leftNorm, rightNorm := 0.0, 0.0, 0.0
	for index := range left {
		x, y := float64(left[index]), float64(right[index])
		dot += x * y
		leftNorm += x * x
		rightNorm += y * y
	}
	return dot / math.Sqrt(leftNorm*rightNorm)
}

func norm(vector []float32) float64 {
	total := 0.0
	for _, value := range vector {
		total += float64(value) * float64(value)
	}
	return math.Sqrt(total)
}
