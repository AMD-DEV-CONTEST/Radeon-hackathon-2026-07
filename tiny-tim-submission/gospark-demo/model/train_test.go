package model

import "testing"

func TestTrainStepLossDecreasesRealEndToEnd(t *testing.T) {
	// THE REAL PROOF: does the entire, complete, hand-derived backward
	// chain -- composed together for the first time -- actually
	// produce genuine learning behavior on real GPU compute? Every
	// individual piece was already hand-verified in isolation; this is
	// the real test that the whole chain, wired together, works.

	vocabSize, dModel, dFF, maxSeqLen := 10, 8, 16, 10
	m := NewAMDHistoryModel(vocabSize, dModel, dFF, maxSeqLen, 42)
	opt := NewSimpleOptimizer(0.01)

	// A simple, fixed, real pattern to learn: given [1,2,3], predict [2,3,4].
	tokenIDs := []int{1, 2, 3}
	targets := []int{2, 3, 4}

	var firstLoss, lastLoss float64
	numSteps := 50

	for step := 0; step < numSteps; step++ {
		loss, err := TrainStep(m, opt, tokenIDs, targets)
		if err != nil {
			t.Fatalf("TrainStep failed at step %d: %v", step, err)
		}
		if step == 0 {
			firstLoss = loss
		}
		if step == numSteps-1 {
			lastLoss = loss
		}
		if step%10 == 0 {
			t.Logf("step %d: loss = %.6f", step, loss)
		}
	}

	t.Logf("Real end-to-end training: first loss = %.6f, last loss = %.6f", firstLoss, lastLoss)

	if lastLoss >= firstLoss {
		t.Fatalf("expected real loss to decrease over %d real training steps, went from %v to %v", numSteps, firstLoss, lastLoss)
	}
}
