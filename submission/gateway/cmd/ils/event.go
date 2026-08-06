package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync/atomic"
	"time"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

// cmdEvent implements the three event-related subcommands:
//
//	event consume chat — receive chat events as NDJSON on stdout
//	event status       — print /events/status (one-shot, no WS)
//	event schema chat  — print the schema for chat events
//
// `event consume` is now a thin adapter on uasclient.Client: the
// library handles register, dial, handshake, dedupe, and ack. The
// CLI supplies a max-events / timeout stop condition so that
// smoke tests and CI runs can exit without manually killing the
// process.
func cmdEvent(args []string) {
	if len(args) < 1 {
		printEventUsage()
		os.Exit(1)
	}
	switch args[0] {
	case "consume":
		cmdEventConsume(args[1:])
	case "status":
		cmdEventStatus(args[1:])
	case "schema":
		cmdEventSchema(args[1:])
	default:
		fmt.Fprintf(os.Stderr, "unknown event subcommand: %s\n", args[0])
		printEventUsage()
		os.Exit(1)
	}
}

func printEventUsage() {
	bin := os.Args[0]
	fmt.Fprintf(os.Stderr, `Usage:
  %[1]s event consume chat [--max-events N] [--timeout 30s]
  %[1]s event status [--json]
  %[1]s event schema chat

Notes:
  stderr carries status; stdout is reserved for NDJSON events.
  Reconnect + dedupe + replay are now handled inside the uasclient
  library; this command is a thin adapter.
`, bin)
}

func cmdEventConsume(args []string) {
	if len(args) < 1 {
		printEventUsage()
		os.Exit(1)
	}
	eventKey := args[0]
	if eventKey != "chat" {
		fmt.Fprintf(os.Stderr, "unsupported event key: %s\n", eventKey)
		os.Exit(2)
	}

	fs := flag.NewFlagSet("event consume chat", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway websocket base URL")
	agentID := fs.String("agent-id", os.Getenv("AGENT_ID"), "only print chat events for this agent id (empty = all)")
	maxEvents := fs.Int("max-events", 0, "exit after N matching events; 0 means unlimited")
	timeout := fs.Duration("timeout", 0, "exit after duration; 0 means unlimited")
	if err := fs.Parse(args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}

	// Stop conditions: max-events or timeout, whichever comes first.
	// We translate these into a context that the library's connect
	// loop will honor.
	ctx := context.Background()
	var cancel context.CancelFunc
	if *timeout > 0 {
		ctx, cancel = context.WithTimeout(ctx, *timeout)
		defer cancel()
	}
	if *maxEvents > 0 {
		ctx, cancel = context.WithCancel(ctx)
		defer cancel()
		go func() {
			var counter int64
			// We can't intercept the library's count, so we
			// just sleep and let the timeout fire. This is a
			// known limitation; for production long-running
			// consumers, --max-events is a CI/smoke aid, not
			// a hot loop. A future revision can plumb a
			// counter through the OnEvent hook.
			_ = counter
			for {
				select {
				case <-ctx.Done():
					return
				case <-time.After(time.Hour):
				}
			}
		}()
	}

	cfg := uasclient.Config{
		GatewayURL:  *gatewayURL,
		AgentID:     *agentID, // empty = client mode
		AgentName:   "ils-event-consumer",
		AgentType:   "client",
		NoHeartbeat: true,
		Stderr:      os.Stderr,
	}

	// OnEvent: print raw NDJSON; the library has already deduped
	// by event_id and will auto-ack. If max-events is set, cancel
	// the context after the Nth event so the connect loop exits.
	var seen int64
	cfg.OnEvent = func(ctx context.Context, e uasclient.Event) error {
		if *agentID != "" {
			if e.FromAgentID != *agentID && e.TargetAgentID != *agentID {
				return nil
			}
		}
		raw, _ := json.Marshal(e)
		fmt.Println(string(raw))
		if *maxEvents > 0 {
			if atomic.AddInt64(&seen, 1) >= int64(*maxEvents) {
				if cancel != nil {
					cancel()
				}
			}
		}
		return nil
	}

	cl := uasclient.New(cfg)
	if err := cl.Connect(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "[event] connect: %v\n", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "[event] exited received=%d\n", atomic.LoadInt64(&seen))
}

func cmdEventStatus(args []string) {
	fs := flag.NewFlagSet("event status", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	jsonOutput := fs.Bool("json", true, "print JSON output")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}

	// One-shot HTTP GET; no WS involved. The library's HTTP base
	// converter is reused via this same gatewayURL, keeping the
	// env-var + default pattern consistent with the rest of the
	// CLI.
	base := httpBase(*gatewayURL)
	req, err := http.NewRequest("GET", base+"/events/status", nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "event status: %v\n", err)
		os.Exit(1)
	}
	resp, err := (&http.Client{Timeout: 10 * time.Second}).Do(req)
	if err != nil {
		fmt.Fprintf(os.Stderr, "event status failed: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()
	out, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Fprintf(os.Stderr, "event status read failed: %v\n", err)
		os.Exit(1)
	}
	if resp.StatusCode >= 300 {
		fmt.Fprintf(os.Stderr, "event status returned HTTP %d: %s\n", resp.StatusCode, strings.TrimSpace(string(out)))
		os.Exit(1)
	}
	_ = *jsonOutput
	fmt.Println(string(out))
}

func cmdEventSchema(args []string) {
	if len(args) < 1 || args[0] != "chat" {
		fmt.Fprintln(os.Stderr, "event schema only supports: chat")
		os.Exit(2)
	}
	schema := map[string]interface{}{
		"event_key":  "chat",
		"event_type": "chat.message",
		"fields": []map[string]interface{}{
			{"name": "event_id", "type": "string", "required": true, "description": "unique event id; safe for ack and replay"},
			{"name": "event_type", "type": "string", "required": true, "description": "chat.message"},
			{"name": "message_id", "type": "string", "required": true, "description": "stable chat message id"},
			{"name": "conversation_id", "type": "string", "required": true, "description": "conversation id; mirrors conv_id for legacy clients"},
			{"name": "conv_id", "type": "string", "required": true, "description": "legacy conversation id"},
			{"name": "from", "type": "string", "required": false, "description": "sender display name"},
			{"name": "from_agent_id", "type": "string", "required": false, "description": "sender ILS Daemon agent id"},
			{"name": "target_agent_id", "type": "string", "required": false, "description": "target ILS Daemon agent id; empty means OB clients"},
			{"name": "text", "type": "string", "required": true, "description": "chat text"},
			{"name": "ts", "type": "string", "required": true, "description": "UTC RFC3339 timestamp"},
			{"name": "type", "type": "string", "required": true, "description": "legacy event type, always chat"},
		},
	}
	out, _ := json.MarshalIndent(schema, "", "  ")
	fmt.Println(string(out))
}

// httpBase is a local copy of uasclient's URL→HTTP converter.
// It can't be exported from the library without widening its
// API surface, and this is the only place in the ils CLI that
// needs the converter outside a uasclient.Client.
func httpBase(gatewayURL string) string {
	base := gatewayURL
	if strings.HasPrefix(base, "ws://") {
		base = "http://" + strings.TrimPrefix(base, "ws://")
	} else if strings.HasPrefix(base, "wss://") {
		base = "https://" + strings.TrimPrefix(base, "wss://")
	}
	return strings.TrimRight(base, "/")
}
