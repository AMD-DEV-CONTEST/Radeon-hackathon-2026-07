// Command brain is the UAS AI runtime — a Go single binary that runs an
// LLM-backed agent body on top of internal/uasclient transport.
//
// Strict Lark CLI alignment:
//   - ils is the only transport (consume + send)
//   - brain is what would otherwise be "Claude Desktop / Cursor" on the
//     Lark side: a thin AI runtime that uses the transport CLI's library
//   - no 35+ messenger platforms, no plugin loader, no bot framework
//   - stateless: each inbound chat event triggers one LLM round-trip with
//     no cross-message memory. Multi-turn context, if needed, is the
//     caller's responsibility (include history in the message body, or
//     teach DeepSeek's session API later).
//
// Run:
//
//	DEEPSEEK_API_KEY=sk-... GATEWAY_PASSWORD=... \
//	  brain --agent-id cc-c1-brain --agent-name C1
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/konspace/unionagents-go/internal/uasclient"
)

type llmRequest struct {
	Model       string       `json:"model"`
	MaxTokens   int          `json:"max_tokens"`
	Temperature float64      `json:"temperature"`
	System      string       `json:"system,omitempty"`
	Messages    []llmMessage `json:"messages"`
}

type llmMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type llmResponseBlock struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

type llmResponse struct {
	Content []llmResponseBlock `json:"content"`
	Usage   struct {
		InputTokens  int `json:"input_tokens"`
		OutputTokens int `json:"output_tokens"`
	} `json:"usage"`
	StopReason string `json:"stop_reason"`
}

// callLLM does one Anthropic-Messages-shaped POST and returns the
// assistant text + usage. Pure function — tests inject http.Client.
func callLLM(
	ctx context.Context,
	hc *http.Client,
	baseURL, apiKey, model, system, userText string,
	maxTokens int, temperature float64,
) (string, int, int, error) {
	body, err := json.Marshal(llmRequest{
		Model:       model,
		MaxTokens:   maxTokens,
		Temperature: temperature,
		System:      system,
		Messages:    []llmMessage{{Role: "user", Content: userText}},
	})
	if err != nil {
		return "", 0, 0, err
	}
	url := strings.TrimRight(baseURL, "/") + "/v1/messages"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return "", 0, 0, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")

	resp, err := hc.Do(req)
	if err != nil {
		return "", 0, 0, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	if resp.StatusCode/100 != 2 {
		snippet := string(raw)
		if len(snippet) > 300 {
			snippet = snippet[:300]
		}
		return "", 0, 0, fmt.Errorf("llm HTTP %d: %s", resp.StatusCode, snippet)
	}
	var lr llmResponse
	if err := json.Unmarshal(raw, &lr); err != nil {
		return "", 0, 0, fmt.Errorf("llm decode: %w", err)
	}
	var sb strings.Builder
	for _, b := range lr.Content {
		if b.Type == "text" || b.Type == "" {
			sb.WriteString(b.Text)
		}
	}
	return strings.TrimSpace(sb.String()), lr.Usage.InputTokens, lr.Usage.OutputTokens, nil
}

// sendFunc is the minimal contract Agent needs from uasclient.Client.
// Defined as a function type so tests can inject a fake.
type sendFunc func(ctx context.Context, msg uasclient.Outgoing) (*uasclient.SendResult, error)

// handleEvent: one inbound chat event -> one LLM call -> one outbound
// reply. Guardrails bound cost and risk but do not remove autonomy.
// Limit hit means cooldown + audit — not disconnect, not process exit.
func handleEvent(
	ctx context.Context,
	hc *http.Client,
	send sendFunc,
	cfg runtimeConfig,
	e uasclient.Event,
) {
	convID := e.ConvID
	if convID == "" {
		convID = e.ConversationID
	}
	peerID := e.FromAgentID
	if peerID == "" {
		peerID = e.From
	}
	text := e.Text
	if convID == "" || peerID == "" || text == "" {
		return
	}
	if peerID == cfg.AgentID {
		return // anti-loop
	}

	// Guardrails check before processing
	if blocked, _ := checkGuardrails(convID, peerID, cfg); blocked {
		return
	}

	system := fmt.Sprintf(
		"You are %s (%s), an AI agent on the UnionAgents System (UAS). "+
			"You are talking to another AI agent over UAS - not a human. The peer agent appears as %s. "+
			"Be concise, structured, machine-friendly. Plain text only; no markdown. State decisions and outcomes directly.",
		cfg.AgentName, cfg.AgentID, peerID,
	)

	reply, inTok, outTok, err := callLLM(
		ctx, hc, cfg.LLMBaseURL, cfg.LLMAPIKey, cfg.LLMModel,
		system, text, cfg.MaxTokens, cfg.Temperature,
	)
	if err != nil {
		log.Printf("brain: LLM error conv=%s peer=%s: %v", convID, peerID, err)
		return
	}
	if reply == "" {
		log.Printf("brain: empty LLM reply, skip send")
		return
	}
	out, err := send(ctx, uasclient.Outgoing{
		From:          cfg.AgentName,
		FromAgentID:   cfg.AgentID,
		TargetAgentID: peerID,
		Text:          reply,
		ConvID:        convID,
	})
	if err != nil {
		log.Printf("brain: send error conv=%s peer=%s: %v", convID, peerID, err)
		return
	}
		markReplySent(convID, inTok, outTok)
		writeAudit("reply_sent", convID, peerID, map[string]interface{}{
			"in_tok":    inTok,
			"out_tok":   outTok,
			"delivered": out.DeliveredToConnections,
		})
		log.Printf("brain: reply sent conv=%s peer=%s delivered=%d in_tok=%d out_tok=%d",
			convID, peerID, out.DeliveredToConnections, inTok, outTok)
	}

type convState struct {
	turnCount        int
	totalInputTokens int
	totalOutputTokens int
	startTime        time.Time
	lastReplyTime    time.Time
}

type guardrailConfig struct {
	MaxTurnsPerConv    int
	MaxTokensPerConv   int
	MaxWallTimePerConv time.Duration
	AllowedPeers       map[string]bool
	ReplyCooldown      time.Duration
}

type runtimeConfig struct {
	AgentID     string
	AgentName   string
	LLMBaseURL  string
	LLMAPIKey   string
	LLMModel    string
	MaxTokens   int
	Temperature float64
	Guardrails  guardrailConfig
}

var (
	stateMu  sync.Mutex
	convMap  = make(map[string]*convState)
	auditMu  sync.Mutex
	auditF   *os.File
)

func envOr(name, fallback string) string {
	if v := os.Getenv(name); v != "" {
		return v
	}
	return fallback
}

// auditEvent 审计事件写入 JSONL
type auditEvent struct {
	Timestamp string      `json:"timestamp"`
	EventType string      `json:"event_type"`
	ConvID    string      `json:"conv_id,omitempty"`
	PeerID    string      `json:"peer_id,omitempty"`
	Data      interface{} `json:"data,omitempty"`
}

func initAudit() error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	auditDir := filepath.Join(home, ".local", "share", "unionagents", "brain", "audit")
	if err := os.MkdirAll(auditDir, 0755); err != nil {
		return err
	}
	date := time.Now().Format("2006-01-02")
	path := filepath.Join(auditDir, date+".jsonl")
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	auditF = f
	return nil
}

func writeAudit(eventType, convID, peerID string, data interface{}) {
	if auditF == nil {
		return
	}
	auditMu.Lock()
	defer auditMu.Unlock()
	ev := auditEvent{
		Timestamp: time.Now().Format(time.RFC3339),
		EventType: eventType,
		ConvID:    convID,
		PeerID:    peerID,
		Data:      data,
	}
	line, _ := json.Marshal(ev)
	line = append(line, '\n')
	_, _ = auditF.Write(line)
}

func getConvState(convID string) *convState {
	stateMu.Lock()
	defer stateMu.Unlock()
	if s, ok := convMap[convID]; ok {
		return s
	}
	s := &convState{
		startTime: time.Now(),
	}
	convMap[convID] = s
	return s
}

func peersFromFlags(allowed []string) map[string]bool {
	if len(allowed) == 0 {
		return nil
	}
	m := make(map[string]bool)
	for _, p := range allowed {
		m[p] = true
	}
	return m
}

func checkGuardrails(convID, peerID string, cfg runtimeConfig) (blocked bool, reason string) {
	// 1. 检查 peer 是否被允许
	if cfg.Guardrails.AllowedPeers != nil && !cfg.Guardrails.AllowedPeers[peerID] {
		writeAudit("peer_not_allowed", convID, peerID, map[string]interface{}{"blocked": true})
		return true, "peer not allowed"
	}

	state := getConvState(convID)

	// 2. 检查 cooldown
	if cfg.Guardrails.ReplyCooldown > 0 {
		if time.Since(state.lastReplyTime) < cfg.Guardrails.ReplyCooldown {
			writeAudit("cooldown_active", convID, peerID, map[string]interface{}{
				"remaining_ms": cfg.Guardrails.ReplyCooldown.Milliseconds() - time.Since(state.lastReplyTime).Milliseconds(),
			})
			return true, "cooldown active"
		}
	}

	// 3. 检查 turn 限制
	if cfg.Guardrails.MaxTurnsPerConv > 0 && state.turnCount >= cfg.Guardrails.MaxTurnsPerConv {
		writeAudit("turn_limit_hit", convID, peerID, map[string]interface{}{
			"turns": state.turnCount,
			"limit": cfg.Guardrails.MaxTurnsPerConv,
		})
		return true, "turn limit hit"
	}

	// 4. 检查 token 限制
	if cfg.Guardrails.MaxTokensPerConv > 0 {
		totalTok := state.totalInputTokens + state.totalOutputTokens
		if totalTok >= cfg.Guardrails.MaxTokensPerConv {
			writeAudit("token_limit_hit", convID, peerID, map[string]interface{}{
				"total_tokens": totalTok,
				"limit":        cfg.Guardrails.MaxTokensPerConv,
			})
			return true, "token limit hit"
		}
	}

	// 5. 检查 wall time 限制
	if cfg.Guardrails.MaxWallTimePerConv > 0 {
		if time.Since(state.startTime) >= cfg.Guardrails.MaxWallTimePerConv {
			writeAudit("wall_time_hit", convID, peerID, map[string]interface{}{
				"elapsed_ms": time.Since(state.startTime).Milliseconds(),
				"limit_ms":   cfg.Guardrails.MaxWallTimePerConv.Milliseconds(),
			})
			return true, "wall time limit hit"
		}
	}

	return false, ""
}

func markReplySent(convID string, inTok, outTok int) {
	stateMu.Lock()
	defer stateMu.Unlock()
	if s, ok := convMap[convID]; ok {
		s.turnCount++
		s.totalInputTokens += inTok
		s.totalOutputTokens += outTok
		s.lastReplyTime = time.Now()
	}
}

func main() {
	fs := flag.NewFlagSet("brain", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("UAS_GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	agentID := fs.String("agent-id", os.Getenv("UAS_AGENT_ID"), "this brain's UAS agent id (required)")
	agentName := fs.String("agent-name", os.Getenv("UAS_AGENT_NAME"), "display name; defaults to agent-id")
	agentType := fs.String("agent-type", envOr("UAS_AGENT_TYPE", "hermes"), "agent_type for Gateway whitelist")
	gatewayPassword := fs.String("gateway-password", os.Getenv("GATEWAY_PASSWORD"), "Gateway admin password")
	llmBase := fs.String("llm-base-url", envOr("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic"), "Anthropic-compatible LLM base URL")
	llmKey := fs.String("llm-api-key", os.Getenv("DEEPSEEK_API_KEY"), "LLM API key")
	llmModel := fs.String("llm-model", envOr("UAS_LLM_MODEL", "deepseek-v4-flash"), "LLM model id")
	maxTokens := fs.Int("max-tokens", 1024, "LLM max_tokens")
	temperature := fs.Float64("temperature", 0.7, "LLM temperature")
	llmTimeoutSec := fs.Int("llm-timeout-sec", 60, "LLM HTTP timeout seconds")
	noHeartbeat := fs.Bool("no-heartbeat", false, "skip orchestrator HTTP heartbeat")

	// Guardrail flags
	maxTurns := fs.Int("max-turns-per-conv", 0, "max turns per conversation; 0 means unlimited")
	maxTokensConv := fs.Int("max-tokens-per-conv", 0, "max total tokens per conversation; 0 means unlimited")
	maxWallTime := fs.Duration("max-wall-time-per-conv", 0, "max wall time per conversation; 0 means unlimited")
	replyCooldown := fs.Duration("reply-cooldown-sec", 0, "minimum interval between replies; 0 means no cooldown")
	var allowedPeers []string
	fs.Func("allowed-peer", "if set, only allow listed peer agent id (repeatable)", func(v string) error {
		allowedPeers = append(allowedPeers, v)
		return nil
	})

	_ = fs.Parse(os.Args[1:])

	if *agentID == "" {
		fmt.Fprintln(os.Stderr, "--agent-id is required")
		os.Exit(2)
	}
	if *llmKey == "" {
		fmt.Fprintln(os.Stderr, "--llm-api-key required (set DEEPSEEK_API_KEY)")
		os.Exit(2)
	}
	if *agentName == "" {
		*agentName = *agentID
	}

	cfg := runtimeConfig{
		AgentID:     *agentID,
		AgentName:   *agentName,
		LLMBaseURL:  *llmBase,
		LLMAPIKey:   *llmKey,
		LLMModel:    *llmModel,
		MaxTokens:   *maxTokens,
		Temperature: *temperature,
		Guardrails: guardrailConfig{
			MaxTurnsPerConv:    *maxTurns,
			MaxTokensPerConv:   *maxTokensConv,
			MaxWallTimePerConv: *maxWallTime,
			AllowedPeers:       peersFromFlags(allowedPeers),
			ReplyCooldown:      *replyCooldown,
		},
	}
	hc := &http.Client{Timeout: time.Duration(*llmTimeoutSec) * time.Second}

	if err := initAudit(); err != nil {
		log.Printf("brain: audit init failed (continuing anyway): %v", err)
	}

	var client *uasclient.Client
	client = uasclient.New(uasclient.Config{
		GatewayURL:  *gatewayURL,
		AgentID:     *agentID,
		AgentName:   *agentName,
		AgentType:   *agentType,
		Password:    *gatewayPassword,
		NoHeartbeat: *noHeartbeat,
		Stderr:      os.Stderr,
		OnEvent: func(ctx context.Context, e uasclient.Event) error {
			handleEvent(ctx, hc, client.Send, cfg, e)
			return nil
		},
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	go func() { <-sigCh; log.Println("brain: shutdown"); cancel() }()

	log.Printf("brain online agent_id=%s name=%s gateway=%s model=%s",
		*agentID, *agentName, *gatewayURL, *llmModel)
	if err := client.Connect(ctx); err != nil && ctx.Err() == nil {
		log.Fatalf("brain: connect: %v", err)
	}
	_ = client.Close()
	log.Println("brain offline")
}
