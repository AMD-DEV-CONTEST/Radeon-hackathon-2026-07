//go:build ignore

package main

import (
	"encoding/json"
	"fmt"
	"os"
)

const (
	defaultSourceSchema = "D:/OMIMA/packages/protocol/src/ledger/schema.json"
	targetSchema        = "testdata/schema.json"
	sourceEnv           = "OMIMA_LEDGER_SCHEMA"
)

func main() {
	source := os.Getenv(sourceEnv)
	if source == "" {
		source = defaultSourceSchema
	}

	data, err := os.ReadFile(source)
	if err != nil {
		fatalf("read source schema %s: %v", source, err)
	}
	if !json.Valid(data) {
		fatalf("source schema %s is not valid JSON", source)
	}
	if err := os.WriteFile(targetSchema, data, 0644); err != nil {
		fatalf("write target schema %s: %v", targetSchema, err)
	}
}

func fatalf(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, "generate_schema: "+format+"\n", args...)
	os.Exit(1)
}
