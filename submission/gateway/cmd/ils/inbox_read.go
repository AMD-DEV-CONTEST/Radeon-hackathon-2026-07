package main

import (
	"bufio"
	"context"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const inboxReadDefaultLines = 50

// inboxReadOptions configures `ils inbox read`.
type inboxReadOptions struct {
	Profile string
	Lines   int
	All     bool
	JSON    bool
}

// inboxTailOptions configures `ils inbox tail`.
type inboxTailOptions struct {
	Profile string
	Lines   int
	Follow  bool
	JSON    bool
}

func resolveInboxPath(profile string) (string, error) {
	p, err := profileGet(profile)
	if err != nil {
		return "", err
	}
	if p.InboxPath != "" {
		return p.InboxPath, nil
	}
	return profilePaths(runtimeBase(ilsHome()), p.Name).inbox, nil
}

// readLastNLines reads the whole file via bufio.Scanner (constant memory)
// and returns the last n non-empty lines. n <= 0 → all lines.
func readLastNLines(path string, n int) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()
	var all []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	for sc.Scan() {
		if s := sc.Text(); s != "" {
			all = append(all, s)
		}
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	if n <= 0 || n >= len(all) {
		return all, nil
	}
	return all[len(all)-n:], nil
}

func runInboxRead(opts inboxReadOptions, out io.Writer) error {
	if opts.All && opts.Lines > 0 {
		return fmt.Errorf("--lines and --all are mutually exclusive")
	}
	inboxPath, err := resolveInboxPath(opts.Profile)
	if err != nil {
		return err
	}
	n := opts.Lines
	if !opts.All && n == 0 {
		n = inboxReadDefaultLines
	}
	lines, err := readLastNLines(inboxPath, n)
	if err != nil {
		return err
	}
	for _, l := range lines {
		fmt.Fprintln(out, l)
	}
	return nil
}

func runInboxTail(ctx context.Context, opts inboxTailOptions, out io.Writer) error {
	inboxPath, err := resolveInboxPath(opts.Profile)
	if err != nil {
		return err
	}
	n := opts.Lines
	if n <= 0 {
		n = 10
	}
	lines, err := readLastNLines(inboxPath, n)
	if err != nil {
		return err
	}
	for _, l := range lines {
		fmt.Fprintln(out, l)
	}
	if !opts.Follow {
		return nil
	}
	// Follow: poll for new lines appended after the current size.
	info, _ := os.Stat(inboxPath)
	var offset int64
	if info != nil {
		offset = info.Size()
	}
	t := time.NewTicker(250 * time.Millisecond)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-t.C:
			f, err := os.Open(inboxPath)
			if err != nil {
				continue
			}
			if _, err := f.Seek(offset, 0); err != nil {
				f.Close()
				continue
			}
			sc := bufio.NewScanner(f)
			sc.Buffer(make([]byte, 64*1024), 1024*1024)
			for sc.Scan() {
				if s := sc.Text(); s != "" {
					fmt.Fprintln(out, s)
				}
			}
			if newInfo, err := f.Stat(); err == nil {
				offset = newInfo.Size()
			}
			f.Close()
		}
	}
}

// cmdInboxRead parses flags and calls runInboxRead.
func cmdInboxRead(args []string) {
	fs := flag.NewFlagSet("inbox read", flag.ExitOnError)
	profile := fs.String("profile", "", "profile name (preferred)")
	lines := fs.Int("lines", 0, "last N lines (default 50; 0 means default)")
	all := fs.Bool("all", false, "print all lines (overrides --lines)")
	_ = fs.Bool("json", false, "pass through NDJSON (no reformatting)")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse: %v\n", err)
		os.Exit(2)
	}
	name := *profile
	if name == "" {
		if fs.NArg() < 1 {
			fmt.Fprintln(os.Stderr, "inbox read requires --profile <name> or a positional profile name")
			os.Exit(2)
		}
		name = fs.Arg(0)
	}
	if err := runInboxRead(inboxReadOptions{Profile: name, Lines: *lines, All: *all, JSON: false}, os.Stdout); err != nil {
		fmt.Fprintf(os.Stderr, "inbox read: %v\n", err)
		os.Exit(1)
	}
}

// cmdInboxTail parses flags and calls runInboxTail.
func cmdInboxTail(args []string) {
	fs := flag.NewFlagSet("inbox tail", flag.ExitOnError)
	profile := fs.String("profile", "", "profile name (preferred)")
	lines := fs.Int("lines", 10, "last N lines (default 10)")
	follow := fs.Bool("follow", false, "block and stream new lines")
	_ = fs.Bool("json", false, "pass through NDJSON")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse: %v\n", err)
		os.Exit(2)
	}
	name := *profile
	if name == "" {
		if fs.NArg() < 1 {
			fmt.Fprintln(os.Stderr, "inbox tail requires --profile <name> or a positional profile name")
			os.Exit(2)
		}
		name = fs.Arg(0)
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := runInboxTail(ctx, inboxTailOptions{Profile: name, Lines: *lines, Follow: *follow, JSON: false}, os.Stdout); err != nil {
		fmt.Fprintf(os.Stderr, "inbox tail: %v\n", err)
		os.Exit(1)
	}
}
