package model

import (
	"math"
	"testing"
)

func TestBackwardOutputLayerHandVerified(t *testing.T) {
	// Hand-verified: seqLen=1, vocabSize=3, dModel=2.
	// probs = [0.2, 0.3, 0.5], target = [2] (correct answer is index 2).
	// dLogits = probs - one_hot(2) = [0.2, 0.3, -0.5], /seqLen(1) unchanged.
	//
	// norm2Out = [1, 2] (1x2).
	// dOutputProj = norm2Out^T @ dLogits = [[1],[2]] @ [[0.2,0.3,-0.5]]
	//             = [0.2, 0.3, -0.5, 0.4, 0.6, -1.0] (2x3, row-major).
	//
	// OutputProj = [1,0,0, 0,1,0] (2x3): dim0->vocab0, dim1->vocab1.
	// dNorm2Out = dLogits @ OutputProj^T = [0.2,0.3,-0.5] @ [[1,0],[0,1],[0,0]]
	//           = [0.2, 0.3] (1x2).

	m := &AMDHistoryModel{
		VocabSize:  3,
		DModel:     2,
		OutputProj: []float64{1, 0, 0, 0, 1, 0},
	}
	cache := &ForwardCache{
		SeqLen:   1,
		Norm2Out: []float64{1, 2},
		Probs:    []float64{0.2, 0.3, 0.5},
	}
	targets := []int{2}

	dOutputProj, dNorm2Out, err := BackwardOutputLayer(cache, m, targets)
	if err != nil {
		t.Fatalf("BackwardOutputLayer failed: %v", err)
	}

	wantDOutputProj := []float64{0.2, 0.3, -0.5, 0.4, 0.6, -1.0}
	for i := range wantDOutputProj {
		diff := dOutputProj[i] - wantDOutputProj[i]
		if diff > 0.0001 || diff < -0.0001 {
			t.Errorf("dOutputProj[%d]: expected %v, got %v", i, wantDOutputProj[i], dOutputProj[i])
		}
	}

	wantDNorm2Out := []float64{0.2, 0.3}
	for i := range wantDNorm2Out {
		diff := dNorm2Out[i] - wantDNorm2Out[i]
		if diff > 0.0001 || diff < -0.0001 {
			t.Errorf("dNorm2Out[%d]: expected %v, got %v", i, wantDNorm2Out[i], dNorm2Out[i])
		}
	}

	t.Logf("dOutputProj: %v", dOutputProj)
	t.Logf("dNorm2Out: %v", dNorm2Out)
}

func TestCrossEntropyLossHandVerified(t *testing.T) {
	// probs = [0.2, 0.3, 0.5], target = 2 -> loss = -ln(0.5) ≈ 0.6931
	probs := []float64{0.2, 0.3, 0.5}
	targets := []int{2}

	loss, err := CrossEntropyLoss(probs, targets, 1, 3)
	if err != nil {
		t.Fatalf("CrossEntropyLoss failed: %v", err)
	}

	want := 0.693147
	diff := loss - want
	if diff > 0.0001 || diff < -0.0001 {
		t.Errorf("expected loss ~= %v, got %v", want, loss)
	}
	t.Logf("Real cross entropy loss: %v", loss)
}

func TestBackwardLayerNormHandVerified(t *testing.T) {
	// Hand-verified: rows=1, cols=3.
	// xhat = [1, 0, -1], gamma = [1, 1, 1], dy = [1, 0, 0], stdInv = [1.0].
	//
	// dxhat = dy*gamma = [1, 0, 0]
	// sum(dxhat) = 1, sum(dxhat*xhat) = 1*1 + 0*0 + 0*(-1) = 1
	// N = 3
	// dx[0] = (1/3)*(3*1 - 1 - 1*1) = (1/3)*1 = 0.3333...
	// dx[1] = (1/3)*(3*0 - 1 - 0*1) = (1/3)*(-1) = -0.3333...
	// dx[2] = (1/3)*(3*0 - 1 - (-1)*1) = (1/3)*0 = 0
	//
	// dgamma = dy*xhat = [1*1, 0*0, 0*(-1)] = [1, 0, 0]
	// dbeta = dy = [1, 0, 0]

	xhat := []float64{1, 0, -1}
	gamma := []float64{1, 1, 1}
	dy := []float64{1, 0, 0}
	stdInv := []float64{1.0}

	dx, dgamma, dbeta := BackwardLayerNorm(dy, xhat, gamma, stdInv, 1, 3)

	wantDx := []float64{1.0 / 3.0, -1.0 / 3.0, 0}
	for i := range wantDx {
		diff := dx[i] - wantDx[i]
		if diff > 0.0001 || diff < -0.0001 {
			t.Errorf("dx[%d]: expected %v, got %v", i, wantDx[i], dx[i])
		}
	}

	wantDgamma := []float64{1, 0, 0}
	for i := range wantDgamma {
		if dgamma[i] != wantDgamma[i] {
			t.Errorf("dgamma[%d]: expected %v, got %v", i, wantDgamma[i], dgamma[i])
		}
	}

	wantDbeta := []float64{1, 0, 0}
	for i := range wantDbeta {
		if dbeta[i] != wantDbeta[i] {
			t.Errorf("dbeta[%d]: expected %v, got %v", i, wantDbeta[i], dbeta[i])
		}
	}

	t.Logf("dx: %v, dgamma: %v, dbeta: %v", dx, dgamma, dbeta)
}

func TestBackwardFFNHandVerified(t *testing.T) {
	// Hand-verified: seqLen=1, dModel=2, dFF=2, identity weights to
	// keep the calculation clean.
	// Norm1Out = [1, 0], W1 = W2 = identity, B1 = B2 = [0, 0].
	// FF1Pre = [1, 0] -> FF1Out (ReLU) = [1, 0] -> FF2Out = [1, 0].
	// dResid2 = [1, 1] (real incoming gradient).
	//
	// Residual split: dNorm1OutFromResidual = [1,1], dFF2Out = [1,1].
	// dW2 = FF1Out^T @ dFF2Out = [1,1,0,0], dB2 = [1,1].
	// dFF1Out = dFF2Out @ W2^T = [1,1] (identity).
	// ReLU backward: FF1Pre=[1,0] -> dFF1Pre = [1,0] (blocked at index 1).
	// dW1 = Norm1Out^T @ dFF1Pre = [1,0,0,0], dB1 = [1,0].
	// dNorm1OutFromFFN = dFF1Pre @ W1^T = [1,0].
	// Total dNorm1Out = [1,1] + [1,0] = [2,1].

	m := &AMDHistoryModel{
		DModel: 2,
		DFF:    2,
		W1:     []float64{1, 0, 0, 1},
		W2:     []float64{1, 0, 0, 1},
	}
	cache := &ForwardCache{
		SeqLen:   1,
		Norm1Out: []float64{1, 0},
		FF1Pre:   []float64{1, 0},
		FF1Out:   []float64{1, 0},
	}
	dResid2 := []float64{1, 1}

	dW1, dB1, dW2, dB2, dNorm1Out, err := BackwardFFN(cache, m, dResid2)
	if err != nil {
		t.Fatalf("BackwardFFN failed: %v", err)
	}

	checkClose := func(name string, got, want []float64) {
		for i := range want {
			diff := got[i] - want[i]
			if diff > 0.0001 || diff < -0.0001 {
				t.Errorf("%s[%d]: expected %v, got %v", name, i, want[i], got[i])
			}
		}
	}

	checkClose("dW1", dW1, []float64{1, 0, 0, 0})
	checkClose("dB1", dB1, []float64{1, 0})
	checkClose("dW2", dW2, []float64{1, 1, 0, 0})
	checkClose("dB2", dB2, []float64{1, 1})
	checkClose("dNorm1Out", dNorm1Out, []float64{2, 1})

	t.Logf("dW1: %v, dB1: %v, dW2: %v, dB2: %v, dNorm1Out: %v", dW1, dB1, dW2, dB2, dNorm1Out)
}

func TestBackwardResid1AndNorm1HandVerified(t *testing.T) {
	// Reuses the exact same hand-verified numbers as
	// TestBackwardLayerNormHandVerified, since this genuinely delegates
	// to the same real formula -- known expected output:
	// dx = [1/3, -1/3, 0], dgamma = [1,0,0], dbeta = [1,0,0].
	//
	// Real, additional check: the residual split should send that
	// SAME dResid1 value into BOTH dEmbeddedFromResid1 and dAttnProj
	// unchanged, matching addition's own standard backward rule.

	m := &AMDHistoryModel{
		DModel: 3,
		Gamma1: []float64{1, 1, 1},
	}
	cache := &ForwardCache{
		SeqLen:      1,
		Norm1Xhat:   []float64{1, 0, -1},
		Norm1StdInv: []float64{1.0},
	}
	dNorm1Out := []float64{1, 0, 0}

	dEmbedded, dAttnProj, dGamma1, dBeta1 := BackwardResid1AndNorm1(cache, m, dNorm1Out)

	wantDx := []float64{1.0 / 3.0, -1.0 / 3.0, 0}
	checkClose := func(name string, got, want []float64) {
		for i := range want {
			diff := got[i] - want[i]
			if diff > 0.0001 || diff < -0.0001 {
				t.Errorf("%s[%d]: expected %v, got %v", name, i, want[i], got[i])
			}
		}
	}

	checkClose("dEmbeddedFromResid1", dEmbedded, wantDx)
	checkClose("dAttnProj", dAttnProj, wantDx)
	checkClose("dGamma1", dGamma1, []float64{1, 0, 0})
	checkClose("dBeta1", dBeta1, []float64{1, 0, 0})

	// Real, structural check: both residual branches should genuinely
	// be identical, not just individually correct.
	for i := range dEmbedded {
		if dEmbedded[i] != dAttnProj[i] {
			t.Errorf("expected residual split to send the identical gradient to both branches, got dEmbedded[%d]=%v, dAttnProj[%d]=%v", i, dEmbedded[i], i, dAttnProj[i])
		}
	}

	t.Logf("dEmbedded: %v, dAttnProj: %v, dGamma1: %v, dBeta1: %v", dEmbedded, dAttnProj, dGamma1, dBeta1)
}

func TestBackwardAttnOutputAndWeightedSumHandVerified(t *testing.T) {
	// Hand-verified: seqLen=2, dModel=2.
	// AttnOut = [[1,0],[0,1]] (identity rows), Wo = identity.
	// dAttnProj = [[1,0],[0,1]] (identity).
	//
	// dWo = AttnOut^T @ dAttnProj = identity @ identity = identity.
	// dAttnOut = dAttnProj @ Wo^T = identity @ identity = identity.
	//
	// AttnWeights = [[0.5,0.5],[0.5,0.5]] (uniform), V = identity.
	// dV = AttnWeights^T @ dAttnOut = [[0.5,0.5],[0.5,0.5]] @ identity
	//    = [[0.5,0.5],[0.5,0.5]].
	// dAttnWeights = dAttnOut @ V^T = identity @ identity = identity.

	m := &AMDHistoryModel{DModel: 2, Wo: []float64{1, 0, 0, 1}}
	cache := &ForwardCache{
		SeqLen:      2,
		AttnOut:     []float64{1, 0, 0, 1},
		AttnWeights: []float64{0.5, 0.5, 0.5, 0.5},
		V:           []float64{1, 0, 0, 1},
	}
	dAttnProj := []float64{1, 0, 0, 1}

	dWo, dAttnWeights, dV, err := BackwardAttnOutputAndWeightedSum(cache, m, dAttnProj)
	if err != nil {
		t.Fatalf("BackwardAttnOutputAndWeightedSum failed: %v", err)
	}

	checkClose := func(name string, got, want []float64) {
		for i := range want {
			diff := got[i] - want[i]
			if diff > 0.0001 || diff < -0.0001 {
				t.Errorf("%s[%d]: expected %v, got %v", name, i, want[i], got[i])
			}
		}
	}

	checkClose("dWo", dWo, []float64{1, 0, 0, 1})
	checkClose("dAttnWeights", dAttnWeights, []float64{1, 0, 0, 1})
	checkClose("dV", dV, []float64{0.5, 0.5, 0.5, 0.5})

	t.Logf("dWo: %v, dAttnWeights: %v, dV: %v", dWo, dAttnWeights, dV)
}

func TestSoftmaxBackwardHandVerified(t *testing.T) {
	// Hand-verified: y = [0.5, 0.5] (a real, valid softmax row), dy = [1, 0].
	// sum = 1*0.5 + 0*0.5 = 0.5
	// dx[0] = 0.5*(1-0.5) = 0.25
	// dx[1] = 0.5*(0-0.5) = -0.25
	y := []float64{0.5, 0.5}
	dy := []float64{1, 0}

	dx := softmaxBackward(dy, y, 1, 2)

	want := []float64{0.25, -0.25}
	for i := range want {
		diff := dx[i] - want[i]
		if diff > 0.0001 || diff < -0.0001 {
			t.Errorf("dx[%d]: expected %v, got %v", i, want[i], dx[i])
		}
	}
	t.Logf("softmaxBackward result: %v", dx)
}

func TestBackwardAttnScoresAndQKHandVerified(t *testing.T) {
	// Hand-verified: seqLen=2, dModel=2, Q=K=identity, uniform attention
	// weights (both rows = [0.5,0.5]), dAttnWeights uses [1,0] per row
	// (matching the same pattern already hand-verified in
	// TestSoftmaxBackwardHandVerified, applied to both rows).
	//
	// softmaxBackward gives dAttnScores = [0.25,-0.25,0.25,-0.25]
	// (both rows identical, same calculation as the standalone test).
	//
	// scale = 1/sqrt(2). dQK = dAttnScores * scale.
	// With Q=K=identity, dQ = dQK @ K = dQK (unchanged),
	// dK = dQK^T @ Q = dQK^T (unchanged).

	dModel := 2
	scale := 1.0 / math.Sqrt(float64(dModel))

	m := &AMDHistoryModel{DModel: dModel}
	cache := &ForwardCache{
		SeqLen:      2,
		AttnWeights: []float64{0.5, 0.5, 0.5, 0.5},
		Q:           []float64{1, 0, 0, 1},
		K:           []float64{1, 0, 0, 1},
	}
	dAttnWeights := []float64{1, 0, 1, 0}

	dQ, dK, err := BackwardAttnScoresAndQK(cache, m, dAttnWeights)
	if err != nil {
		t.Fatalf("BackwardAttnScoresAndQK failed: %v", err)
	}

	dAttnScores := []float64{0.25, -0.25, 0.25, -0.25}
	dQK := make([]float64, 4)
	for i, v := range dAttnScores {
		dQK[i] = v * scale
	}
	// dQK^T for a 2x2 matrix [[a,b],[c,d]] is [[a,c],[b,d]].
	dQKT := []float64{dQK[0], dQK[2], dQK[1], dQK[3]}

	checkClose := func(name string, got, want []float64) {
		for i := range want {
			diff := got[i] - want[i]
			if diff > 0.0001 || diff < -0.0001 {
				t.Errorf("%s[%d]: expected %v, got %v", name, i, want[i], got[i])
			}
		}
	}

	checkClose("dQ", dQ, dQK)
	checkClose("dK", dK, dQKT)

	t.Logf("dQ: %v, dK: %v (scale=%v)", dQ, dK, scale)
}

func TestBackwardQKVProjectionsHandVerified(t *testing.T) {
	m := &AMDHistoryModel{
		DModel: 2,
		Wq:     []float64{1, 0, 0, 1},
		Wk:     []float64{1, 0, 0, 1},
		Wv:     []float64{1, 0, 0, 1},
	}
	cache := &ForwardCache{SeqLen: 1, EmbeddedInput: []float64{1, 2}}
	dQ := []float64{1, 1}
	dK := []float64{1, 1}
	dV := []float64{1, 1}

	dWq, dWk, dWv, dEmbeddedFromQKV, err := BackwardQKVProjections(cache, m, dQ, dK, dV)
	if err != nil {
		t.Fatalf("BackwardQKVProjections failed: %v", err)
	}

	checkClose := func(name string, got, want []float64) {
		for i := range want {
			diff := got[i] - want[i]
			if diff > 0.0001 || diff < -0.0001 {
				t.Errorf("%s[%d]: expected %v, got %v", name, i, want[i], got[i])
			}
		}
	}

	want := []float64{1, 1, 2, 2}
	checkClose("dWq", dWq, want)
	checkClose("dWk", dWk, want)
	checkClose("dWv", dWv, want)
	checkClose("dEmbeddedFromQKV", dEmbeddedFromQKV, []float64{3, 3})

	t.Logf("dWq: %v, dWk: %v, dWv: %v, dEmbeddedFromQKV: %v", dWq, dWk, dWv, dEmbeddedFromQKV)
}

func TestBackwardEmbeddingAccumulatesRepeatedTokens(t *testing.T) {
	m := &AMDHistoryModel{VocabSize: 3, DModel: 2}
	tokenIDs := []int{0, 1, 0}
	dEmbeddedInput := []float64{1, 1, 2, 2, 3, 3}

	dEmbedding := BackwardEmbedding(m, tokenIDs, dEmbeddedInput)

	want := []float64{4, 4, 2, 2, 0, 0}
	for i := range want {
		if dEmbedding[i] != want[i] {
			t.Errorf("dEmbedding[%d]: expected %v, got %v", i, want[i], dEmbedding[i])
		}
	}

	t.Logf("dEmbedding: %v", dEmbedding)
}
