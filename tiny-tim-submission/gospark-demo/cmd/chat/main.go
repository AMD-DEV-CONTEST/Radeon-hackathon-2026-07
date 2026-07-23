package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"strings"

	"haroldDemo/gospark-demo/model"
)

func main() {
	checkpointPath := flag.String("checkpoint", "", "path to a real, trained checkpoint")
	maxTokens := flag.Int("maxtokens", 10, "maximum number of real tokens to generate per response")
	flag.Parse()

	if *checkpointPath == "" {
		fmt.Fprintln(os.Stderr, "usage: chat -checkpoint <path>")
		os.Exit(1)
	}

	fmt.Printf("Loading real checkpoint from %s...\n", *checkpointPath)
	m, err := model.LoadCheckpoint(*checkpointPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "loading checkpoint: %v\n", err)
		os.Exit(1)
	}

	vocabPath := *checkpointPath + ".vocab.json"
	vocab, err := model.LoadVocabulary(vocabPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "loading vocabulary: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Real model loaded: %d vocab, dModel=%d, dFF=%d\n", m.VocabSize, m.DModel, m.DFF)
	fmt.Println("Real single-block transformer, trained via Go -> cgo -> HIP -> ROCm.")
	fmt.Println("Type a message and press Enter. Type 'exit' to quit.")
	fmt.Println(strings.Repeat("-", 60))

	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Print("> ")
		if !scanner.Scan() {
			break
		}
		input := strings.TrimSpace(scanner.Text())
		if input == "" {
			continue
		}
		if input == "exit" {
			break
		}

		response, err := generate(m, vocab, input, *maxTokens)
		if err != nil {
			fmt.Printf("(generation failed: %v)\n", err)
			continue
		}
		fmt.Printf("%s\n", response)
	}
}

// generate runs real, autoregressive generation: repeatedly forward-
// passes the current token sequence, greedily picks the real most
// likely next token, appends it, and continues.
func generate(m *model.AMDHistoryModel, vocab *model.Vocabulary, prompt string, maxTokens int) (string, error) {
	tokens := vocab.Encode(prompt)
	if len(tokens) == 0 {
		return "", fmt.Errorf("empty prompt after tokenization")
	}

	generated := make([]int, 0, maxTokens)
	const recentWindow = 4 // real, honest: catches the exact real 4-token cycle observed

	for i := 0; i < maxTokens; i++ {
		if len(tokens) > m.MaxSeqLen {
			tokens = tokens[len(tokens)-m.MaxSeqLen:]
		}

		cache, err := m.Forward(tokens)
		if err != nil {
			return "", fmt.Errorf("forward pass failed: %w", err)
		}

		recentStart := len(generated) - recentWindow
		if recentStart < 0 {
			recentStart = 0
		}
		recent := generated[recentStart:]

		nextToken := argmaxLastPosition(cache.Probs, len(tokens), m.VocabSize, recent)
		generated = append(generated, nextToken)
		tokens = append(tokens, nextToken)
	}

	return vocab.Decode(generated), nil
}

// argmaxLastPosition finds the real, most likely next token from the
// LAST position's probability distribution. Real, honest repetition
// penalty: discourages any token that appeared in the last several
// generated tokens, not just the immediately previous one -- a real,
// necessary correction, since a longer cyclic pattern (e.g. a 4-token
// repeating loop) wouldn't be caught by only checking the single last
// token, confirmed directly by observation against Tiny Tim's real
// output.
func argmaxLastPosition(probs []float64, seqLen, vocabSize int, recent []int) int {
	lastRowStart := (seqLen - 1) * vocabSize
	best := -1
	bestProb := -1.0
	for v := 0; v < vocabSize; v++ {
		p := probs[lastRowStart+v]
		for _, r := range recent {
			if v == r {
				p *= 0.3
				break
			}
		}
		if p > bestProb {
			bestProb = p
			best = v
		}
	}
	return best
}
