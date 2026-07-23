package model

import (
	"fmt"
	"math"
	"math/rand"

	"haroldDemo/gospark-demo/native"
)

// AMDHistoryModel is a genuinely narrow, single-block transformer --
// real, hardcoded dimensions, real single-head self-attention, real
// GPU compute for every step via the proven native kernels. Not a
// general framework: fixed architecture, explicit weight fields, no
// reusable Tensor[T]/autograd abstraction.
type AMDHistoryModel struct {
	VocabSize int
	DModel    int
	DFF       int
	MaxSeqLen int

	// Token embeddings -- real lookup table, VocabSize x DModel.
	Embedding []float64

	// Single-head self-attention weights, all DModel x DModel.
	Wq, Wk, Wv, Wo []float64

	// LayerNorm 1 (post-attention).
	Gamma1, Beta1 []float64

	// Feed-forward: DModel -> DFF -> DModel.
	W1 []float64 // DModel x DFF
	B1 []float64 // DFF
	W2 []float64 // DFF x DModel
	B2 []float64 // DModel

	// LayerNorm 2 (post-FFN).
	Gamma2, Beta2 []float64

	// Output projection to vocabulary, DModel x VocabSize.
	OutputProj []float64
}

// NewAMDHistoryModel creates a real model with random initialization
// (small, deterministic-seedable values -- real, not zeros, since
// zero-initialized weights would never learn).
func NewAMDHistoryModel(vocabSize, dModel, dFF, maxSeqLen int, seed int64) *AMDHistoryModel {
	r := rand.New(rand.NewSource(seed))
	initSlice := func(n int) []float64 {
		s := make([]float64, n)
		for i := range s {
			s[i] = (r.Float64() - 0.5) * 0.1
		}
		return s
	}
	ones := func(n int) []float64 {
		s := make([]float64, n)
		for i := range s {
			s[i] = 1.0
		}
		return s
	}
	zeros := func(n int) []float64 {
		return make([]float64, n)
	}

	return &AMDHistoryModel{
		VocabSize:  vocabSize,
		DModel:     dModel,
		DFF:        dFF,
		MaxSeqLen:  maxSeqLen,
		Embedding:  initSlice(vocabSize * dModel),
		Wq:         initSlice(dModel * dModel),
		Wk:         initSlice(dModel * dModel),
		Wv:         initSlice(dModel * dModel),
		Wo:         initSlice(dModel * dModel),
		Gamma1:     ones(dModel),
		Beta1:      zeros(dModel),
		W1:         initSlice(dModel * dFF),
		B1:         zeros(dFF),
		W2:         initSlice(dFF * dModel),
		B2:         zeros(dModel),
		Gamma2:     ones(dModel),
		Beta2:      zeros(dModel),
		OutputProj: initSlice(dModel * vocabSize),
	}
}

// ForwardCache holds every real intermediate value from a forward
// pass that the (upcoming) hand-derived backward pass will need --
// explicit and narrow, not a generic autograd tape.
type ForwardCache struct {
	TokenIDs      []int
	SeqLen        int
	EmbeddedInput []float64 // seqLen x dModel
	Q, K, V       []float64 // seqLen x dModel each
	AttnScores    []float64 // seqLen x seqLen, pre-softmax
	AttnWeights   []float64 // seqLen x seqLen, post-softmax
	AttnOut       []float64 // seqLen x dModel, weighted sum of V
	AttnProj      []float64 // seqLen x dModel, after Wo
	Resid1        []float64 // seqLen x dModel, embedded + attnProj
	Norm1Out      []float64
	Norm1Xhat     []float64
	Norm1StdInv   []float64
	FF1Pre        []float64 // seqLen x dFF, before ReLU
	FF1Out        []float64 // seqLen x dFF, after ReLU
	FF2Out        []float64 // seqLen x dModel
	Resid2        []float64
	Norm2Out      []float64
	Norm2Xhat     []float64
	Norm2StdInv   []float64
	Logits        []float64 // seqLen x vocabSize
	Probs         []float64 // seqLen x vocabSize, post-softmax
}

// Forward runs the real, complete forward pass for a token sequence,
// using real GPU compute at every step via the proven native kernels.
// Returns real output probabilities over the vocabulary for each
// position, plus a real cache of every intermediate value the
// (upcoming) backward pass will need.
func (m *AMDHistoryModel) Forward(tokenIDs []int) (*ForwardCache, error) {
	seqLen := len(tokenIDs)
	if seqLen == 0 {
		return nil, fmt.Errorf("forward: empty token sequence")
	}
	if seqLen > m.MaxSeqLen {
		return nil, fmt.Errorf("forward: sequence length %d exceeds MaxSeqLen %d", seqLen, m.MaxSeqLen)
	}

	cache := &ForwardCache{TokenIDs: tokenIDs, SeqLen: seqLen}

	// Real embedding lookup -- a genuinely simple gather, no GPU kernel
	// needed for this step (matches GoSpark's own real EmbeddingLookup
	// design choice).
	embedded := make([]float64, seqLen*m.DModel)
	for i, tok := range tokenIDs {
		if tok < 0 || tok >= m.VocabSize {
			return nil, fmt.Errorf("forward: token id %d out of vocab range [0,%d)", tok, m.VocabSize)
		}
		copy(embedded[i*m.DModel:(i+1)*m.DModel], m.Embedding[tok*m.DModel:(tok+1)*m.DModel])
	}
	cache.EmbeddedInput = embedded

	// Real Q, K, V projections via the real GPU matmul kernel.
	q, err := native.GPUMatMul(embedded, m.Wq, seqLen, m.DModel, m.DModel)
	if err != nil {
		return nil, fmt.Errorf("forward: computing Q: %w", err)
	}
	k, err := native.GPUMatMul(embedded, m.Wk, seqLen, m.DModel, m.DModel)
	if err != nil {
		return nil, fmt.Errorf("forward: computing K: %w", err)
	}
	v, err := native.GPUMatMul(embedded, m.Wv, seqLen, m.DModel, m.DModel)
	if err != nil {
		return nil, fmt.Errorf("forward: computing V: %w", err)
	}
	cache.Q, cache.K, cache.V = q, k, v

	// Real attention scores: Q @ K^T / sqrt(dModel).
	kT := transpose(k, seqLen, m.DModel)
	scores, err := native.GPUMatMul(q, kT, seqLen, m.DModel, seqLen)
	if err != nil {
		return nil, fmt.Errorf("forward: computing attention scores: %w", err)
	}
	scale := 1.0 / math.Sqrt(float64(m.DModel))
	for i := range scores {
		scores[i] *= scale
	}
	cache.AttnScores = scores

	// Real softmax over attention scores, via the real GPU kernel.
	attnWeights, err := native.GPUSoftmax(scores, seqLen, seqLen)
	if err != nil {
		return nil, fmt.Errorf("forward: attention softmax: %w", err)
	}
	cache.AttnWeights = attnWeights

	// Real weighted sum of V.
	attnOut, err := native.GPUMatMul(attnWeights, v, seqLen, seqLen, m.DModel)
	if err != nil {
		return nil, fmt.Errorf("forward: computing attention output: %w", err)
	}
	cache.AttnOut = attnOut

	// Real output projection.
	attnProj, err := native.GPUMatMul(attnOut, m.Wo, seqLen, m.DModel, m.DModel)
	if err != nil {
		return nil, fmt.Errorf("forward: computing attention output projection: %w", err)
	}
	cache.AttnProj = attnProj

	// Real residual connection + real LayerNorm.
	resid1 := addSlices(embedded, attnProj)
	cache.Resid1 = resid1
	norm1Out, norm1Xhat, norm1StdInv, err := native.GPULayerNorm(resid1, m.Gamma1, m.Beta1, seqLen, m.DModel, 1e-5)
	if err != nil {
		return nil, fmt.Errorf("forward: layernorm 1: %w", err)
	}
	cache.Norm1Out, cache.Norm1Xhat, cache.Norm1StdInv = norm1Out, norm1Xhat, norm1StdInv

	// Real feed-forward: Linear -> ReLU -> Linear.
	ff1Pre, err := native.GPUMatMul(norm1Out, m.W1, seqLen, m.DModel, m.DFF)
	if err != nil {
		return nil, fmt.Errorf("forward: FF1: %w", err)
	}
	ff1Pre = addBias(ff1Pre, m.B1, seqLen, m.DFF)
	cache.FF1Pre = ff1Pre

	ff1Out, err := native.GPUReLU(ff1Pre)
	if err != nil {
		return nil, fmt.Errorf("forward: FF ReLU: %w", err)
	}
	cache.FF1Out = ff1Out

	ff2Out, err := native.GPUMatMul(ff1Out, m.W2, seqLen, m.DFF, m.DModel)
	if err != nil {
		return nil, fmt.Errorf("forward: FF2: %w", err)
	}
	ff2Out = addBias(ff2Out, m.B2, seqLen, m.DModel)
	cache.FF2Out = ff2Out

	// Real residual connection + real LayerNorm.
	resid2 := addSlices(norm1Out, ff2Out)
	cache.Resid2 = resid2
	norm2Out, norm2Xhat, norm2StdInv, err := native.GPULayerNorm(resid2, m.Gamma2, m.Beta2, seqLen, m.DModel, 1e-5)
	if err != nil {
		return nil, fmt.Errorf("forward: layernorm 2: %w", err)
	}
	cache.Norm2Out, cache.Norm2Xhat, cache.Norm2StdInv = norm2Out, norm2Xhat, norm2StdInv

	// Real output projection to vocabulary, plus real softmax for
	// real next-token probabilities.
	logits, err := native.GPUMatMul(norm2Out, m.OutputProj, seqLen, m.DModel, m.VocabSize)
	if err != nil {
		return nil, fmt.Errorf("forward: output projection: %w", err)
	}
	cache.Logits = logits

	probs, err := native.GPUSoftmax(logits, seqLen, m.VocabSize)
	if err != nil {
		return nil, fmt.Errorf("forward: output softmax: %w", err)
	}
	cache.Probs = probs

	return cache, nil
}

// transpose returns the real transpose of an rows x cols matrix.
func transpose(m []float64, rows, cols int) []float64 {
	out := make([]float64, rows*cols)
	for r := 0; r < rows; r++ {
		for c := 0; c < cols; c++ {
			out[c*rows+r] = m[r*cols+c]
		}
	}
	return out
}

// addSlices returns the real element-wise sum of two equal-length slices.
func addSlices(a, b []float64) []float64 {
	out := make([]float64, len(a))
	for i := range a {
		out[i] = a[i] + b[i]
	}
	return out
}

// addBias adds a real per-column bias vector to every row of a
// rows x cols matrix.
func addBias(m []float64, bias []float64, rows, cols int) []float64 {
	out := make([]float64, len(m))
	for r := 0; r < rows; r++ {
		for c := 0; c < cols; c++ {
			out[r*cols+c] = m[r*cols+c] + bias[c]
		}
	}
	return out
}
