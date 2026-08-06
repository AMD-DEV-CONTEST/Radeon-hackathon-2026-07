package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"strings"
)

// runProfileCmd implements `ils profile <subcommand>`.
// Subcommands: list, set, get, rm. Writes human-readable text by
// default; --json switches to NDJSON where applicable.
//
// runProfileCmd takes stdout/stderr as parameters so tests can capture
// output without touching os.Stdout directly.
func runProfileCmd(args []string, stdout, stderr io.Writer) error {
	if len(args) < 1 {
		return fmt.Errorf("profile requires a subcommand: list|set|get|rm")
	}
	switch args[0] {
	case "list":
		return profileCmdList(args[1:], stdout)
	case "set":
		return profileCmdSet(args[1:], stdout)
	case "get":
		return profileCmdGet(args[1:], stdout)
	case "rm":
		return profileCmdRm(args[1:], stdout)
	default:
		return fmt.Errorf("unknown profile subcommand: %s", args[0])
	}
}

func profileCmdList(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("profile list", flag.ContinueOnError)
	asJSON := fs.Bool("json", false, "output NDJSON")
	if err := fs.Parse(args); err != nil {
		return err
	}
	list, err := profileList()
	if err != nil {
		return err
	}
	if *asJSON {
		for _, p := range list {
			b, _ := json.Marshal(p)
			fmt.Fprintln(stdout, string(b))
		}
		return nil
	}
	fmt.Fprintf(stdout, "%-12s %-20s %s\n", "NAME", "AGENT_ID", "INBOX")
	for _, p := range list {
		inbox := p.InboxPath
		if inbox == "" {
			inbox = "(default)"
		}
		fmt.Fprintf(stdout, "%-12s %-20s %s\n", p.Name, p.AgentID, inbox)
	}
	return nil
}

func profileCmdSet(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("profile set", flag.ContinueOnError)
	agentID := fs.String("agent-id", "", "agent id (required)")
	inboxPath := fs.String("inbox-path", "", "override inbox.ndjson path")
	statePath := fs.String("state-path", "", "override state dir path")
	logPath := fs.String("log-path", "", "override daemon.log path")
	// Go's flag package stops parsing at the first non-flag argument, so
	// `profile set x1 --agent-id x1` would miss the flag. Reorder so
	// flags come first, then the positional name — accepting both
	// `set x1 --agent-id x1` and `set --agent-id x1 x1`.
	flags, positional := splitFlagsAndPositional(args)
	if err := fs.Parse(flags); err != nil {
		return err
	}
	if len(positional) < 1 {
		return fmt.Errorf("profile set requires a name")
	}
	name := positional[0]
	if *agentID == "" {
		return fmt.Errorf("profile set requires --agent-id")
	}
	if err := profileSet(Profile{
		Name:      name,
		AgentID:   *agentID,
		InboxPath: *inboxPath,
		StatePath: *statePath,
		LogPath:   *logPath,
	}); err != nil {
		return err
	}
	fmt.Fprintf(stdout, "profile %q set (agent_id=%s)\n", name, *agentID)
	return nil
}

func profileCmdGet(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("profile get", flag.ContinueOnError)
	asJSON := fs.Bool("json", false, "output NDJSON")
	flags, positional := splitFlagsAndPositional(args)
	if err := fs.Parse(flags); err != nil {
		return err
	}
	if len(positional) < 1 {
		return fmt.Errorf("profile get requires a name")
	}
	p, err := profileGet(positional[0])
	if err != nil {
		return err
	}
	if *asJSON {
		b, _ := json.Marshal(p)
		fmt.Fprintln(stdout, string(b))
		return nil
	}
	fmt.Fprintf(stdout, "name:       %s\n", p.Name)
	fmt.Fprintf(stdout, "agent_id:   %s\n", p.AgentID)
	fmt.Fprintf(stdout, "inbox_path: %s\n", p.InboxPath)
	fmt.Fprintf(stdout, "state_path: %s\n", p.StatePath)
	fmt.Fprintf(stdout, "log_path:   %s\n", p.LogPath)
	return nil
}

func profileCmdRm(args []string, stdout io.Writer) error {
	fs := flag.NewFlagSet("profile rm", flag.ContinueOnError)
	flags, positional := splitFlagsAndPositional(args)
	if err := fs.Parse(flags); err != nil {
		return err
	}
	if len(positional) < 1 {
		return fmt.Errorf("profile rm requires a name")
	}
	name := positional[0]
	if err := profileRm(name); err != nil {
		return err
	}
	fmt.Fprintf(stdout, "profile %q removed (runtime files NOT deleted)\n", name)
	return nil
}

// splitFlagsAndPositional separates a Go-style arg slice into flag args
// (each flag kept together with its value token) and positional args.
//
// Heuristic: a token starting with "-" is a flag. The NEXT token is its
// value UNLESS (a) the flag already contains "=", (b) the next token
// itself starts with "-", or (c) the flag is a known boolean (--json)
// that takes no value. This correctly groups "--agent-id x1" but
// leaves "--json" without consuming the following positional.
func splitFlagsAndPositional(args []string) (flags, positional []string) {
	boolFlags := map[string]bool{"--json": true}
	flags = []string{}
	positional = []string{}
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--" {
			positional = append(positional, args[i+1:]...)
			break
		}
		if len(a) > 0 && a[0] == '-' && a != "-" {
			flags = append(flags, a)
			if !strings.Contains(a, "=") && !boolFlags[a] && i+1 < len(args) {
				next := args[i+1]
				if !(len(next) > 0 && next[0] == '-') {
					flags = append(flags, next)
					i++
				}
			}
			continue
		}
		positional = append(positional, a)
	}
	return flags, positional
}

func printProfileUsage(w io.Writer) {
	fmt.Fprintf(w, `Usage:
  ils profile list [--json]
  ils profile set <name> --agent-id <id> [--inbox-path ...] [--state-path ...] [--log-path ...]
  ils profile get <name> [--json]
  ils profile rm <name>
`)
}
