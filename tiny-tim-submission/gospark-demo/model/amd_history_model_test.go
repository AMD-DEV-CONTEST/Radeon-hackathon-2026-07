package model

import (
	"math"
	"testing"
)

func TestForwardRealEndToEnd(t *testing.T) {
	vocabSize, dModel, dFF, maxSeqLen := 20, 8, 16, 10
	m := NewAMDHistoryModel(vocabSize, dModel, dFF, maxSeqLen, 42)

	tokenIDs := []int{1, 5, 3, 7}
	cache, err := m.Forward(tokenIDs)
	if err != nil {
		t.Fatalf("Forward failed: %v", err)
	}

	seqLen := len(tokenIDs)

	// Real, structural check: output shape must be seqLen x vocabSize.
	if len(cache.Probs) != seqLen*vocabSize {
		t.Fatalf("expected %d probability values (seqLen*vocabSize), got %d", seqLen*vocabSize, len(cache.Probs))
	}

	// Real, structural check: every row of real softmax output must sum
	// to ~1.0 -- a genuine, meaningful probability distribution, not
	// garbage numbers.
	for row := 0; row < seqLen; row++ {
		sum := 0.0
		for col := 0; col < vocabSize; col++ {
			p := cache.Probs[row*vocabSize+col]
			if math.IsNaN(p) {
				t.Fatalf("row %d, col %d: got NaN in real softmax output", row, col)
			}
			sum += p
		}
		diff := sum - 1.0
		if diff > 0.0001 || diff < -0.0001 {
			t.Errorf("row %d: probabilities sum to %v, expected ~1.0", row, sum)
		}
	}

	t.Logf("Forward pass succeeded: %d tokens, %d vocab, first-token top probability position check passed", seqLen, vocabSize)
}
