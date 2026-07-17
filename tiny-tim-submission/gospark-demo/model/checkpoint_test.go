package model

import (
	"os"
	"testing"
)

func TestCheckpointRoundTripsCorrectly(t *testing.T) {
	m := NewAMDHistoryModel(10, 8, 16, 10, 42)

	tmpFile, err := os.CreateTemp("", "checkpoint-*.json")
	if err != nil {
		t.Fatalf("creating temp file: %v", err)
	}
	path := tmpFile.Name()
	tmpFile.Close()
	defer os.Remove(path)

	if err := SaveCheckpoint(m, path); err != nil {
		t.Fatalf("SaveCheckpoint failed: %v", err)
	}

	loaded, err := LoadCheckpoint(path)
	if err != nil {
		t.Fatalf("LoadCheckpoint failed: %v", err)
	}

	if loaded.VocabSize != m.VocabSize || loaded.DModel != m.DModel || loaded.DFF != m.DFF || loaded.MaxSeqLen != m.MaxSeqLen {
		t.Fatalf("dimensions don't match: got %+v, want VocabSize=%d DModel=%d DFF=%d MaxSeqLen=%d",
			loaded, m.VocabSize, m.DModel, m.DFF, m.MaxSeqLen)
	}

	checkEqual := func(name string, got, want []float64) {
		if len(got) != len(want) {
			t.Errorf("%s: length mismatch, got %d, want %d", name, len(got), len(want))
			return
		}
		for i := range want {
			if got[i] != want[i] {
				t.Errorf("%s[%d]: expected %v, got %v", name, i, want[i], got[i])
			}
		}
	}

	checkEqual("Embedding", loaded.Embedding, m.Embedding)
	checkEqual("Wq", loaded.Wq, m.Wq)
	checkEqual("OutputProj", loaded.OutputProj, m.OutputProj)

	t.Logf("Checkpoint round-tripped correctly: %d embedding params, %d Wq params", len(loaded.Embedding), len(loaded.Wq))
}
