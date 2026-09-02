package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/rvbernucci/signalforge/internal/contracts"
	"github.com/rvbernucci/signalforge/internal/engine"
)

func main() {
	requestPath := flag.String("request", "-", "EngineRequest JSON path, or - for stdin")
	outputPath := flag.String("output", "-", "result JSON path, or - for stdout")
	receiptRoot := flag.String("receipt-store", "", "optional immutable receipt-store directory")
	codeCommit := flag.String("code-commit", "", "source revision that owns the formula execution")
	flag.Parse()

	if err := run(*requestPath, *outputPath, *receiptRoot, *codeCommit, os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(requestPath, outputPath, receiptRoot, codeCommit string, stdin io.Reader, stdout io.Writer) error {
	reader := stdin
	if requestPath != "-" {
		file, err := os.Open(filepath.Clean(requestPath))
		if err != nil {
			return err
		}
		defer file.Close()
		reader = file
	}
	decoder := json.NewDecoder(io.LimitReader(reader, 4<<20))
	decoder.DisallowUnknownFields()
	var request contracts.EngineRequest
	if err := decoder.Decode(&request); err != nil {
		return fmt.Errorf("decode engine request: %w", err)
	}
	executor, err := engine.New(codeCommit)
	if err != nil {
		return err
	}
	result := executor.Execute(request)
	if result.Receipt != nil && receiptRoot != "" {
		store, err := engine.NewReceiptStore(receiptRoot)
		if err != nil {
			return err
		}
		if _, err := store.Save(*result.Receipt); err != nil {
			return err
		}
	}

	writer := stdout
	var file *os.File
	if outputPath != "-" {
		if err := os.MkdirAll(filepath.Dir(filepath.Clean(outputPath)), 0o750); err != nil && filepath.Dir(outputPath) != "." {
			return err
		}
		file, err = os.OpenFile(filepath.Clean(outputPath), os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o640)
		if err != nil {
			return err
		}
		defer file.Close()
		writer = file
	}
	encoder := json.NewEncoder(writer)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(result); err != nil {
		return err
	}
	if result.Failure != nil {
		return fmt.Errorf("calculation refused: %s", result.Failure.Message)
	}
	return nil
}
