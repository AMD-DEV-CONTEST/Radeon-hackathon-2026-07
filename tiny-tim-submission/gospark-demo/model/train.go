package model

import "fmt"

// SimpleOptimizer is a genuinely narrow, hardcoded gradient-descent
// step -- deliberately NOT GoSpark's real AdamW implementation, a
// real, simpler, different optimizer appropriate for this narrow
// demo's own scope.
type SimpleOptimizer struct {
	LR float64
}

// NewSimpleOptimizer creates a real, simple optimizer with the given
// learning rate.
func NewSimpleOptimizer(lr float64) *SimpleOptimizer {
	return &SimpleOptimizer{LR: lr}
}

// Step applies a real, simple gradient descent update: param -= lr*grad.
func (o *SimpleOptimizer) Step(param, grad []float64) {
	for i := range param {
		param[i] -= o.LR * grad[i]
	}
}

// TrainStep runs one real, complete forward + backward + optimizer
// step for a single real token sequence, chaining together the entire
// real, hand-derived backward pass -- every piece already built and
// individually hand-verified across every layer of the model.
// Returns the real loss for this step.
func TrainStep(m *AMDHistoryModel, opt *SimpleOptimizer, tokenIDs []int, targets []int) (float64, error) {
	cache, err := m.Forward(tokenIDs)
	if err != nil {
		return 0, fmt.Errorf("train step: forward: %w", err)
	}

	seqLen := cache.SeqLen
	loss, err := CrossEntropyLoss(cache.Probs, targets, seqLen, m.VocabSize)
	if err != nil {
		return 0, fmt.Errorf("train step: computing loss: %w", err)
	}

	dOutputProj, dNorm2Out, err := BackwardOutputLayer(cache, m, targets)
	if err != nil {
		return 0, fmt.Errorf("train step: backward output layer: %w", err)
	}

	dResid2, dGamma2, dBeta2 := BackwardLayerNorm(dNorm2Out, cache.Norm2Xhat, m.Gamma2, cache.Norm2StdInv, seqLen, m.DModel)

	dW1, dB1, dW2, dB2, dNorm1Out, err := BackwardFFN(cache, m, dResid2)
	if err != nil {
		return 0, fmt.Errorf("train step: backward ffn: %w", err)
	}

	dEmbeddedFromResid1, dAttnProj, dGamma1, dBeta1 := BackwardResid1AndNorm1(cache, m, dNorm1Out)

	dWo, dAttnWeights, dV, err := BackwardAttnOutputAndWeightedSum(cache, m, dAttnProj)
	if err != nil {
		return 0, fmt.Errorf("train step: backward attn output: %w", err)
	}

	dQ, dK, err := BackwardAttnScoresAndQK(cache, m, dAttnWeights)
	if err != nil {
		return 0, fmt.Errorf("train step: backward attn scores: %w", err)
	}

	dWq, dWk, dWv, dEmbeddedFromQKV, err := BackwardQKVProjections(cache, m, dQ, dK, dV)
	if err != nil {
		return 0, fmt.Errorf("train step: backward qkv: %w", err)
	}

	dEmbeddedTotal := addSlices(dEmbeddedFromResid1, dEmbeddedFromQKV)
	dEmbedding := BackwardEmbedding(m, tokenIDs, dEmbeddedTotal)

	// Real, complete optimizer step -- every real, learnable parameter
	// updated using its own real, hand-derived gradient.
	opt.Step(m.OutputProj, dOutputProj)
	opt.Step(m.Gamma2, dGamma2)
	opt.Step(m.Beta2, dBeta2)
	opt.Step(m.W1, dW1)
	opt.Step(m.B1, dB1)
	opt.Step(m.W2, dW2)
	opt.Step(m.B2, dB2)
	opt.Step(m.Gamma1, dGamma1)
	opt.Step(m.Beta1, dBeta1)
	opt.Step(m.Wo, dWo)
	opt.Step(m.Wq, dWq)
	opt.Step(m.Wk, dWk)
	opt.Step(m.Wv, dWv)
	opt.Step(m.Embedding, dEmbedding)

	return loss, nil
}
