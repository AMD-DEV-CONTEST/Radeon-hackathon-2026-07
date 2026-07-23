package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"regexp"
)

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type example struct {
	Messages []message `json:"messages"`
}

// claimPattern extracts the real claim text embedded in the standard
// HaroldCorpus/AMDCorpus question format:
// `Is the following claim true, and why: "CLAIM TEXT."`
var claimPattern = regexp.MustCompile(`Is the following claim true, and why: "(.+?)"`)

func main() {
	inPath := flag.String("in", "", "path to a real HaroldCorpus/AMDCorpus.jsonl file")
	outPath := flag.String("out", "", "path to write the real, extracted plain-text claims")
	flag.Parse()

	if *inPath == "" || *outPath == "" {
		fmt.Fprintln(os.Stderr, "usage: extractcorpus -in AMDCorpus.jsonl -out claims.txt")
		os.Exit(1)
	}

	inFile, err := os.Open(*inPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "opening input: %v\n", err)
		os.Exit(1)
	}
	defer inFile.Close()

	outFile, err := os.Create(*outPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "creating output: %v\n", err)
		os.Exit(1)
	}
	defer outFile.Close()

	scanner := bufio.NewScanner(inFile)
	scanner.Buffer(make([]byte, 1024*1024), 10*1024*1024) // real, generous buffer for long lines
	extracted := 0
	total := 0

	for scanner.Scan() {
		total++
		var ex example
		if err := json.Unmarshal(scanner.Bytes(), &ex); err != nil {
			fmt.Fprintf(os.Stderr, "line %d: skipping, invalid JSON: %v\n", total, err)
			continue
		}
		if len(ex.Messages) == 0 {
			continue
		}

		userContent := ex.Messages[0].Content
		matches := claimPattern.FindStringSubmatch(userContent)
		if len(matches) < 2 {
			fmt.Fprintf(os.Stderr, "line %d: no claim pattern match, skipping\n", total)
			continue
		}

		claim := matches[1]
		fmt.Fprintln(outFile, claim)
		extracted++
	}

	if err := scanner.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "scanning input: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Extracted %d real claims from %d total lines, wrote to %s\n", extracted, total, *outPath)
}
