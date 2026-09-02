package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/rvbernucci/signalforge/internal/golden"
	"github.com/rvbernucci/signalforge/internal/workspace"
)

func main() {
	input := flag.String("input", "", "private golden report JSON")
	output := flag.String("output", "", "safe research workspace JSON")
	flag.Parse()
	if *input == "" || *output == "" {
		fatal(fmt.Errorf("--input and --output are required"))
	}
	payload, err := os.ReadFile(*input)
	if err != nil {
		fatal(err)
	}
	var report golden.Report
	if err := json.Unmarshal(payload, &report); err != nil {
		fatal(fmt.Errorf("decode golden report: %w", err))
	}
	projection, err := workspace.Project(report)
	if err != nil {
		fatal(err)
	}
	payload, err = json.MarshalIndent(projection, "", "  ")
	if err != nil {
		fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(*output), 0o750); err != nil {
		fatal(err)
	}
	if err := os.WriteFile(*output, append(payload, '\n'), 0o640); err != nil {
		fatal(err)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
