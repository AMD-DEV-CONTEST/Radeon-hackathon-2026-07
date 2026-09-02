package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/rvbernucci/signalforge/internal/golden"
)

func main() {
	input := flag.String("input", "", "safe decision replay JSON to validate")
	flag.Parse()
	if err := run(*input, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(path string, output io.Writer) error {
	if path == "" {
		return errors.New("--input is required")
	}
	file, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open replay: %w", err)
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	decoder.DisallowUnknownFields()
	var replay golden.SafeDecisionReplay
	if err := decoder.Decode(&replay); err != nil {
		return fmt.Errorf("decode replay: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("replay contains multiple JSON values")
		}
		return fmt.Errorf("decode trailing replay data: %w", err)
	}
	if err := golden.ValidateSafeDecisionReplay(replay); err != nil {
		return fmt.Errorf("validate replay: %w", err)
	}
	_, err = fmt.Fprintf(output, "valid safe replay %s (%s, %d routes, %d claims)\n",
		replay.ReplayID, replay.Status, len(replay.Routes), len(replay.Claims))
	return err
}
