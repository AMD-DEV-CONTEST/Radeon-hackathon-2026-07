package model

import (
	"encoding/json"
	"fmt"
	"os"
)

// Checkpoint holds every real, learnable parameter of an
// AMDHistoryModel, plus the real architecture dimensions needed to
// correctly reconstruct the model on load -- a genuinely simple,
// honest JSON format, appropriate for this narrow demo's scope.
type Checkpoint struct {
	VocabSize int `json:"vocab_size"`
	DModel    int `json:"d_model"`
	DFF       int `json:"d_ff"`
	MaxSeqLen int `json:"max_seq_len"`

	Embedding  []float64 `json:"embedding"`
	Wq         []float64 `json:"wq"`
	Wk         []float64 `json:"wk"`
	Wv         []float64 `json:"wv"`
	Wo         []float64 `json:"wo"`
	Gamma1     []float64 `json:"gamma1"`
	Beta1      []float64 `json:"beta1"`
	W1         []float64 `json:"w1"`
	B1         []float64 `json:"b1"`
	W2         []float64 `json:"w2"`
	B2         []float64 `json:"b2"`
	Gamma2     []float64 `json:"gamma2"`
	Beta2      []float64 `json:"beta2"`
	OutputProj []float64 `json:"output_proj"`
}

// SaveCheckpoint writes the real, current state of every learnable
// parameter to a real file on disk.
func SaveCheckpoint(m *AMDHistoryModel, path string) error {
	ckpt := Checkpoint{
		VocabSize:  m.VocabSize,
		DModel:     m.DModel,
		DFF:        m.DFF,
		MaxSeqLen:  m.MaxSeqLen,
		Embedding:  m.Embedding,
		Wq:         m.Wq,
		Wk:         m.Wk,
		Wv:         m.Wv,
		Wo:         m.Wo,
		Gamma1:     m.Gamma1,
		Beta1:      m.Beta1,
		W1:         m.W1,
		B1:         m.B1,
		W2:         m.W2,
		B2:         m.B2,
		Gamma2:     m.Gamma2,
		Beta2:      m.Beta2,
		OutputProj: m.OutputProj,
	}

	data, err := json.Marshal(ckpt)
	if err != nil {
		return fmt.Errorf("save checkpoint: marshaling: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("save checkpoint: writing %q: %w", path, err)
	}

	return nil
}

// LoadCheckpoint reads a real checkpoint file and reconstructs a
// complete, real AMDHistoryModel from it.
func LoadCheckpoint(path string) (*AMDHistoryModel, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("load checkpoint: reading %q: %w", path, err)
	}

	var ckpt Checkpoint
	if err := json.Unmarshal(data, &ckpt); err != nil {
		return nil, fmt.Errorf("load checkpoint: unmarshaling %q: %w", path, err)
	}

	return &AMDHistoryModel{
		VocabSize:  ckpt.VocabSize,
		DModel:     ckpt.DModel,
		DFF:        ckpt.DFF,
		MaxSeqLen:  ckpt.MaxSeqLen,
		Embedding:  ckpt.Embedding,
		Wq:         ckpt.Wq,
		Wk:         ckpt.Wk,
		Wv:         ckpt.Wv,
		Wo:         ckpt.Wo,
		Gamma1:     ckpt.Gamma1,
		Beta1:      ckpt.Beta1,
		W1:         ckpt.W1,
		B1:         ckpt.B1,
		W2:         ckpt.W2,
		B2:         ckpt.B2,
		Gamma2:     ckpt.Gamma2,
		Beta2:      ckpt.Beta2,
		OutputProj: ckpt.OutputProj,
	}, nil
}
