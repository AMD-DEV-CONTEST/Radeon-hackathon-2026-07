package main

import (
	"context"
	"flag"
	"fmt"
	"os"

	"github.com/konspace/unionagents-go/internal/boundary"
)

func cmdBoundary(args []string) {
	if len(args) < 1 || args[0] != "status" {
		fmt.Fprintf(os.Stderr, "用法:\n  %s boundary status [--json]\n", os.Args[0])
		os.Exit(1)
	}

	fs := flag.NewFlagSet("boundary status", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", uasEnvOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	orchestratorURL := fs.String("orchestrator-url", uasEnvOr("ORCHESTRATOR_URL", "http://111.228.42.18:8000"), "UAS Orchestrator URL")
	jsonOutput := fs.Bool("json", false, "print JSON output")
	if err := fs.Parse(args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}

	status := boundary.FetchCombinedStatus(context.Background(), *gatewayURL, *orchestratorURL)
	out, err := boundary.FormatCombinedStatus(status, *jsonOutput)
	if err != nil {
		fmt.Fprintf(os.Stderr, "format boundary status: %v\n", err)
		os.Exit(1)
	}
	fmt.Println(out)
	if !status.GatewayOK || !status.OrchestratorOK {
		os.Exit(1)
	}
}

func uasEnvOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
