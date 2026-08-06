package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
)

// cmdLocalDaemon implements `ils local daemon`. It resolves profiles
// (from profiles.json or inline --profile/--profiles + --agent-id),
// builds daemonProfile records with resolved runtime paths, and runs
// runLocalDaemon. No GATEWAY_PASSWORD, no task dispatch.
func cmdLocalDaemon(args []string) {
	fs := flag.NewFlagSet("local daemon", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	baseFlag := fs.String("base", "", "runtime base dir (default: ILS_RUNTIME_HOME or ILS_HOME)")
	profileSingle := fs.String("profile", "", "single profile name")
	profilesCSV := fs.String("profiles", "", "comma-separated profile names")
	inlineAgentID := fs.String("agent-id", "", "inline agent_id for --profile (no profiles.json needed)")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}

	if *profileSingle == "" && *profilesCSV == "" {
		fmt.Fprintln(os.Stderr, "local daemon requires --profile <name> or --profiles x1,c1,z1")
		os.Exit(2)
	}
	if *profileSingle != "" && *profilesCSV != "" {
		fmt.Fprintln(os.Stderr, "--profile and --profiles are mutually exclusive")
		os.Exit(2)
	}

	var names []string
	if *profileSingle != "" {
		names = []string{*profileSingle}
	} else {
		for _, n := range strings.Split(*profilesCSV, ",") {
			if n = strings.TrimSpace(n); n != "" {
				names = append(names, n)
			}
		}
	}

	base := runtimeBase(*baseFlag)
	if base == "" {
		base = ilsHome()
	}

	var profiles []daemonProfile
	for _, name := range names {
		p, err := profileGet(name)
		if err != nil {
			// Allow inline single-profile without profiles.json.
			if *profileSingle != "" && *inlineAgentID != "" && len(names) == 1 {
				p = Profile{Name: name, AgentID: *inlineAgentID}
			} else {
				fmt.Fprintf(os.Stderr, "profile %q: %v\n", name, err)
				fmt.Fprintln(os.Stderr, "(hint: run 'ils profile set <name> --agent-id <id>' first, or use --profile <name> --agent-id <id> inline)")
				os.Exit(1)
			}
		}
		pp := profilePaths(base, p.Name)
		profiles = append(profiles, daemonProfile{
			Name:               p.Name,
			AgentID:            p.AgentID,
			InboxPath:          firstNonEmpty(p.InboxPath, pp.inbox),
			UasclientWorkspace: firstNonEmpty(p.StatePath, pp.uasclientWorkspace),
			LockPath:           pp.lockFile,
		})
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	fmt.Fprintf(os.Stderr, "[local] starting %d profile(s): %s\n", len(profiles), joinNames(profiles))
	if err := runLocalDaemon(ctx, localDaemonOptions{
		GatewayURL:  *gatewayURL,
		Profiles:    profiles,
		NoHeartbeat: true,
		Stderr:      os.Stderr,
	}); err != nil {
		fmt.Fprintf(os.Stderr, "[local] daemon error: %v\n", err)
		os.Exit(1)
	}
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

func joinNames(ps []daemonProfile) string {
	var ns []string
	for _, p := range ps {
		ns = append(ns, p.Name+"("+p.AgentID+")")
	}
	return strings.Join(ns, ", ")
}
