package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/rvbernucci/signalforge/internal/orchestrationeval"
)

func main() {
	report, err := orchestrationeval.Evaluate()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	encoded, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	os.Stdout.Write(append(encoded, '\n'))
}
