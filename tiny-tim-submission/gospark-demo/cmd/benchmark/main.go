package main

import (
	"flag"
	"fmt"
	"time"

	"haroldDemo/gospark-demo/model"
)

func main() {
	dModel := flag.Int("dmodel", 32, "model dimension")
	dFF := flag.Int("dff", 64, "feed-forward dimension")
	vocabSize := flag.Int("vocab", 50, "vocabulary size")
	seqLen := flag.Int("seqlen", 8, "sequence length for benchmarking")
	forwardIters := flag.Int("forwarditers", 100, "number of real forward passes to benchmark")
	trainIters := flag.Int("trainiters", 50, "number of real training steps to benchmark")
	flag.Parse()

	fmt.Println("=== Real GoSpark-Demo Benchmark ===")
	fmt.Println("Real Go -> cgo -> HIP -> ROCm compute path")
	fmt.Printf("Config: dModel=%d, dFF=%d, vocabSize=%d, seqLen=%d\n\n", *dModel, *dFF, *vocabSize, *seqLen)

	m := model.NewAMDHistoryModel(*vocabSize, *dModel, *dFF, *seqLen+2, 42)

	tokenIDs := make([]int, *seqLen)
	for i := range tokenIDs {
		tokenIDs[i] = i % *vocabSize
	}

	// Real, live forward-pass benchmark.
	fmt.Printf("Running %d real forward passes...\n", *forwardIters)
	start := time.Now()
	for i := 0; i < *forwardIters; i++ {
		if _, err := m.Forward(tokenIDs); err != nil {
			fmt.Printf("forward pass failed: %v\n", err)
			return
		}
	}
	forwardElapsed := time.Since(start)
	forwardPerSec := float64(*forwardIters) / forwardElapsed.Seconds()

	fmt.Printf("  Total time: %v\n", forwardElapsed.Round(time.Millisecond))
	fmt.Printf("  Forward passes/sec: %.2f\n", forwardPerSec)
	fmt.Printf("  Avg time per forward pass: %v\n\n", (forwardElapsed / time.Duration(*forwardIters)).Round(time.Microsecond))

	// Real, live training-step benchmark (forward + complete backward
	// pass + optimizer step).
	targets := make([]int, *seqLen)
	for i := range targets {
		targets[i] = (i + 1) % *vocabSize
	}
	opt := model.NewSimpleOptimizer(0.01)

	fmt.Printf("Running %d real training steps (forward + full backward + optimizer)...\n", *trainIters)
	start = time.Now()
	var lastLoss float64
	for i := 0; i < *trainIters; i++ {
		loss, err := model.TrainStep(m, opt, tokenIDs, targets)
		if err != nil {
			fmt.Printf("train step failed: %v\n", err)
			return
		}
		lastLoss = loss
	}
	trainElapsed := time.Since(start)
	trainStepsPerSec := float64(*trainIters) / trainElapsed.Seconds()
	tokensPerSec := float64(*trainIters**seqLen) / trainElapsed.Seconds()

	fmt.Printf("  Total time: %v\n", trainElapsed.Round(time.Millisecond))
	fmt.Printf("  Training steps/sec: %.2f\n", trainStepsPerSec)
	fmt.Printf("  Real tokens/sec (training): %.2f\n", tokensPerSec)
	fmt.Printf("  Avg time per training step: %v\n", (trainElapsed / time.Duration(*trainIters)).Round(time.Microsecond))
	fmt.Printf("  Final loss after benchmark run: %.6f\n", lastLoss)
}
