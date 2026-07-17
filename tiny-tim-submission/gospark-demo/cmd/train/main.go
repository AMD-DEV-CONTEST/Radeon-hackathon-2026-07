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
	dataPath := flag.String("data", "", "path to a real text file, one training sentence per line")
	epochs := flag.Int("epochs", 50, "number of real training epochs")
	lr := flag.Float64("lr", 0.01, "learning rate")
	dModel := flag.Int("dmodel", 32, "model dimension")
	dFF := flag.Int("dff", 64, "feed-forward dimension")
	maxSeqLen := flag.Int("maxseqlen", 32, "maximum sequence length")
	outPath := flag.String("out", "checkpoint.json", "path to save the real, trained checkpoint")
	seed := flag.Int64("seed", 42, "real seed for reproducible initialization")
	flag.Parse()

	if *dataPath == "" {
		fmt.Fprintln(os.Stderr, "usage: train -data <path> [-epochs N] [-lr X] [-out checkpoint.json]")
		os.Exit(1)
	}

	lines, err := readLines(*dataPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "reading data file: %v\n", err)
		os.Exit(1)
	}
	if len(lines) == 0 {
		fmt.Fprintln(os.Stderr, "no real training lines found in data file")
		os.Exit(1)
	}
	fmt.Printf("Loaded %d real training lines from %s\n", len(lines), *dataPath)

	vocab := model.BuildVocabulary(lines)
	fmt.Printf("Built real vocabulary: %d unique words\n", vocab.Size())

	m := model.NewAMDHistoryModel(vocab.Size(), *dModel, *dFF, *maxSeqLen, *seed)
	opt := model.NewSimpleOptimizer(*lr)

	fmt.Printf("Starting real training: %d epochs, lr=%v, dModel=%d, dFF=%d\n", *epochs, *lr, *dModel, *dFF)

	for epoch := 0; epoch < *epochs; epoch++ {
		totalLoss := 0.0
		numSteps := 0

		for _, line := range lines {
			ids := vocab.Encode(line)
			if len(ids) < 2 {
				continue // need at least 2 real tokens for an input/target pair
			}
			if len(ids) > *maxSeqLen+1 {
				ids = ids[:*maxSeqLen+1]
			}

			input := ids[:len(ids)-1]
			target := ids[1:]

			loss, err := model.TrainStep(m, opt, input, target)
			if err != nil {
				fmt.Fprintf(os.Stderr, "train step failed: %v\n", err)
				continue
			}
			totalLoss += loss
			numSteps++
		}

		if numSteps > 0 && (epoch%5 == 0 || epoch == *epochs-1) {
			fmt.Printf("epoch %d: avg loss = %.6f (%d real steps)\n", epoch, totalLoss/float64(numSteps), numSteps)
		}
	}

	if err := model.SaveCheckpoint(m, *outPath); err != nil {
		fmt.Fprintf(os.Stderr, "saving checkpoint: %v\n", err)
		os.Exit(1)
	}
	vocabPath := *outPath + ".vocab.json"
	if err := model.SaveVocabulary(vocab, vocabPath); err != nil {
		fmt.Fprintf(os.Stderr, "saving vocabulary: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Real training complete. Checkpoint saved to %s, vocabulary saved to %s\n", *outPath, vocabPath)
}

// readLines reads a real text file, returning every real,
// non-empty, trimmed line.
func readLines(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var lines []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line != "" {
			lines = append(lines, line)
		}
	}
	return lines, scanner.Err()
}
