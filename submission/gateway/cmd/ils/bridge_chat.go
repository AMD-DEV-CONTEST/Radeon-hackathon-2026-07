package main

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
	"unicode/utf16"
)

// ── Bridge message formats ────────────────────────────────────

// bridgeInboxMsg is written by daemon to inbox.ndjson for each incoming chat.
type bridgeInboxMsg struct {
	EventID     string `json:"event_id"`
	From        string `json:"from"`
	FromAgentID string `json:"from_agent_id,omitempty"`
	ConvID      string `json:"conv_id"`
	Text    string `json:"text"`
	Ts      string `json:"ts"`
}

// bridgeOutboxMsg is written by agent to outbox.ndjson as a reply.
// Daemon reads new lines and sends via sendGatewayChatReply.
// TargetAgentID must be set — empty target replies are dropped (Feishu bot model).
type bridgeOutboxMsg struct {
	EventID       string `json:"event_id"`
	Reply         string `json:"reply"`
	ConvID        string `json:"conv_id"`
	TargetAgentID string `json:"target_agent_id,omitempty"`
	Ts      string `json:"ts"`
}

// ── Inbox (daemon writes, agent reads) ────────────────────────

var inboxMu sync.Mutex

func writeBridgeInbox(dir, eventID, from, fromAgentID, convID, text string) error {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("mkdir bridge dir: %w", err)
	}
	path := filepath.Join(dir, "inbox.ndjson")
	msg := bridgeInboxMsg{
		EventID:     eventID,
		From:        from,
		FromAgentID: fromAgentID,
		ConvID:      convID,
		Text:    text,
		Ts:      time.Now().UTC().Format(time.RFC3339),
	}
	b, _ := json.Marshal(msg)

	// Write to persistent ndjson file
	inboxMu.Lock()
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		inboxMu.Unlock()
		return fmt.Errorf("open inbox: %w", err)
	}
	if _, err := f.Write(append(b, '\n')); err != nil {
		f.Close()
		inboxMu.Unlock()
		return fmt.Errorf("write inbox: %w", err)
	}
	f.Close()
	inboxMu.Unlock()

	// Also push to inbox socket (instant notification, non-blocking)
	broadcastToInboxSocket(b)

	return nil
}

// ── Inbox socket (named pipe equivalent — instant notification) ──
//
// Instead of just writing to a regular file (which requires polling),
// the daemon also broadcasts each message to all connected socket clients.
// This is the UAS bridge pipe: the agent opens the socket, blocks on
// readline, and gets every message instantly — zero polling, zero scripts.
//
// On Linux: Unix domain socket at {BridgeDir}/inbox.sock
// On Windows: TCP socket on localhost:{port}, port written to {BridgeDir}/inbox.port
// Fallback for old Windows: existing ndjson + Get-Content -Wait

type inboxSocketState struct {
	mu       sync.Mutex
	listener net.Listener
	clients  map[net.Conn]bool
	dir      string
	started  bool
}

var inboxSocket = &inboxSocketState{
	clients: make(map[net.Conn]bool),
}

// ensureInboxSocket creates a socket listener in the bridge dir.
// On Linux: Unix domain socket at {BridgeDir}/inbox.sock
// On Windows: TCP socket on 127.0.0.1, port written to {BridgeDir}/inbox.port
// Safe to call multiple times (idempotent after first call).
func ensureInboxSocket(dir string) {
	inboxSocket.mu.Lock()
	defer inboxSocket.mu.Unlock()
	if inboxSocket.started {
		return
	}

	sockPath := filepath.Join(dir, "inbox.sock")

	// Remove stale socket file from previous run
	os.Remove(sockPath)

	// Try Unix socket first (Linux / modern Windows with Go 1.21+)
	listener, err := net.Listen("unix", sockPath)
	if err != nil {
		// Fall back to TCP on localhost (Windows compat)
		listener, err = net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			slog.Warn("bridge inbox socket not available (unix+tcp)", "err", err)
			return
		}
		port := listener.Addr().(*net.TCPAddr).Port
		portPath := filepath.Join(dir, "inbox.port")
		os.WriteFile(portPath, []byte(fmt.Sprintf("%d", port)), 0644)
		slog.Info("bridge inbox socket (TCP fallback)", "port", port)
	} else {
		slog.Info("bridge inbox socket (Unix)", "path", sockPath)
	}

	inboxSocket.listener = listener
	inboxSocket.dir = dir
	inboxSocket.started = true

	// Accept connections in background
	go inboxSocket.acceptLoop()
}

func (s *inboxSocketState) acceptLoop() {
	for {
		conn, err := s.listener.Accept()
		if err != nil {
			slog.Info("bridge inbox socket accept loop ending", "err", err)
			break
		}
		s.mu.Lock()
		s.clients[conn] = true
		clientCount := len(s.clients)
		s.mu.Unlock()
		slog.Info("bridge inbox socket client connected", "total_clients", clientCount)

		// Read-loop: wait for client disconnect so we can clean up
		go func(c net.Conn) {
			defer func() {
				c.Close()
				s.mu.Lock()
				delete(s.clients, c)
				rem := len(s.clients)
				s.mu.Unlock()
				slog.Info("bridge inbox socket client disconnected", "remaining", rem)
			}()
			buf := make([]byte, 1)
			for {
				_, err := c.Read(buf)
				if err != nil {
					return
				}
			}
		}(conn)
	}
}

func (s *inboxSocketState) close() {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.listener != nil {
		s.listener.Close()
	}
	for conn := range s.clients {
		conn.Close()
	}
	s.clients = make(map[net.Conn]bool)
	s.started = false
}

// broadcastToInboxSocket sends a JSON message (raw bytes, no trailing newline)
// to all connected socket clients. Non-blocking: if a client is slow or
// disconnected, it's silently dropped.
func broadcastToInboxSocket(msg []byte) {
	inboxSocket.mu.Lock()
	clientCount := len(inboxSocket.clients)
	started := inboxSocket.started
	inboxSocket.mu.Unlock()

	if !started {
		return
	}
	if clientCount == 0 {
		slog.Debug("bridge inbox broadcast skipped — no clients")
		return
	}

	slog.Info("bridge inbox socket broadcasting", "clients", clientCount, "msg_len", len(msg))

	inboxSocket.mu.Lock()
	defer inboxSocket.mu.Unlock()

	// Append newline (JSON lines format)
	line := append(msg, '\n')

	for conn := range inboxSocket.clients {
		// Non-blocking write with deadline
		conn.SetWriteDeadline(time.Now().Add(100 * time.Millisecond))
		if _, err := conn.Write(line); err != nil {
			// Remove dead client
			conn.Close()
			delete(inboxSocket.clients, conn)
			slog.Debug("bridge inbox socket client dropped", "err", err)
		}
	}
}

// cmdBridgeListen connects to a bridge inbox socket and prints messages to stdout.
// Usage: ils bridge listen --dir /path/to/bridge
func cmdBridgeListen(args []string) {
	dir := ""
	for i := 0; i < len(args); i++ {
		if args[i] == "--dir" && i+1 < len(args) {
			dir = args[i+1]
			i++
		}
	}
	if dir == "" {
		dir = os.Getenv("ILS_BRIDGE_DIR")
	}
	if dir == "" {
		fmt.Fprintln(os.Stderr, "usage: ils bridge listen --dir /path/to/bridge")
		fmt.Fprintln(os.Stderr, "       or: ILS_BRIDGE_DIR=/path/to/bridge ils bridge listen")
		os.Exit(1)
	}

	sockPath := filepath.Join(dir, "inbox.sock")

	// Wait for socket file to exist (retry for 10s)
	for i := 0; i < 50; i++ {
		if _, err := os.Stat(sockPath); err == nil {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	// Try Unix socket first
	conn, err := net.Dial("unix", sockPath)
	if err != nil {
		// Fall back to TCP (Windows compat)
		portPath := filepath.Join(dir, "inbox.port")
		portData, pErr := os.ReadFile(portPath)
		if pErr != nil {
			fmt.Fprintf(os.Stderr, "connect to inbox socket (unix): %v\n", err)
			fmt.Fprintf(os.Stderr, "no TCP fallback port file either: %v\n", pErr)
			os.Exit(1)
		}
		port := strings.TrimSpace(string(portData))
		conn, err = net.Dial("tcp", "127.0.0.1:"+port)
		if err != nil {
			fmt.Fprintf(os.Stderr, "connect to inbox socket (tcp): %v\n", err)
			os.Exit(1)
		}
		fmt.Fprintf(os.Stderr, "📬 inbox socket connected (TCP port %s), waiting for messages...\n", port)
	} else {
		fmt.Fprintf(os.Stderr, "📬 inbox socket connected (Unix), waiting for messages...\n")
	}
	defer conn.Close()

	scanner := bufio.NewScanner(conn)

	// Start stdin reader goroutine: lines from stdin → outbox.ndjson
	// This makes `ils bridge listen | agent` bidirectional:
	//   socket → stdout (messages to agent)
	//   stdin  → outbox (replies from agent)
	stdinCh := make(chan string, 64)
	go func() {
		stdinScan := bufio.NewScanner(os.Stdin)
		for stdinScan.Scan() {
			stdinCh <- stdinScan.Text()
		}
	}()

	// Main loop: read from socket, write to stdout
	// Also check for stdin input periodically
	for scanner.Scan() {
		line := scanner.Text()
		var msg bridgeInboxMsg
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			continue
		}
		// Output raw UAS chat JSON to stdout for simple shell consumers.
		fmt.Println(line)
		os.Stdout.Sync()

		// Drain any pending stdin input (non-blocking)
		for {
			select {
			case stdinLine := <-stdinCh:
				appendToOutbox(dir, stdinLine, &msg)
			default:
				goto doneDrain
			}
		}
	doneDrain:
	}

	// After socket EOF, continue reading stdin until pipe closes
	fmt.Fprintf(os.Stderr, "[bridge] inbox socket closed, listening on stdin only...\n")
	for stdinLine := range stdinCh {
		appendToOutbox(dir, stdinLine, nil)
	}
}

// appendToOutbox writes a reply line to outbox.ndjson.
// If stdinLine is valid JSON with "reply" + "conv_id", use as-is.
// Otherwise, wrap as {"reply":"<line>","conv_id":"<from last msg>"}.
func appendToOutbox(dir, stdinLine string, lastMsg *bridgeInboxMsg) {
	outboxPath := filepath.Join(dir, "outbox.ndjson")
	var entry map[string]interface{}
	if err := json.Unmarshal([]byte(stdinLine), &entry); err == nil {
		// Valid JSON — use as-is (must have "reply" field)
		if _, ok := entry["reply"]; ok {
			b, _ := json.Marshal(entry)
			f, err := os.OpenFile(outboxPath, os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0644)
			if err == nil {
				f.Write(append(b, '\n'))
				f.Close()
				fmt.Fprintf(os.Stderr, "[bridge] outbox written (json): %s\n", entry["reply"])
			}
			return
		}
	}
	// Plain text — wrap with conv_id from last message if available
	convID := ""
	if lastMsg != nil {
		convID = lastMsg.ConvID
	}
	reply := bridgeOutboxMsg{
		Reply:  strings.TrimSpace(stdinLine),
		ConvID: convID,
	}
	b, _ := json.Marshal(reply)
	f, err := os.OpenFile(outboxPath, os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0644)
	if err == nil {
		f.Write(append(b, '\n'))
		f.Close()
		fmt.Fprintf(os.Stderr, "[bridge] outbox written: %s\n", reply.Reply)
	}
}

// ── Outbox watcher (daemon polls, agent writes) ───────────────

// outboxCursor tracks how many lines we've already read from outbox.ndjson.
// Persisted to cursor file so new daemon restarts don't re-send old replies.
type outboxState struct {
	mu     sync.Mutex
	dir    string
	lines  int // number of lines already consumed
	stopCh chan struct{}
}

func newOutboxState(dir string) *outboxState {
	return &outboxState{
		dir:    dir,
		stopCh: make(chan struct{}),
	}
}

func (s *outboxState) loadCursor() {
	path := filepath.Join(s.dir, ".outbox_cursor")
	data, err := os.ReadFile(path)
	if err != nil {
		s.lines = 0
		return
	}
	fmt.Sscanf(strings.TrimSpace(string(data)), "%d", &s.lines)
}

func (s *outboxState) saveCursor() {
	path := filepath.Join(s.dir, ".outbox_cursor")
	os.WriteFile(path, []byte(fmt.Sprintf("%d\n", s.lines)), 0644)
}

func (s *outboxState) pollOnce(cfg daemonCfg) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path := filepath.Join(s.dir, "outbox.ndjson")
	f, err := os.Open(path)
	if err != nil {
		if !os.IsNotExist(err) {
			slog.Warn("bridge outbox open", "err", err)
		}
		return
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	lineNum := 0
	for scanner.Scan() {
		lineNum++
		if lineNum <= s.lines {
			continue // already consumed
		}
		// New reply line
		var msg bridgeOutboxMsg
		if err := json.Unmarshal(scanner.Bytes(), &msg); err != nil {
			slog.Warn("bridge outbox parse", "err", err)
			continue
		}
		reply := strings.TrimSpace(msg.Reply)
		if reply == "" {
			continue
		}
		// Send the reply back through Gateway
		slog.Info("bridge outbox reply",
			"event_id", msg.EventID[:min(len(msg.EventID), 12)],
			"conv_id", msg.ConvID[:min(len(msg.ConvID), 12)],
			"target_agent_id", msg.TargetAgentID,
			"reply_len", len(reply))

		// Feishu bot model: reply must have a target. Empty target is dropped.
		sendGatewayChatReply(cfg, "bridge", msg.ConvID, reply, msg.TargetAgentID)
	}
	s.lines = lineNum
	s.saveCursor()
}

func (s *outboxState) start(cfg daemonCfg) {
	s.loadCursor()
	slog.Info("bridge outbox watcher started", "dir", s.dir, "cursor_lines", s.lines)

	tick := time.NewTicker(2 * time.Second)
	defer tick.Stop()

	for {
		select {
		case <-s.stopCh:
			slog.Info("bridge outbox watcher stopped")
			return
		case <-tick.C:
			s.pollOnce(cfg)
		}
	}
}

func (s *outboxState) stop() {
	close(s.stopCh)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ── Global bridge watcher (singleton, started on first message) ──

var (
	globalOutboxState *outboxState
	globalOutboxMu    sync.Mutex
)

// startBridgeOutboxWatcher starts the outbox polling goroutine once.
// Subsequent calls are no-ops. Called from handleChatEvent on first bridge message.
func startBridgeOutboxWatcher(cfg daemonCfg) {
	globalOutboxMu.Lock()
	defer globalOutboxMu.Unlock()

	if globalOutboxState != nil {
		return // already running
	}

	dir := cfg.BridgeDir
	state := newOutboxState(dir)
	globalOutboxState = state
	go state.start(cfg)

	slog.Info("bridge outbox watcher launched", "dir", dir)
}

// ── Bridge auto: auto-responder (testing/headless mode) ──────

func cmdBridgeAuto(args []string) {
	dir := ""
	for i, a := range args {
		if a == "--dir" && i+1 < len(args) {
			dir = args[i+1]
		}
	}
	if dir == "" {
		dir = os.Getenv("ILS_BRIDGE_DIR")
	}
	if dir == "" {
		fmt.Fprintln(os.Stderr, "usage: ils bridge auto --dir /path/to/bridge")
		fmt.Fprintln(os.Stderr, "       or: ILS_BRIDGE_DIR=/path/to/bridge ils bridge auto")
		os.Exit(1)
	}

	// Try Unix socket, fall back to TCP
	outboxPath := filepath.Join(dir, "outbox.ndjson")
	sockPath := filepath.Join(dir, "inbox.sock")
	for i := 0; i < 50; i++ {
		if _, err := os.Stat(sockPath); err == nil {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	conn, err := net.Dial("unix", sockPath)
	if err != nil {
		// TCP fallback
		portPath := filepath.Join(dir, "inbox.port")
		portData, pErr := os.ReadFile(portPath)
		if pErr != nil {
			fmt.Fprintf(os.Stderr, "connect: %v / fallback: %v\n", err, pErr)
			os.Exit(1)
		}
		port := strings.TrimSpace(string(portData))
		conn, err = net.Dial("tcp", "127.0.0.1:"+port)
		if err != nil {
			fmt.Fprintf(os.Stderr, "connect tcp: %v\n", err)
			os.Exit(1)
		}
	}
	defer conn.Close()

	fmt.Fprintf(os.Stderr, "📬 bridge auto: connected, auto-replying to all messages...\n")

	// Track responded event IDs to prevent loops
	responded := make(map[string]bool)

	scanner := bufio.NewScanner(conn)
	for scanner.Scan() {
		line := scanner.Text()
		var msg bridgeInboxMsg
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			continue
		}
		// Skip already-responded events (resists re-broadcast loops)
		if responded[msg.EventID] {
			continue
		}
		// Skip auto-generated messages (prevents auto → Gateway → auto loops)
		if strings.Contains(msg.Text, "[auto]") {
			continue
		}
		responded[msg.EventID] = true
		// Drop messages with no sender UUID — replies cannot be targeted
		// per Feishu bot model (every reply has a specific recipient).
		if msg.FromAgentID == "" {
			fmt.Fprintf(os.Stderr, "↘ drop [%s] %s (no from_agent_id)\n",
				msg.From, msg.Text[:min(len(msg.Text), 40)])
			continue
		}
		replyBody := bridgeOutboxMsg{
			EventID:       msg.EventID,
			Reply:         fmt.Sprintf("[auto] %s said: %s", msg.From, msg.Text),
			ConvID:        msg.ConvID,
			TargetAgentID: msg.FromAgentID,
		}
		b, _ := json.Marshal(replyBody)
		f, err := os.OpenFile(outboxPath, os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0644)
		if err != nil {
			fmt.Fprintf(os.Stderr, "write outbox: %v\n", err)
			continue
		}
		f.Write(append(b, '\n'))
		f.Close()
		fmt.Fprintf(os.Stderr, "↻ auto-replied to [%s] %s\n", msg.From, msg.Text[:min(len(msg.Text), 40)])
	}
}

// cmdBridgeRuntime replaces `bridge auto`'s canned echo with a real
// command invocation. For each inbox chat message, it pipes the message
// text into the configured shell command's stdin and uses its stdout as
// the reply. Target is always the original sender's UUID (Feishu model).
//
// Usage:
//   ils bridge runtime --dir <bridge-dir> --cmd "<shell-line>" [--timeout 60s]
//
// Env vars (used when flags are omitted):
//   ILS_BRIDGE_DIR — same as --dir
//   ILS_BRIDGE_CMD — same as --cmd
//
// Examples:
//   --cmd "claude --print"                     # spawn a Claude Code subprocess
//   --cmd "reasonix run --stdin"               # invoke Reasonix CLI
//   --cmd "ollama run llama3"                  # call a local LLM via Ollama
//   --cmd "python /opt/agent/main.py"          # custom Python adapter
//
// The command reads the chat text from stdin and must write its reply
// to stdout. stderr is captured into the reply on non-zero exit.
func cmdBridgeRuntime(args []string) {
	dir := ""
	cmdline := ""
	shell := ""
	timeoutStr := "60s"

	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--dir":
			if i+1 < len(args) {
				dir = args[i+1]
				i++
			}
		case "--cmd":
			if i+1 < len(args) {
				cmdline = args[i+1]
				i++
			}
		case "--shell":
			if i+1 < len(args) {
				shell = args[i+1]
				i++
			}
		case "--timeout":
			if i+1 < len(args) {
				timeoutStr = args[i+1]
				i++
			}
		}
	}

	if dir == "" {
		dir = os.Getenv("ILS_BRIDGE_DIR")
	}
	if cmdline == "" {
		cmdline = os.Getenv("ILS_BRIDGE_CMD")
	}
	if shell == "" {
		shell = os.Getenv("ILS_BRIDGE_SHELL")
	}
	// Pick a sensible default shell per OS. Windows agents (R3/R4) often
	// lack Git Bash, so default to PowerShell which ships with Windows
	// Server out of the box. For PowerShell, do NOT pass "-Command -"
	// (that means "read command from stdin", which conflicts with our
	// "append cmdline as a -Command argument" pattern). The user-supplied
	// cmdline can still read piped stdin via the $Input automatic var.
	// Override via --shell or ILS_BRIDGE_SHELL.
	if shell == "" {
		if runtime.GOOS == "windows" {
			shell = "powershell -NoProfile -Command"
		} else {
			shell = "sh -c"
		}
	}

	if dir == "" || cmdline == "" {
		fmt.Fprintln(os.Stderr, "usage: ils bridge runtime --dir /path --cmd '<shell command>'")
		fmt.Fprintln(os.Stderr, "       or: ILS_BRIDGE_DIR=... ILS_BRIDGE_CMD=... ils bridge runtime")
		fmt.Fprintln(os.Stderr, "       --cmd reads chat text on stdin, writes reply on stdout")
		os.Exit(1)
	}

	timeout, err := time.ParseDuration(timeoutStr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid --timeout %q: %v\n", timeoutStr, err)
		os.Exit(1)
	}

	outboxPath := filepath.Join(dir, "outbox.ndjson")
	sockPath := filepath.Join(dir, "inbox.sock")
	for i := 0; i < 50; i++ {
		if _, err := os.Stat(sockPath); err == nil {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	conn, err := net.Dial("unix", sockPath)
	if err != nil {
		portPath := filepath.Join(dir, "inbox.port")
		portData, pErr := os.ReadFile(portPath)
		if pErr != nil {
			fmt.Fprintf(os.Stderr, "connect: %v / fallback: %v\n", err, pErr)
			os.Exit(1)
		}
		port := strings.TrimSpace(string(portData))
		conn, err = net.Dial("tcp", "127.0.0.1:"+port)
		if err != nil {
			fmt.Fprintf(os.Stderr, "connect tcp: %v\n", err)
			os.Exit(1)
		}
	}
	defer conn.Close()

	fmt.Fprintf(os.Stderr, "🤖 bridge runtime: shell=%q cmd=%q timeout=%s, reading inbox...\n", shell, cmdline, timeout)

	responded := make(map[string]bool)
	scanner := bufio.NewScanner(conn)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		var msg bridgeInboxMsg
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			continue
		}
		if responded[msg.EventID] {
			continue
		}
		// Prevent runtime ↔ runtime loops: skip anything an auto-responder produced.
		if strings.Contains(msg.Text, "[auto]") || strings.Contains(msg.Text, "[runtime]") {
			continue
		}
		// Feishu model: cannot reply without a target — drop.
		if msg.FromAgentID == "" {
			fmt.Fprintf(os.Stderr, "↘ drop [%s] no from_agent_id\n", msg.From)
			continue
		}
		responded[msg.EventID] = true

		// Invoke the configured shell command with text on stdin.
		// shellParts splits the shell template (e.g. "sh -c", "powershell
		// -NoProfile -Command") so the chat cmdline is appended as the
		// last arg. The user-supplied cmdline reads piped stdin to receive
		// chat text (sh: stdin directly; PowerShell: $Input automatic var).
		ctx, cancel := context.WithTimeout(context.Background(), timeout)
		shellParts := strings.Fields(shell)
		if len(shellParts) == 0 {
			fmt.Fprintln(os.Stderr, "invalid empty shell")
			cancel()
			continue
		}
		shellArgs := append([]string(nil), shellParts[1:]...)
		// PowerShell on Windows: Windows command-line "\"" escaping conflicts
		// with PowerShell's string parser — closing braces in script blocks
		// get eaten, producing "Missing closing '}'" errors. Use base64
		// UTF-16LE -EncodedCommand to sidestep all quoting issues.
		shellBase := filepath.Base(shellParts[0])
		shellBaseNoExt := strings.TrimSuffix(strings.ToLower(shellBase), ".exe")
		isPowerShell := shellBaseNoExt == "powershell" || shellBaseNoExt == "pwsh"
		fmt.Fprintf(os.Stderr, "[exec] shell0=%q base=%q isPowerShell=%v\n", shellParts[0], shellBase, isPowerShell)
		if isPowerShell {
			// Strip "-Command" if present at end; we replace with -EncodedCommand.
			cleanArgs := make([]string, 0, len(shellArgs))
			for _, a := range shellArgs {
				if strings.EqualFold(a, "-Command") {
					continue
				}
				cleanArgs = append(cleanArgs, a)
			}
			u16 := utf16.Encode([]rune(cmdline))
			buf := make([]byte, len(u16)*2)
			for i, r := range u16 {
				buf[i*2] = byte(r & 0xff)
				buf[i*2+1] = byte(r >> 8)
			}
			encoded := base64.StdEncoding.EncodeToString(buf)
			cleanArgs = append(cleanArgs, "-EncodedCommand", encoded)
			shellArgs = cleanArgs
		} else {
			shellArgs = append(shellArgs, cmdline)
		}
		shellCmd := exec.CommandContext(ctx, shellParts[0], shellArgs...)
		shellCmd.Stdin = strings.NewReader(msg.Text)
		shellCmd.Env = os.Environ()
		out, runErr := shellCmd.CombinedOutput()
		cancel()

		reply := strings.TrimSpace(string(out))
		if runErr != nil {
			reply = fmt.Sprintf("⚠️ runtime error: %v\n%s", runErr, reply)
		}
		if reply == "" {
			reply = "(empty reply)"
		}
		// Mark replies so peers can dedupe and avoid runtime↔runtime echo.
		reply = "[runtime] " + reply
		if len(reply) > 4000 {
			reply = reply[:4000] + "\n...(truncated)"
		}

		replyBody := bridgeOutboxMsg{
			EventID:       msg.EventID,
			Reply:         reply,
			ConvID:        msg.ConvID,
			TargetAgentID: msg.FromAgentID,
		}
		b, _ := json.Marshal(replyBody)
		f, ferr := os.OpenFile(outboxPath, os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0644)
		if ferr != nil {
			fmt.Fprintf(os.Stderr, "write outbox: %v\n", ferr)
			continue
		}
		f.Write(append(b, '\n'))
		f.Close()
		preview := msg.Text
		if len(preview) > 30 {
			preview = preview[:30]
		}
		fmt.Fprintf(os.Stderr, "✓ runtime replied to [%s] %q → %d bytes\n", msg.From, preview, len(reply))
	}
}
