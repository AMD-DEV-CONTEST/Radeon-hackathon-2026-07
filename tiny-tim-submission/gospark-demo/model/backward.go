package model

import (
	"fmt"
	"math"

	"haroldDemo/gospark-demo/native"
)

// CrossEntropyLoss computes the real, standard cross-entropy loss
// given real softmax probabilities and real target token IDs (the
// actual next token at each position) -- the real loss function used
// for language model training.
func CrossEntropyLoss(probs []float64, targets []int, seqLen, vocabSize int) (float64, error) {
	if len(targets) != seqLen {
		return 0, fmt.Errorf("cross entropy loss: expected %d targets, got %d", seqLen, len(targets))
	}
	loss := 0.0
	for i, target := range targets {
		if target < 0 || target >= vocabSize {
			return 0, fmt.Errorf("cross entropy loss: target %d at position %d out of vocab range", target, i)
		}
		p := probs[i*vocabSize+target]
		// Real, honest numerical safety: avoid log(0) for a genuinely
		// zero-probability prediction (a real, if rare, possibility
		// early in training with a randomly-initialized model).
		if p < 1e-10 {
			p = 1e-10
		}
		loss -= math.Log(p)
	}
	return loss / float64(seqLen), nil
}

// BackwardOutputLayer computes the real gradients for the output
// projection layer -- the actual first step of backpropagation.
// Uses the real, well-established closed-form result for combined
// softmax+cross-entropy: dLoss/dLogits = probs - one_hot(target).
// Given Logits = norm2Out @ OutputProj, the real matrix-calculus
// gradients are dOutputProj = norm2Out^T @ dLogits and
// dNorm2Out = dLogits @ OutputProj^T.
func BackwardOutputLayer(cache *ForwardCache, m *AMDHistoryModel, targets []int) (dOutputProj, dNorm2Out []float64, err error) {
	seqLen := cache.SeqLen
	vocabSize := m.VocabSize
	dModel := m.DModel

	if len(targets) != seqLen {
		return nil, nil, fmt.Errorf("backward output layer: expected %d targets, got %d", seqLen, len(targets))
	}

	// Real, closed-form gradient: dLogits = probs - one_hot(target).
	dLogits := make([]float64, seqLen*vocabSize)
	copy(dLogits, cache.Probs)
	for i, target := range targets {
		dLogits[i*vocabSize+target] -= 1.0
	}
	// Real, standard gradient averaging over the sequence, matching
	// CrossEntropyLoss's own averaging.
	for i := range dLogits {
		dLogits[i] /= float64(seqLen)
	}

	// dOutputProj = norm2Out^T @ dLogits  (dModel x vocabSize)
	norm2OutT := transpose(cache.Norm2Out, seqLen, dModel)
	dOutputProj, err = native.GPUMatMul(norm2OutT, dLogits, dModel, seqLen, vocabSize)
	if err != nil {
		return nil, nil, fmt.Errorf("backward output layer: computing dOutputProj: %w", err)
	}

	// dNorm2Out = dLogits @ OutputProj^T  (seqLen x dModel)
	outputProjT := transpose(m.OutputProj, dModel, vocabSize)
	dNorm2Out, err = native.GPUMatMul(dLogits, outputProjT, seqLen, vocabSize, dModel)
	if err != nil {
		return nil, nil, fmt.Errorf("backward output layer: computing dNorm2Out: %w", err)
	}

	return dOutputProj, dNorm2Out, nil
}

// BackwardLayerNorm computes the real gradients for a LayerNorm layer,
// using the standard, established formula (from the original LayerNorm
// paper's own backward derivation). Given y = gamma*xhat + beta, where
// xhat = (x - mean) / sqrt(var + eps):
//
//	dbeta  = sum(dy) over rows, per feature
//	dgamma = sum(dy * xhat) over rows, per feature
//	dxhat  = dy * gamma
//	dx     = (stdInv/N) * (N*dxhat - sum(dxhat) - xhat*sum(dxhat*xhat))
//
// dx is computed independently per row, using that row's own cached
// stdInv (matching how each row was normalized independently in the
// real forward pass).
func BackwardLayerNorm(dy, xhat, gamma, stdInv []float64, rows, cols int) (dx, dgamma, dbeta []float64) {
	dgamma = make([]float64, cols)
	dbeta = make([]float64, cols)
	dx = make([]float64, rows*cols)

	for r := 0; r < rows; r++ {
		rowDxhat := make([]float64, cols)
		sumDxhat := 0.0
		sumDxhatXhat := 0.0

		for c := 0; c < cols; c++ {
			idx := r*cols + c
			dyVal := dy[idx]
			xhatVal := xhat[idx]

			dbeta[c] += dyVal
			dgamma[c] += dyVal * xhatVal

			dxhatVal := dyVal * gamma[c]
			rowDxhat[c] = dxhatVal
			sumDxhat += dxhatVal
			sumDxhatXhat += dxhatVal * xhatVal
		}

		n := float64(cols)
		si := stdInv[r]
		for c := 0; c < cols; c++ {
			idx := r*cols + c
			dx[idx] = (si / n) * (n*rowDxhat[c] - sumDxhat - xhat[idx]*sumDxhatXhat)
		}
	}

	return dx, dgamma, dbeta
}

// reluBackward computes the real gradient through ReLU: dPre[i] =
// dOut[i] if pre[i] > 0, else 0 -- the standard, well-known ReLU
// gradient rule.
func reluBackward(dOut, pre []float64) []float64 {
	dPre := make([]float64, len(dOut))
	for i := range dOut {
		if pre[i] > 0 {
			dPre[i] = dOut[i]
		}
	}
	return dPre
}

// sumRows sums a rows x cols matrix down to a single cols-length
// vector -- the real, standard bias gradient (a bias is added to
// every row, so its gradient is the sum of the incoming gradient
// across all rows).
func sumRows(m []float64, rows, cols int) []float64 {
	out := make([]float64, cols)
	for r := 0; r < rows; r++ {
		for c := 0; c < cols; c++ {
			out[c] += m[r*cols+c]
		}
	}
	return out
}

// BackwardFFN computes the real gradients through the feed-forward
// block (Linear -> ReLU -> Linear) plus the real residual split,
// given dResid2 (the gradient flowing back from LayerNorm2). Since
// Resid2 = Norm1Out + FF2Out, the same incoming gradient flows into
// BOTH branches of the residual sum -- a real, standard property of
// addition's own backward rule.
func BackwardFFN(cache *ForwardCache, m *AMDHistoryModel, dResid2 []float64) (dW1, dB1, dW2, dB2, dNorm1Out []float64, err error) {
	seqLen := cache.SeqLen
	dModel := m.DModel
	dFF := m.DFF

	// Real residual split: the same gradient flows into both branches.
	dNorm1OutFromResidual := dResid2
	dFF2Out := dResid2

	// Backward through FF2 (Linear: FF1Out @ W2 + B2 = FF2Out).
	ff1OutT := transpose(cache.FF1Out, seqLen, dFF)
	dW2, err = native.GPUMatMul(ff1OutT, dFF2Out, dFF, seqLen, dModel)
	if err != nil {
		return nil, nil, nil, nil, nil, fmt.Errorf("backward ffn: computing dW2: %w", err)
	}
	dB2 = sumRows(dFF2Out, seqLen, dModel)

	w2T := transpose(m.W2, dFF, dModel)
	dFF1Out, err := native.GPUMatMul(dFF2Out, w2T, seqLen, dModel, dFF)
	if err != nil {
		return nil, nil, nil, nil, nil, fmt.Errorf("backward ffn: computing dFF1Out: %w", err)
	}

	// Backward through ReLU.
	dFF1Pre := reluBackward(dFF1Out, cache.FF1Pre)

	// Backward through FF1 (Linear: Norm1Out @ W1 + B1 = FF1Pre).
	norm1OutT := transpose(cache.Norm1Out, seqLen, dModel)
	dW1, err = native.GPUMatMul(norm1OutT, dFF1Pre, dModel, seqLen, dFF)
	if err != nil {
		return nil, nil, nil, nil, nil, fmt.Errorf("backward ffn: computing dW1: %w", err)
	}
	dB1 = sumRows(dFF1Pre, seqLen, dFF)

	w1T := transpose(m.W1, dModel, dFF)
	dNorm1OutFromFFN, err := native.GPUMatMul(dFF1Pre, w1T, seqLen, dFF, dModel)
	if err != nil {
		return nil, nil, nil, nil, nil, fmt.Errorf("backward ffn: computing dNorm1Out contribution: %w", err)
	}

	// Real, total gradient: both real contributions to Norm1Out, added.
	dNorm1Out = addSlices(dNorm1OutFromResidual, dNorm1OutFromFFN)

	return dW1, dB1, dW2, dB2, dNorm1Out, nil
}

// BackwardResid1AndNorm1 backward through LayerNorm1 (reusing the
// same real, proven BackwardLayerNorm formula) and the real residual
// split for Resid1 = EmbeddedInput + AttnProj -- the same incoming
// gradient flows into both branches, matching addition's own
// standard backward rule (same pattern as Resid2's split).
func BackwardResid1AndNorm1(cache *ForwardCache, m *AMDHistoryModel, dNorm1Out []float64) (dEmbeddedFromResid1, dAttnProj, dGamma1, dBeta1 []float64) {
	seqLen := cache.SeqLen
	dModel := m.DModel

	dResid1, dGamma1, dBeta1 := BackwardLayerNorm(dNorm1Out, cache.Norm1Xhat, m.Gamma1, cache.Norm1StdInv, seqLen, dModel)

	dEmbeddedFromResid1 = dResid1
	dAttnProj = dResid1

	return dEmbeddedFromResid1, dAttnProj, dGamma1, dBeta1
}

// BackwardAttnOutputAndWeightedSum computes the real gradients through
// the attention output projection (AttnProj = AttnOut @ Wo) and the
// real weighted sum (AttnOut = AttnWeights @ V) -- the same familiar
// Y = X@W backward math already proven for the output layer and FFN,
// just applied to attention's own matrices.
func BackwardAttnOutputAndWeightedSum(cache *ForwardCache, m *AMDHistoryModel, dAttnProj []float64) (dWo, dAttnWeights, dV []float64, err error) {
	seqLen := cache.SeqLen
	dModel := m.DModel

	// Backward through AttnProj = AttnOut @ Wo.
	attnOutT := transpose(cache.AttnOut, seqLen, dModel)
	dWo, err = native.GPUMatMul(attnOutT, dAttnProj, dModel, seqLen, dModel)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("backward attn output: computing dWo: %w", err)
	}

	woT := transpose(m.Wo, dModel, dModel)
	dAttnOut, err := native.GPUMatMul(dAttnProj, woT, seqLen, dModel, dModel)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("backward attn output: computing dAttnOut: %w", err)
	}

	// Backward through AttnOut = AttnWeights @ V.
	attnWeightsT := transpose(cache.AttnWeights, seqLen, seqLen)
	dV, err = native.GPUMatMul(attnWeightsT, dAttnOut, seqLen, seqLen, dModel)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("backward attn output: computing dV: %w", err)
	}

	vT := transpose(cache.V, seqLen, dModel)
	dAttnWeights, err = native.GPUMatMul(dAttnOut, vT, seqLen, dModel, seqLen)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("backward attn output: computing dAttnWeights: %w", err)
	}

	return dWo, dAttnWeights, dV, nil
}

// softmaxBackward computes the real, standalone gradient through a
// row-wise softmax -- genuinely different from the earlier combined
// softmax+cross-entropy shortcut, since attention's softmax isn't
// followed directly by a loss. Real, standard formula per row
// (y = softmax(x)): dx[i] = y[i] * (dy[i] - sum_j(dy[j]*y[j])).
func softmaxBackward(dy, y []float64, rows, cols int) []float64 {
	dx := make([]float64, rows*cols)
	for r := 0; r < rows; r++ {
		sum := 0.0
		for c := 0; c < cols; c++ {
			idx := r*cols + c
			sum += dy[idx] * y[idx]
		}
		for c := 0; c < cols; c++ {
			idx := r*cols + c
			dx[idx] = y[idx] * (dy[idx] - sum)
		}
	}
	return dx
}

// BackwardAttnScoresAndQK computes the real gradients through the
// attention softmax and the scaled Q@K^T dot product. Given
// AttnScores = (Q @ K^T) * scale, the scale is a scalar so its
// backward is just elementwise scaling; the real Q/K gradients follow
// the same familiar matmul backward rule already proven elsewhere.
func BackwardAttnScoresAndQK(cache *ForwardCache, m *AMDHistoryModel, dAttnWeights []float64) (dQ, dK []float64, err error) {
	seqLen := cache.SeqLen
	dModel := m.DModel

	dAttnScores := softmaxBackward(dAttnWeights, cache.AttnWeights, seqLen, seqLen)

	scale := 1.0 / math.Sqrt(float64(dModel))
	dQK := make([]float64, len(dAttnScores))
	for i, v := range dAttnScores {
		dQK[i] = v * scale
	}

	// AttnScores = Q @ K^T, so dQ = dQK @ K, dK = dQK^T @ Q.
	dQ, err = native.GPUMatMul(dQK, cache.K, seqLen, seqLen, dModel)
	if err != nil {
		return nil, nil, fmt.Errorf("backward attn scores: computing dQ: %w", err)
	}

	dQKT := transpose(dQK, seqLen, seqLen)
	dK, err = native.GPUMatMul(dQKT, cache.Q, seqLen, seqLen, dModel)
	if err != nil {
		return nil, nil, fmt.Errorf("backward attn scores: computing dK: %w", err)
	}

	return dQ, dK, nil
}

// BackwardQKVProjections computes the real gradients through the Q,
// K, V projection matrices, using the same familiar Y=X@W backward
// rule already proven for every other linear layer in this model.
func BackwardQKVProjections(cache *ForwardCache, m *AMDHistoryModel, dQ, dK, dV []float64) (dWq, dWk, dWv, dEmbeddedFromQKV []float64, err error) {
	seqLen := cache.SeqLen
	dModel := m.DModel

	embeddedT := transpose(cache.EmbeddedInput, seqLen, dModel)

	dWq, err = native.GPUMatMul(embeddedT, dQ, dModel, seqLen, dModel)
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("backward qkv: computing dWq: %w", err)
	}
	dWk, err = native.GPUMatMul(embeddedT, dK, dModel, seqLen, dModel)
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("backward qkv: computing dWk: %w", err)
	}
	dWv, err = native.GPUMatMul(embeddedT, dV, dModel, seqLen, dModel)
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("backward qkv: computing dWv: %w", err)
	}

	wqT := transpose(m.Wq, dModel, dModel)
	dEmbeddedFromQ, err := native.GPUMatMul(dQ, wqT, seqLen, dModel, dModel)
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("backward qkv: computing dEmbeddedFromQ: %w", err)
	}
	wkT := transpose(m.Wk, dModel, dModel)
	dEmbeddedFromK, err := native.GPUMatMul(dK, wkT, seqLen, dModel, dModel)
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("backward qkv: computing dEmbeddedFromK: %w", err)
	}
	wvT := transpose(m.Wv, dModel, dModel)
	dEmbeddedFromV, err := native.GPUMatMul(dV, wvT, seqLen, dModel, dModel)
	if err != nil {
		return nil, nil, nil, nil, fmt.Errorf("backward qkv: computing dEmbeddedFromV: %w", err)
	}

	dEmbeddedFromQKV = addSlices(addSlices(dEmbeddedFromQ, dEmbeddedFromK), dEmbeddedFromV)

	return dWq, dWk, dWv, dEmbeddedFromQKV, nil
}

// BackwardEmbedding scatter-adds the real, total per-position
// embedded-input gradient back into the embedding table, at the
// position corresponding to each real token actually used --
// accumulating (not overwriting) if the same token appears more than
// once in the sequence, matching how a real embedding lookup's
// gradient genuinely works.
func BackwardEmbedding(m *AMDHistoryModel, tokenIDs []int, dEmbeddedInput []float64) []float64 {
	dEmbedding := make([]float64, m.VocabSize*m.DModel)
	for i, tok := range tokenIDs {
		for c := 0; c < m.DModel; c++ {
			dEmbedding[tok*m.DModel+c] += dEmbeddedInput[i*m.DModel+c]
		}
	}
	return dEmbedding
}
