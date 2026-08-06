package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/konspace/unionagents-go/internal/agent"
	"github.com/konspace/unionagents-go/internal/uasclient"
)

// ── Config ────────────────────────────────────────────────────

type daemonCfg struct {
	OrchestratorURL string
	GatewayURL      string
	AgentID         string
	AgentName       string
	AgentType       string
	Username        string
	Password        string
	Token           string
	BridgeDir       string // non-empty = bridge mode (inbox/outbox file exchange)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func loadDaemonConfig() daemonCfg {
	hostname, _ := os.Hostname()
	return daemonCfg{
		OrchestratorURL: envOr("ORCHESTRATOR_URL", envOr("UAS_ORCHESTRATOR_URL", "http://111.228.42.18:8000")),
		GatewayURL:      envOr("GATEWAY_URL", "wss://api.upser.pro"),
		AgentID:         os.Getenv("AGENT_ID"),
		AgentName:       envOr("AGENT_NAME", hostname+"-ils"),
		AgentType:       envOr("AGENT_TYPE", "claude_code"),
		Username:        envOr("GATEWAY_USERNAME", "admin"),
		Password:        os.Getenv("GATEWAY_PASSWORD"),
		BridgeDir:       os.Getenv("ILS_BRIDGE_DIR"),
	}
}

// ── Entrypoint ────────────────────────────────────────────────

func daemonRun() {
	cfg := loadDaemonConfig()

	// 1. Agent Binding Contract self-check — verify the runtime is available.
	if binding := agent.LookupRuntime(cfg.AgentType); binding.OK {
		slog.Info("agent binding ok", "type", cfg.AgentType, "exe", binding.ExePath)
		if err := binding.Runtime.Doctor(); err != nil {
			slog.Warn("agent doctor check failed", "type", cfg.AgentType, "err", err)
		}
	} else {
		slog.Error("agent binding failed — chat will not work", "type", cfg.AgentType, "err", binding.Err)
	}

	// 2. Register with Orchestrator if no ID
	if cfg.AgentID == "" {
		id, err := registerAgent(cfg)
		if err != nil {
			slog.Error("agent registration failed", "err", err)
			os.Exit(1)
		}
		cfg.AgentID = id
		slog.Info("agent registered", "id", id, "name", cfg.AgentName)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// 3. Task channel — events from uasclient → main execution loop
	taskChan := make(chan map[string]interface{}, 10)

	// 4. Heartbeat goroutine
	go heartbeatLoop(ctx, cfg)

	httpClient := ilsHTTPClient()

	// 5. Build uasclient with OnRawEvent to intercept task:dispatch + chat.
	// The library handles login, register, dial, handshake, reconnect, ping.
	cl := uasclient.New(uasclient.Config{
		GatewayURL:      cfg.GatewayURL,
		AgentID:         cfg.AgentID,
		AgentName:       cfg.AgentName,
		AgentType:       cfg.AgentType,
		Password:        cfg.Password,
		OrchestratorURL: cfg.OrchestratorURL,
		OnRawEvent: func(ctx context.Context, raw map[string]interface{}) bool {
			return dispatchDaemonEvent(raw, taskChan, cfg)
		},
	})

	// 6. Start bridge outbox watcher immediately if in bridge mode
	if cfg.BridgeDir != "" {
		startBridgeOutboxWatcher(cfg)
		ensureInboxSocket(cfg.BridgeDir)
		slog.Info("bridge initialized", "dir", cfg.BridgeDir)
	}

	// 7. Connect blocks until ctx is cancelled. Run the task loop
	// in a goroutine alongside it.
	fmt.Printf("ils daemon ready | agent: %s | name: %s\n", cfg.AgentID, cfg.AgentName)
	fmt.Println("connected to Gateway WSS, waiting for tasks... (Ctrl-C to quit)")

	// Connect runs the reconnect loop. We run it in a goroutine so
	// we can also process the task channel.
	go func() {
		if err := cl.Connect(ctx); err != nil {
			slog.Error("uasclient connect exited with error", "err", err)
		}
	}()

	// 8. Main event loop — execute tasks as they arrive via WebSocket
	for {
		select {
		case <-ctx.Done():
			slog.Info("daemon stopping")
			_ = cl.Close()
			return
		case task := <-taskChan:
			executeTask(ctx, httpClient, cfg, task)
		}
	}
}

// dispatchDaemonEvent is the OnRawEvent callback for the daemon.
// It intercepts task:dispatch and chat events, returning true to
// consume them (prevent the library's chat-only path from also
// processing them). For all other event types, returns false so
// the library handles them normally.
func dispatchDaemonEvent(raw map[string]interface{}, taskChan chan map[string]interface{}, cfg daemonCfg) bool {
	t, _ := raw["type"].(string)
	switch t {
	case "task:dispatch":
		if task, ok := raw["task"].(map[string]interface{}); ok {
			taskID, _ := task["id"].(string)
			slog.Info("task received via WebSocket", "id", taskID)
			select {
			case taskChan <- task:
			default:
				slog.Warn("task channel full, dropping task", "id", taskID)
			}
		}
		return true // consumed
	case "chat":
		go handleChatEvent(raw, cfg)
		return true // consumed (daemon handles ack via its own reply)
	case "server:welcome":
		slog.Info("gateway welcomed")
		return false // let library process (handshake)
	default:
		return false // let library handle
	}
}

// ── Agent registration ────────────────────────────────────────

func registerAgent(cfg daemonCfg) (string, error) {
	// Determine binding status before registration
	bindingStatus := "unknown"
	if binding := agent.LookupRuntime(cfg.AgentType); binding.OK {
		if err := binding.Runtime.Doctor(); err != nil {
			bindingStatus = "degraded"
		} else {
			bindingStatus = "ready"
		}
	} else {
		bindingStatus = "failed"
	}

	body, _ := json.Marshal(map[string]interface{}{
		"name":            cfg.AgentName,
		"agent_type":      cfg.AgentType,
		"binding_status":  bindingStatus,
		"os":              runtime.GOOS,
		"host_id":         cfg.AgentName,
		"shell":           shellBin(),
		"max_concurrency": 1,
	})
	client := ilsHTTPClient()
	req, _ := http.NewRequest("POST", cfg.OrchestratorURL+"/agents/register", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Token)
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	var result map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&result)
	if id, ok := result["id"].(string); ok {
		return id, nil
	}
	if id, ok := result["agent_id"].(string); ok {
		return id, nil
	}
	return "", fmt.Errorf("registration failed: %v", result)
}

func shellBin() string {
	if runtime.GOOS == "windows" {
		return "powershell"
	}
	return "bash"
}

// ── Heartbeat ─────────────────────────────────────────────────

func sendHeartbeat(cfg daemonCfg) {
	client := ilsShortHTTPClient()
	body, _ := json.Marshal(map[string]string{"agent_id": cfg.AgentID})
	req, _ := http.NewRequest("POST",
		cfg.OrchestratorURL+"/agents/"+cfg.AgentID+"/heartbeat",
		bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Token)
	}
	if resp, err := client.Do(req); err != nil {
		slog.Warn("heartbeat failed", "err", err)
	} else {
		resp.Body.Close()
		slog.Info("heartbeat sent")
	}
}

func heartbeatLoop(ctx context.Context, cfg daemonCfg) {
	// Send one immediately so Orchestrator marks agent online before the first task arrives.
	sendHeartbeat(cfg)

	tick := time.NewTicker(60 * time.Second)
	defer tick.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			sendHeartbeat(cfg)
		}
	}
}

// ── Chat handling ─────────────────────────────────────────────

// handleChatEvent receives a real-time chat message from Gateway and replies immediately.
// In normal mode: spawns a CLI subprocess (reasonix run / claude run ...).
// In bridge mode (BridgeDir != ""): writes to inbox.ndjson and lets the agent poll outbox.ndjson.
func handleChatEvent(raw map[string]interface{}, cfg daemonCfg) {
	from, _ := raw["from"].(string)
	fromAgentID, _ := raw["from_agent_id"].(string)
	text, _ := raw["text"].(string)
	convID, _ := raw["conv_id"].(string)
	targetAgentID, _ := raw["target_agent_id"].(string)
	eventID, _ := raw["event_id"].(string)

	if text == "" {
		return
	}
	// Only handle messages explicitly addressed to this agent.
	// Broadcast messages (empty target_agent_id) are for OB/Cockpit
	// clients, NOT for agents. Processing broadcast messages causes
	// agents to spam error replies that flood the Gateway and break
	// other agents' bidirectional communication.
	if targetAgentID == "" || targetAgentID != cfg.AgentID {
		return
	}

	fmt.Printf("\n[chat] %s → me\n  text: %s\n  from_agent_id: %s\n  conv_id: %s\n", from, text, fromAgentID, convID)

	// ── Bridge mode: write to inbox, let agent process via file exchange ──
	if cfg.BridgeDir != "" {
		if err := writeBridgeInbox(cfg.BridgeDir, eventID, from, fromAgentID, convID, text); err != nil {
			slog.Error("bridge inbox write", "err", err, "from_agent", fromAgentID)
			// Don't put internal errors on the chat bus. Caller will see
			// silence; ops sees the error via logs.
		}
		// Start outbox watcher once (idempotent: no-op if already running)
		startBridgeOutboxWatcher(cfg)
		return
	}

	// Invoke the agent via the Agent Binding Contract.
	go func() {
		binding := agent.LookupRuntime(cfg.AgentType)
		if !binding.OK {
			// Echo fallback: always reply so the requester gets a response
			// instead of silence. This is the key to bidirectional WS testing.
			echoReply := fmt.Sprintf("[echo] %s received your message\n  text: %s\n  agent_type: %s\n  note: runtime not configured (%s)",
				cfg.AgentName, text, cfg.AgentType, binding.Err)
			if len(echoReply) > 4000 {
				echoReply = echoReply[:4000] + "\n...(truncated)"
			}
			// Feishu model: only reply if we know who to reply to.
			// No sender UUID → silent drop (avoids broadcast spam).
			sendGatewayChatReply(cfg, from, convID, echoReply, fromAgentID)
			return
		}

		// Run the doctor self-check before first use.
		// Per Feishu bot model: internal health failures MUST NOT enter the
		// chat message bus. They go to logs/metrics. R5 self-bombed
		// 240k events into Gateway on 2026-06-15 by sending doctor errors
		// as chat replies, which broadcast back, which it auto-replied to.
		if err := binding.Runtime.Doctor(); err != nil {
			slog.Error("agent doctor check failed — silent (not on chat bus)",
				"agent_id", cfg.AgentID,
				"agent_type", cfg.AgentType,
				"runtime", binding.Runtime.Type,
				"err", err)
			return
		}

		// Remote runtime → HTTP POST to the agent's RemoteURL
		if binding.Runtime.RemoteURL != "" {
			reply, err := forwardToRemoteAgent(binding.Runtime, from, text, convID, cfg.AgentID)
			if err != nil {
				// Remote errors are user-facing in the conversation,
				// but only if we know the sender. Drop otherwise.
				reply = fmt.Sprintf("⚠️ %s remote error: %v\n%s", binding.Runtime.Type, err, reply)
			}
			if reply == "" {
				reply = fmt.Sprintf("[%s] remote agent returned no content", binding.Runtime.Type)
			}
			if len(reply) > 4000 {
				reply = reply[:4000] + "\n...(truncated)"
			}
			sendGatewayChatReply(cfg, from, convID, reply, fromAgentID)
			return
		}

		// No runtime available — neither remote URL nor local CLI.
		// Send an echo fallback so the requester always gets a reply
		// (critical for ils chat request and bidirectional WS tests).
		if binding.Runtime.RemoteURL == "" && binding.ExePath == "" {
			echoReply := fmt.Sprintf("[echo] %s received your message (agent_type=%s, no runtime configured)\n  text: %s",
				cfg.AgentName, cfg.AgentType, text)
			if len(echoReply) > 4000 {
				echoReply = echoReply[:4000] + "\n...(truncated)"
			}
			// Feishu model: silently drop if no sender to reply to.
			sendGatewayChatReply(cfg, from, convID, echoReply, fromAgentID)
			return
		}

		// Local CLI runtime
		wrappedPrompt := binding.Runtime.WrapChatPrompt(text)
		args := binding.Runtime.BuildArgs(wrappedPrompt)
		ctx, cancel := context.WithTimeout(context.Background(), binding.Runtime.Timeout)
		defer cancel()

		cmd := exec.CommandContext(ctx, binding.ExePath, args...)
		cmd.Env = os.Environ()
		out, runErr := cmd.CombinedOutput()

		reply := strings.TrimSpace(string(out))
		if runErr != nil {
			reply = fmt.Sprintf("⚠️ %s error: %v\n%s", binding.Runtime.Type, runErr, reply)
		}
		if reply == "" {
			reply = fmt.Sprintf("[%s] completed with no output", binding.Runtime.Type)
		}
		if len(reply) > 4000 {
			reply = reply[:4000] + "\n...(truncated)"
		}
		sendGatewayChatReply(cfg, from, convID, reply, fromAgentID)
	}()
}

// forwardToRemoteAgent POSTs a chat message to a remote agent's HTTP endpoint
// and returns the reply text.
func forwardToRemoteAgent(rt agent.RuntimeSchema, from, text, convID, agentID string) (string, error) {
	payload, _ := json.Marshal(map[string]interface{}{
		"from":       from,
		"text":       text,
		"conv_id":    convID,
		"agent_id":   agentID,
		"agent_type": rt.Type,
	})
	client := &http.Client{Timeout: rt.Timeout}
	resp, err := client.Post(rt.RemoteURL, "application/json", bytes.NewReader(payload))
	if err != nil {
		return "", fmt.Errorf("POST %s: %w", rt.RemoteURL, err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4000))
	if resp.StatusCode >= 300 {
		return string(body), fmt.Errorf("HTTP %d from %s", resp.StatusCode, rt.RemoteURL)
	}
	return string(body), nil
}

// triggerSelfPoll calls POST /tasks/poll so the Orchestrator immediately leases
// and broadcasts the just-created chat task back to this agent via Gateway WS.
func triggerSelfPoll(cfg daemonCfg) {
	time.Sleep(300 * time.Millisecond) // let the DB commit
	body, _ := json.Marshal(map[string]interface{}{
		"agent_id":   cfg.AgentID,
		"agent_name": cfg.AgentName,
		"agent_type": cfg.AgentType,
	})
	req, _ := http.NewRequest("POST", cfg.OrchestratorURL+"/tasks/poll", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Token)
	}
	client := ilsHTTPClient()
	resp, err := client.Do(req)
	if err != nil {
		slog.Warn("self-poll failed", "err", err)
		return
	}
	defer resp.Body.Close()
	slog.Info("self-poll triggered", "status", resp.StatusCode)
}

// sendGatewayChatReply posts the agent reply back through Gateway POST /chat
// to a SPECIFIC target agent. Feishu bot model: every reply has a recipient.
// Empty targetAgentID is dropped silently (would otherwise broadcast and
// cause feedback loops — see R5 240k-event self-bomb incident 2026-06-15).
func sendGatewayChatReply(cfg daemonCfg, replyTo, convID, text, targetAgentID string) {
	if targetAgentID == "" {
		slog.Warn("chat reply dropped (no target)",
			"from_agent", cfg.AgentID,
			"conv_id", convID,
			"reason", "feishu_model_requires_target")
		return
	}
	gwHTTP := uasclient.HTTPBase(cfg.GatewayURL)
	chatPath := envOr("GATEWAY_CHAT_PATH", "/api/gateway/chat")
	tgt := targetAgentID
	body := map[string]interface{}{
		"from_agent_id":   cfg.AgentID,
		"from":            cfg.AgentName,
		"target_agent_id": tgt, // empty → Gateway BroadcastToAllClients
		"text":            text,
		"conv_id":         convID,
	}
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST", gwHTTP+chatPath, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	if cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Token)
	}
	client := ilsHTTPClient()
	resp, err := client.Do(req)
	if err != nil {
		slog.Error("chat reply failed", "err", err)
		return
	}
	defer resp.Body.Close()
	fmt.Printf("[chat] reply → %s (conv: %s)\n", replyTo, convID)
}

// ── Task execution ────────────────────────────────────────────

func executeTask(ctx context.Context, client *http.Client, cfg daemonCfg, task map[string]interface{}) {
	taskID, _ := task["id"].(string)
	title, _ := task["title"].(string)
	description, _ := task["description"].(string)

	// Chat tasks must NEVER run as shell commands. Chat is a direct Gateway relay
	// (handleChatEvent). Mark them done to drain the queue safely.
	if tt, _ := task["task_type"].(string); tt == "chat" {
		fmt.Printf("\n[TASK] %s — skipping chat-type task (handled via Gateway relay)\n", taskID[:8])
		completeTask(client, cfg, taskID, "done", "chat task — no execution needed (Gateway relay)", nil)
		return
	}

	// Prefer payload.instruction > payload.context.goal > description
	instruction := description
	if payload, ok := task["payload"].(map[string]interface{}); ok {
		if inst, ok := payload["instruction"].(string); ok && inst != "" {
			instruction = inst
		} else if ctx, ok := payload["context"].(map[string]interface{}); ok {
			if goal, ok := ctx["goal"].(string); ok && goal != "" {
				instruction = goal
			}
		}
	}

	fmt.Printf("\n[TASK] %s\n  id:   %s\n  goal: %s\n", title, taskID[:8], instruction)

	var cmd *exec.Cmd
	if runtime.GOOS == "windows" {
		cmd = exec.CommandContext(ctx, "powershell", "-NonInteractive", "-Command", instruction)
	} else {
		cmd = exec.CommandContext(ctx, "bash", "-c", instruction)
	}

	out, err := cmd.CombinedOutput()
	summary := strings.TrimSpace(string(out))
	if len(summary) > 2000 {
		summary = summary[:2000] + "\n...(truncated)"
	}

	status := "done"
	var errMsg *string
	if err != nil {
		status = "needs_review"
		e := err.Error()
		errMsg = &e
		fmt.Printf("[FAILED] %s\n%s\n", err, summary)
	} else {
		fmt.Printf("[DONE]\n%s\n", summary)
	}

	completeTask(client, cfg, taskID, status, summary, errMsg)
}

func completeTask(client *http.Client, cfg daemonCfg, taskID, status, summary string, errMsg *string) {
	body := map[string]interface{}{
		"agent_id": cfg.AgentID,
		"status":   status,
		"summary":  &summary,
	}
	if errMsg != nil {
		body["error_message"] = errMsg
		et := "execution_error"
		body["error_type"] = &et
	}

	b, _ := json.Marshal(body)
	req, _ := http.NewRequest("POST",
		cfg.OrchestratorURL+"/tasks/"+taskID+"/complete",
		bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	if cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+cfg.Token)
	}
	resp, err := client.Do(req)
	if err != nil {
		slog.Error("complete failed", "task", taskID, "err", err)
		return
	}
	defer resp.Body.Close()
	slog.Info("task complete", "id", taskID, "status", status)
}
