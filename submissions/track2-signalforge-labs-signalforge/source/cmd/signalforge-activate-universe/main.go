package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/rvbernucci/signalforge/internal/productscope"
)

func main() {
	input := flag.String("coverage", "", "Path to the frozen XBRL metric coverage report")
	output := flag.String("output", "", "Path for the activation matrix")
	publicCatalogOutput := flag.String("public-catalog-output", "", "Optional path for the public-safe product catalog")
	flag.Parse()
	if *input == "" || *output == "" {
		exit(fmt.Errorf("--coverage and --output are required"))
	}
	payload, err := os.ReadFile(*input)
	if err != nil {
		exit(err)
	}
	var report productscope.CoverageReport
	if err := json.Unmarshal(payload, &report); err != nil {
		exit(err)
	}
	digest := sha256.Sum256(payload)
	matrix, err := productscope.BuildActivationMatrix(report, hex.EncodeToString(digest[:]))
	if err != nil {
		exit(err)
	}
	encoded, err := json.MarshalIndent(matrix, "", "  ")
	if err != nil {
		exit(err)
	}
	encoded = append(encoded, '\n')
	if err := os.MkdirAll(filepath.Dir(*output), 0o755); err != nil {
		exit(err)
	}
	if err := os.WriteFile(*output, encoded, 0o644); err != nil {
		exit(err)
	}
	if *publicCatalogOutput != "" {
		catalog, buildErr := productscope.BuildPublicCatalog(matrix)
		if buildErr != nil {
			exit(buildErr)
		}
		catalogPayload, marshalErr := json.MarshalIndent(catalog, "", "  ")
		if marshalErr != nil {
			exit(marshalErr)
		}
		catalogPayload = append(catalogPayload, '\n')
		if mkdirErr := os.MkdirAll(filepath.Dir(*publicCatalogOutput), 0o755); mkdirErr != nil {
			exit(mkdirErr)
		}
		if writeErr := os.WriteFile(*publicCatalogOutput, catalogPayload, 0o644); writeErr != nil {
			exit(writeErr)
		}
	}
}

func exit(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
