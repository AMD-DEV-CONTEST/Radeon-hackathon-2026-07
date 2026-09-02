package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/rvbernucci/signalforge/internal/golden"
)

func main() {
	reportPath := flag.String("report", "", "private golden investor report JSON")
	rubricPath := flag.String("rubric", "fixtures/golden/semantic-rubric-v5.json", "frozen semantic rubric JSON")
	outputPath := flag.String("output", "", "optional semantic evaluation output path")
	flag.Parse()
	if *reportPath == "" {
		fatal(fmt.Errorf("--report is required"))
	}
	reportPayload, err := os.ReadFile(*reportPath)
	if err != nil {
		fatal(err)
	}
	var report golden.Report
	if err := json.Unmarshal(reportPayload, &report); err != nil {
		fatal(fmt.Errorf("decode golden report: %w", err))
	}
	rubric, rubricSHA, err := golden.LoadSemanticRubric(*rubricPath)
	if err != nil {
		fatal(err)
	}
	evaluation := golden.EvaluateSemantics(report, rubric, rubricSHA, time.Now().UTC())
	payload, err := json.MarshalIndent(evaluation, "", "  ")
	if err != nil {
		fatal(err)
	}
	payload = append(payload, '\n')
	if *outputPath == "" {
		fmt.Print(string(payload))
	} else {
		if err := os.MkdirAll(filepath.Dir(*outputPath), 0o750); err != nil {
			fatal(err)
		}
		if err := os.WriteFile(*outputPath, payload, 0o640); err != nil {
			fatal(err)
		}
	}
	if !evaluation.Passed {
		os.Exit(2)
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
