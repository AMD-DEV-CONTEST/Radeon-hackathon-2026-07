package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

type inboxWatchOptions struct {
	AgentID         string
	GatewayURL      string
	Format          string
	Once            bool
	AgentName       string
	MaxEvents       int
	NoHeartbeat     bool
	DedupeWorkspace string
	Stderr          io.Writer
}

type inboxLine struct {
	TS        string `json:"ts,omitempty"`
	From      string `json:"from,omitempty"`
	To        string `json:"to,omitempty"`
	ConvID    string `json:"conv_id,omitempty"`
	MessageID string `json:"message_id,omitempty"`
	Text      string `json:"text,omitempty"`
}

func cmdInbox(args []string) {
	if len(args) < 1 {
		printInboxUsage(os.Stderr)
		os.Exit(1)
	}
		switch args[0] {
		case "watch":
			cmdInboxWatch(args[1:])
		case "read":
			cmdInboxRead(args[1:])
		case "tail":
			cmdInboxTail(args[1:])
		default:
		fmt.Fprintf(os.Stderr, "unknown inbox subcommand: %s\n", args[0])
		printInboxUsage(os.Stderr)
		os.Exit(1)
	}
}

func printInboxUsage(w io.Writer) {
	bin := os.Args[0]
	fmt.Fprintf(w, `Usage:
  %[1]s inbox watch --agent-id <id> [--gateway ws://...] [--format jsonl|text] [--once]

Examples:
  %[1]s inbox watch --agent-id=x1 --format=text
  %[1]s inbox watch --agent-id=x1 --once
`, bin)
}

func cmdInboxWatch(args []string) {
	fs := flag.NewFlagSet("inbox watch", flag.ExitOnError)
	agentID := fs.String("agent-id", os.Getenv("AGENT_ID"), "logical recipient agent id to watch")
	gatewayURL := fs.String("gateway", envOr("GATEWAY_URL", "wss://api.upser.pro"), "Gateway WS URL")
	format := fs.String("format", "jsonl", "output format: jsonl or text")
	once := fs.Bool("once", false, "exit after the first message")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}
	if *agentID == "" {
		fmt.Fprintln(os.Stderr, "inbox watch requires --agent-id or AGENT_ID")
		os.Exit(2)
	}
	if *format != "jsonl" && *format != "text" {
		fmt.Fprintln(os.Stderr, "--format must be jsonl or text")
		os.Exit(2)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	err := runInboxWatch(ctx, inboxWatchOptions{
		AgentID:     *agentID,
		GatewayURL:  *gatewayURL,
		Format:      *format,
		Once:        *once,
		AgentName:   "ils-inbox-" + *agentID,
		NoHeartbeat: true,
		Stderr:      os.Stderr,
	}, os.Stdout)
	if err != nil {
		fmt.Fprintf(os.Stderr, "inbox watch failed: %v\n", err)
		os.Exit(1)
	}
}

// profileClientOptions configures a single client-mode subscription for
// `ils local daemon`. The uasclient library handles login/register/dial/
// handshake/reconnect/dedupe/replay/ack; the caller supplies the per-event
// handler and the workspace for per-profile dedupe+cursor isolation.
type profileClientOptions struct {
	GatewayURL  string
	AgentID     string // logical agent_id to register as client
	AgentName   string
	Workspace   string // per-profile dir for uasclient dedupe+cursor
	NoHeartbeat bool
	Stderr      io.Writer
	OnEvent     func(ctx context.Context, e uasclient.Event) error
}

// runProfileClient builds a client-mode uasclient.Client and runs its
// Connect loop until ctx is cancelled. Returns nil on graceful shutdown.
func runProfileClient(ctx context.Context, opts profileClientOptions) error {
	if opts.AgentID == "" {
		return fmt.Errorf("agent id is required")
	}
	if opts.GatewayURL == "" {
		opts.GatewayURL = envOr("GATEWAY_URL", "wss://api.upser.pro")
	}
	if opts.AgentName == "" {
		opts.AgentName = "ils-profile-" + opts.AgentID
	}
	if opts.Stderr == nil {
		opts.Stderr = io.Discard
	}
	cl := uasclient.New(uasclient.Config{
		GatewayURL:    opts.GatewayURL,
		AgentName:     opts.AgentName,
		ClientAgentID: opts.AgentID,
		NoHeartbeat:   opts.NoHeartbeat,
		Workspace:     opts.Workspace,
		Stderr:        opts.Stderr,
	})
	if opts.OnEvent != nil {
		cl.Subscribe(opts.OnEvent)
	}
	// When the parent context is cancelled (SIGINT, test timeout, etc.),
	// close the WS connection so Connect unblocks. Otherwise Connect's
	// readLoop blocks on ReadMessage indefinitely even after ctx fires,
	// because gorilla/websocket ReadMessage is not context-aware.
	go func() {
		<-ctx.Done()
		_ = cl.Close()
	}()
	return cl.Connect(ctx)
}

func runInboxWatch(ctx context.Context, opts inboxWatchOptions, out io.Writer) error {
	if opts.AgentID == "" {
		return fmt.Errorf("agent id is required")
	}
	if opts.GatewayURL == "" {
		opts.GatewayURL = envOr("GATEWAY_URL", "wss://api.upser.pro")
	}
	if opts.Format == "" {
		opts.Format = "jsonl"
	}
	if opts.AgentName == "" {
		opts.AgentName = "ils-inbox-" + opts.AgentID
	}
	if opts.Stderr == nil {
		opts.Stderr = io.Discard
	}

	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	seen := 0
	done := make(chan struct{})
	var doneOnce sync.Once
	limited := opts.Once || opts.MaxEvents > 0
	cfg := uasclient.Config{
		GatewayURL:    opts.GatewayURL,
		AgentName:     opts.AgentName,
		ClientAgentID: opts.AgentID,
		NoHeartbeat:   opts.NoHeartbeat,
		Workspace:     opts.DedupeWorkspace,
		Stderr:        opts.Stderr,
	}
	cl := uasclient.New(cfg)
	cl.Subscribe(func(eventCtx context.Context, e uasclient.Event) error {
		if e.TargetAgentID != "" && e.TargetAgentID != opts.AgentID {
			return nil
		}
		line := eventToInboxLine(e, opts.AgentID)
		if err := writeInboxLine(out, opts.Format, line); err != nil {
			return err
		}
		seen++
		if opts.Once || (opts.MaxEvents > 0 && seen >= opts.MaxEvents) {
			doneOnce.Do(func() {
				close(done)
				cancel()
				go func() {
					_ = cl.Close()
				}()
			})
		}
		return nil
	})

	if !limited {
		return cl.Connect(ctx)
	}

	errCh := make(chan error, 1)
	go func() {
		errCh <- cl.Connect(ctx)
	}()
	select {
	case <-done:
		_ = cl.Close()
		select {
		case <-errCh:
		case <-time.After(2 * time.Second):
		}
		return nil
	case err := <-errCh:
		return err
	case <-ctx.Done():
		_ = cl.Close()
		select {
		case <-errCh:
		case <-time.After(2 * time.Second):
		}
		return nil
	}
}

func eventToInboxLine(e uasclient.Event, agentID string) inboxLine {
	to := e.TargetAgentID
	if to == "" {
		to = agentID
	}
	from := e.FromAgentID
	if from == "" {
		from = e.From
	}
	convID := e.ConvID
	if convID == "" {
		convID = e.ConversationID
	}
	ts := e.Timestamp
	if ts == "" {
		ts = time.Now().UTC().Format(time.RFC3339)
	}
	return inboxLine{
		TS:        ts,
		From:      from,
		To:        to,
		ConvID:    convID,
		MessageID: e.MessageID,
		Text:      e.Text,
	}
}

func writeInboxLine(out io.Writer, format string, line inboxLine) error {
	if format == "text" {
		_, err := fmt.Fprintf(out, "[%s] %s->%s: %s\n", line.TS, line.From, line.To, line.Text)
		return err
	}
	raw, err := json.Marshal(line)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, string(raw))
	return err
}
