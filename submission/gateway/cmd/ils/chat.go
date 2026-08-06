package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

// cmdChat implements `ils chat send` and `ils chat request` on top
// of uasclient.Client. The library handles identity, dedupe, and
// the request→reply correlation; the CLI is a thin adapter that
// maps flags onto the Outgoing struct and prints a stable JSON
// envelope on stdout.
//
// Backwards compatibility (legacy ILS shape, preserved):
//
//	chat send    -> JSON body of the Gateway's /chat response
//	chat request -> {"status","accepted","reply"} envelope
//
// Existing scripts that grep "status" / "reply" / "target_connected"
// keep working without change.
func cmdChat(args []string) {
	if len(args) < 1 {
		printChatUsage()
		os.Exit(1)
	}
	switch args[0] {
	case "send":
		cmdChatSend(args[1:])
	case "request":
		cmdChatRequest(args[1:])
	default:
		fmt.Fprintf(os.Stderr, "unknown chat subcommand: %s\n", args[0])
		printChatUsage()
		os.Exit(1)
	}
}

func printChatUsage() {
	bin := os.Args[0]
	fmt.Fprintf(os.Stderr, `Usage:
  %[1]s chat send --target-agent-id <id> --text "ping" [--conv-id conv_...]
  %[1]s chat send --from-agent-id <id> --from <name> --text "reply"
  %[1]s chat request --from-agent-id <id> --target-agent-id <id> --text "ping" [--timeout 60s]

Notes:
  send prints the Gateway delivery JSON.
  request sends an A2A chat message, waits for a matching reply
  on the event WS, and prints {"status","accepted","reply"}.
`, bin)
}

func cmdChatSend(args []string) {
	fs := flag.NewFlagSet("chat send", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	from := fs.String("from", envOr("AGENT_NAME", defaultHostName("-ils-cli")), "sender display name")
	fromAgentID := fs.String("from-agent-id", os.Getenv("AGENT_ID"), "sender agent id for agent replies")
	fromProfile := fs.String("from-profile", "", "load sender agent_id from profile (--from-agent-id wins)")
	targetAgentID := fs.String("target-agent-id", "", "target agent id; empty broadcasts to OB clients")
	text := fs.String("text", "", "message text")
	convID := fs.String("conv-id", "", "conversation id")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}
	if *text == "" && fs.NArg() > 0 {
		*text = strings.Join(fs.Args(), " ")
	}
	if *text == "" {
		fmt.Fprintln(os.Stderr, "chat send requires --text or trailing message text")
		os.Exit(2)
	}

	ident, err := resolveFromProfile(*fromProfile, *fromAgentID, *from)
	if err != nil {
		fmt.Fprintf(os.Stderr, "chat send: %v\n", err)
		os.Exit(2)
	}
	effectiveFrom := ident.from
	if effectiveFrom == "" {
		effectiveFrom = *from
	}
	effectiveFromAgentID := ident.fromAgentID
	if effectiveFromAgentID == "" {
		effectiveFromAgentID = *fromAgentID
	}

	cl := uasclient.New(uasclient.Config{
		GatewayURL:  *gatewayURL,
		AgentName:   "chat-send-onetime",
		AgentType:   "client",
		NoHeartbeat: true,
		Stderr:      os.Stderr,
	})
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	var sr *uasclient.SendResult
	err = cl.RunOnce(ctx, func() error {
		var err error
		sr, err = cl.Send(ctx, uasclient.Outgoing{
			From:          effectiveFrom,
			FromAgentID:   effectiveFromAgentID,
			TargetAgentID: *targetAgentID,
			Text:          *text,
			ConvID:        *convID,
		})
		return err
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "chat send failed: %v\n", err)
		os.Exit(1)
	}
	out, _ := json.Marshal(sr)
	fmt.Println(string(out))
}

func cmdChatRequest(args []string) {
	fs := flag.NewFlagSet("chat request", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	from := fs.String("from", envOr("AGENT_NAME", defaultHostName("-ils-cli")), "sender display name")
	fromAgentID := fs.String("from-agent-id", os.Getenv("AGENT_ID"), "sender agent id for agent replies")
	fromProfile := fs.String("from-profile", "", "load sender agent_id from profile (--from-agent-id wins)")
	targetAgentID := fs.String("target-agent-id", "", "target agent id")
	text := fs.String("text", "", "message text")
	convID := fs.String("conv-id", "", "conversation id; auto-generated if empty")
	timeout := fs.Duration("timeout", 60*time.Second, "wait duration for matching reply")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}
	if *text == "" && fs.NArg() > 0 {
		*text = strings.Join(fs.Args(), " ")
	}
	if *targetAgentID == "" || *text == "" {
		fmt.Fprintln(os.Stderr, "chat request requires --target-agent-id and --text")
		os.Exit(2)
	}
	if *convID == "" {
		*convID = fmt.Sprintf("a2a_%d", time.Now().UnixNano())
	}

	ident, err := resolveFromProfile(*fromProfile, *fromAgentID, *from)
	if err != nil {
		fmt.Fprintf(os.Stderr, "chat request: %v\n", err)
		os.Exit(2)
	}
	effectiveFrom := ident.from
	if effectiveFrom == "" {
		effectiveFrom = *from
	}
	effectiveFromAgentID := ident.fromAgentID
	if effectiveFromAgentID == "" {
		effectiveFromAgentID = *fromAgentID
	}

	cl := uasclient.New(uasclient.Config{
		GatewayURL:  *gatewayURL,
		AgentName:   "chat-request-onetime",
		AgentType:   "client",
		NoHeartbeat: true,
		Stderr:      os.Stderr,
	})
	ctx, cancel := context.WithTimeout(context.Background(), *timeout+5*time.Second)
	defer cancel()

	var (
		accepted *uasclient.SendResult
		reply    uasclient.Event
	)
	err = cl.RunOnce(ctx, func() error {
		sr, err := cl.Send(ctx, uasclient.Outgoing{
			From:          effectiveFrom,
			FromAgentID:   effectiveFromAgentID,
			TargetAgentID: *targetAgentID,
			Text:          *text,
			ConvID:        *convID,
		})
		if err != nil {
			return fmt.Errorf("send: %w", err)
		}
		if !sr.TargetConnected {
			return fmt.Errorf("target %s not connected", *targetAgentID)
		}
		accepted = sr
		evt, err := cl.Request(ctx, uasclient.Outgoing{
			From:          effectiveFrom,
			FromAgentID:   effectiveFromAgentID,
			TargetAgentID: *targetAgentID,
			Text:          *text,
			ConvID:        *convID,
		}, *timeout)
		if err != nil {
			return err
		}
		reply = evt
		return nil
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "chat request failed: %v\n", err)
		os.Exit(1)
	}
	out := map[string]interface{}{
		"status":   "ok",
		"accepted": accepted,
		"reply":    reply,
	}
	enc, _ := json.Marshal(out)
	fmt.Println(string(enc))
}

func defaultHostName(suffix string) string {
	host, _ := os.Hostname()
	if host == "" {
		host = "unknown"
	}
	return host + suffix
}
