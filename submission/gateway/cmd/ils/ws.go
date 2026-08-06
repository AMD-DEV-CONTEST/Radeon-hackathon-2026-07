package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

// cmdWS implements `ils ws` on top of internal/uasclient. Behavior
// preserved from the legacy file:
//
//   - Register as an agent, connect to the Gateway, complete the
//     ready handshake.
//   - Receive chat events addressed to this agent; print each as a
//     NDJSON line on stdout.
//   - Auto-ack every accepted event.
//   - Read NDJSON reply lines from stdin, POST each as a chat
//     reply to the Gateway, preserving the original conv_id.
//
// What changed (and why this is now considered "production-ready"
// per the hardening spec):
//
//   - The reconnect loop, the dedupe of replayed events, the
//     last_event_id cursor, and the auth + register handshake
//     all live in uasclient and are reused across all three
//     client commands. The CLI here is a thin adapter.
//   - Stop conditions: SIGINT/SIGTERM. Pressing Ctrl-C in a
//     terminal cancels the context, the connect loop drains
//     pending work, and the process exits cleanly.
func cmdWS(args []string) {
	fs := flag.NewFlagSet("ws", flag.ExitOnError)
	gatewayURL := fs.String("gateway", envOr("GATEWAY_URL", "wss://api.upser.pro"), "Gateway WS URL")
	orchestratorURL := fs.String("orchestrator", envOr("ORCHESTRATOR_URL", "http://111.228.42.18:8000"), "Orchestrator URL")
	agentID := fs.String("agent-id", os.Getenv("AGENT_ID"), "Agent ID (required)")
	agentName := fs.String("agent-name", envOr("AGENT_NAME", "ils-ws"), "Agent display name")
	agentType := fs.String("agent-type", envOr("AGENT_TYPE", "hermes"), "Agent runtime type")
	password := fs.String("password", os.Getenv("GATEWAY_PASSWORD"), "Gateway password")
	noHeartbeat := fs.Bool("no-heartbeat", false, "skip orchestrator heartbeat (for ephemeral clients)")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "flag parse: %v\n", err)
		os.Exit(1)
	}
	if *agentID == "" {
		fmt.Fprintln(os.Stderr, "--agent-id or AGENT_ID is required")
		os.Exit(1)
	}
	if *password == "" {
		fmt.Fprintln(os.Stderr, "--password or GATEWAY_PASSWORD is required")
		os.Exit(1)
	}

	cfg := uasclient.Config{
		GatewayURL:      *gatewayURL,
		OrchestratorURL: *orchestratorURL,
		AgentID:         *agentID,
		AgentName:       *agentName,
		AgentType:       *agentType,
		Password:        *password,
		NoHeartbeat:     *noHeartbeat,
		Stderr:          os.Stderr,
	}

	// OnEvent: print the raw NDJSON of the event to stdout, but
	// only if it's addressed to us (matching the legacy ws.go:225
	// filter). The library has already deduped by event_id and
	// will auto-ack; we just need to deliver to the caller.
	cfg.OnEvent = func(ctx context.Context, e uasclient.Event) error {
		if e.TargetAgentID != "" && e.TargetAgentID != *agentID {
			return nil
		}
		raw, _ := json.Marshal(e)
		fmt.Println(string(raw))
		return nil
	}

	// OnReady: feed replayed events back into the same print
	// path. The library's read loop already dedupes + acks
	// replayed events; here we just print them.
	cfg.OnReady = func(ctx context.Context) error {
		// The library handles replay internally via its own
		// cursor store; nothing to do here for now. The hook
		// exists so a future "send a presence beacon on
		// reconnect" feature has a place to live without
		// touching the library.
		return nil
	}

	cl := uasclient.New(cfg)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// Stdin → reply goroutine. Mirrors legacy ws.go:249-295: each
	// line is a JSON object; we read {text, conv_id} and POST
	// /chat. Conv_id is the only required field for the
	// server-side correlation; text is the reply body.
	go stdinReplyLoop(ctx, cl, *agentID, *agentName)

	if err := cl.Connect(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "[ws] connect: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintln(os.Stderr, "[ws] exited")
}

func stdinReplyLoop(ctx context.Context, cl *uasclient.Client, agentID, agentName string) {
	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		if ctx.Err() != nil {
			return
		}
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var in map[string]interface{}
		if err := json.Unmarshal([]byte(line), &in); err != nil {
			fmt.Fprintf(os.Stderr, "[ws] stdin parse: %v\n", err)
			continue
		}
		text, _ := in["text"].(string)
		if text == "" {
			text, _ = in["reply"].(string)
		}
		convID, _ := in["conv_id"].(string)
		if err := cl.Reply(ctx, "", uasclient.Outgoing{
			From:        agentName,
			FromAgentID: agentID,
			Text:        text,
			ConvID:      convID,
		}); err != nil {
			fmt.Fprintf(os.Stderr, "[ws] reply post: %v\n", err)
			continue
		}
		fmt.Fprintf(os.Stderr, "[ws] reply sent conv_id=%s\n", convID)
	}
	if err := scanner.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "[ws] stdin error: %v\n", err)
	}
}
