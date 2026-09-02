package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/architectureeval"
)

func main() {
	report, err := architectureeval.Evaluate()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(report); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
