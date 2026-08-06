package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
)

func cmdGateway(args []string) {
	if len(args) < 1 || args[0] != "status" {
		fmt.Fprintf(os.Stderr, "用法:\n  %s gateway status [--json]\n", os.Args[0])
		os.Exit(1)
	}
	fs := flag.NewFlagSet("gateway status", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	jsonOutput := fs.Bool("json", true, "print JSON output")
	if err := fs.Parse(args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}
	health, healthOK := doctorGetJSON(gatewayHTTPBase(*gatewayURL) + "/health")
	events, eventsOK := doctorGetJSON(gatewayHTTPBase(*gatewayURL) + "/events/status")
	out := map[string]interface{}{
		"status": okStatus(healthOK && eventsOK),
		"health": health,
		"events": events,
	}
	printStatusJSON(out, *jsonOutput)
	if !healthOK || !eventsOK {
		os.Exit(1)
	}
}

func cmdAgent(args []string) {
	if len(args) < 1 || args[0] != "status" {
		fmt.Fprintf(os.Stderr, "用法:\n  %s agent status [--agent-id <id>] [--json]\n", os.Args[0])
		os.Exit(1)
	}
	fs := flag.NewFlagSet("agent status", flag.ExitOnError)
	orchestratorURL := fs.String("orchestrator-url", envOr("ORCHESTRATOR_URL", "http://111.228.42.18:8000"), "UAS Orchestrator URL")
	agentID := fs.String("agent-id", os.Getenv("AGENT_ID"), "filter agent id")
	jsonOutput := fs.Bool("json", true, "print JSON output")
	if err := fs.Parse(args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}
	agents, ok := doctorGetJSON(*orchestratorURL + "/agents")
	out := map[string]interface{}{
		"status":   okStatus(ok),
		"agent_id": *agentID,
		"agents":   filterAgents(agents, *agentID),
	}
	printStatusJSON(out, *jsonOutput)
	if !ok {
		os.Exit(1)
	}
}

func filterAgents(raw interface{}, agentID string) interface{} {
	if agentID == "" {
		return raw
	}
	root, ok := raw.(map[string]interface{})
	if !ok {
		return raw
	}
	list, ok := root["agents"].([]interface{})
	if !ok {
		return raw
	}
	matches := make([]interface{}, 0)
	for _, item := range list {
		agent, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		if id, _ := agent["id"].(string); id == agentID {
			matches = append(matches, item)
		}
	}
	return map[string]interface{}{"agents": matches}
}

func okStatus(ok bool) string {
	if ok {
		return "ok"
	}
	return "fail"
}

func printStatusJSON(v interface{}, jsonOutput bool) {
	_ = jsonOutput
	out, _ := json.MarshalIndent(v, "", "  ")
	fmt.Println(string(out))
}
