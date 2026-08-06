package main

import (
	"crypto/tls"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

//go:embed web/*
var webFS embed.FS

var (
	orchestratorURL string
	gatewayURL      string
	obAgentID       string
	obAppID         string
	httpClient      = &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{
				InsecureSkipVerify: true, // self-signed, internal use
			},
		},
	}

	// WS client (Feishu-style persistent channel)
	wsClient *WSClient

	// In-memory cache — updated by WS pushes, served by HTTP API
	cacheMut    sync.RWMutex
	agentCache  = make(map[string]any) // agentID -> agent info
	taskCache   = make(map[string]any) // taskID -> task info
	cacheLoaded bool

	// Chat message store — appended by WS chat:reply, served by /api/chat/messages
	chatMessages   []ChatMessage
	chatMsgMu      sync.Mutex
	chatMsgCounter int64

	// SSE broadcast — new messages pushed to all connected frontends
	sseClients    = make(map[chan []byte]struct{})
	sseClientsMu  sync.Mutex
	sseRegister   = make(chan chan []byte)
	sseUnregister = make(chan chan []byte)
	sseBroadcast  = make(chan []byte, 64)
)

// ChatMessage represents a single chat message in the conversation.
type ChatMessage struct {
	ID        int64  `json:"id"`
	FromAgent string `json:"from_agent,omitempty"`
	ToAgent   string `json:"to_agent,omitempty"`
	Content   string `json:"content"`
	Subtype   string `json:"subtype,omitempty"` // thinking / tool_call / result (empty=normal)
	Timestamp int64  `json:"timestamp"`
	Direction string `json:"direction"` // "sent" or "received"
}

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})))

	orchestratorURL = envDefault("UA_ORCHESTRATOR_URL", "https://api.upser.pro")
	gatewayURL = envDefault("UA_GATEWAY_URL", "wss://api.upser.pro/ws")
	obAgentID = envDefault("UA_AGENT_ID", "ob-main")
	port := envDefault("UA_OB_PORT", envDefault("UA_DESKTOP_PORT", "19800"))

	slog.Info("OB (Operation Bridge) starting",
		"orchestrator", orchestratorURL,
		"gateway_ws", gatewayURL,
		"port", port)

	// ── Start WebSocket client (Feishu-style persistent channel) ──────
	token := os.Getenv("UA_AUTH_TOKEN")
	if token == "" {
		// Try login to get a token
		token = tryLogin()
	}

	// SSE hub: fan-out chat messages to all connected frontends
	go sseHub()

	wsClient = NewWSClient(WSClientConfig{
		ServerURL:     gatewayURL,
		Token:         token,
		AppID:         obAppID,
		AutoReconnect: true,
		OnMessage:     handleWSMessage,
		OnReconnecting: func() {
			slog.Warn("ob ws reconnecting...")
		},
		OnReconnected: func() {
			slog.Info("ob ws reconnected, refreshing cache")
			refreshCache()
		},
	})

	go func() {
		if err := wsClient.Connect(); err != nil {
			slog.Warn("ws initial connect failed, will retry", "err", err)
		}
	}()

	// ── HTTP server (serves frontend + API) ────────────────────────────
	mux := http.NewServeMux()

	// Static
	mux.HandleFunc("GET /", serveIndex)

	// API
	mux.HandleFunc("GET /api/agents", handleAgents)
	mux.HandleFunc("GET /api/tasks", handleTasks)
	mux.HandleFunc("GET /api/config", handleGetConfig)
	mux.HandleFunc("PUT /api/config", handlePutConfig)
	mux.HandleFunc("GET /api/health", handleHealth)
	mux.HandleFunc("POST /api/chat/send", handleChatSend)
	mux.HandleFunc("GET /api/chat/messages", handleChatMessages)
	mux.HandleFunc("GET /api/chat/stream", handleChatStream)

	handler := loggingMiddleware(mux)
	server := &http.Server{
		Addr:         ":" + port,
		Handler:      handler,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
	}

	slog.Info("OB ready", "url", "http://localhost:"+port)
	if err := server.ListenAndServe(); err != nil {
		slog.Error("server failed", "err", err)
		os.Exit(1)
	}
}

// ── Handlers ──────────────────────────────────────────────────────────

func serveIndex(w http.ResponseWriter, r *http.Request) {
	data, err := webFS.ReadFile("web/index.html")
	if err != nil {
		http.Error(w, "index not found", 500)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(data)
}

// handleAgents returns active Gateway connections as chat targets, falling back
// to the old orchestrator/cache path only when Gateway status is unavailable.
func handleAgents(w http.ResponseWriter, r *http.Request) {
	if agents, ok := gatewayAgents(); ok {
		writeJSON(w, 200, map[string]any{
			"agents": agents,
			"source": "gateway_events_status",
		})
		return
	}

	cacheMut.RLock()
	loaded := cacheLoaded
	cacheMut.RUnlock()

	if loaded {
		cacheMut.RLock()
		data := agentCache
		cacheMut.RUnlock()
		writeJSON(w, 200, map[string]any{
			"agents": data,
			"source": "ws_cache",
		})
		return
	}

	// Fallback to HTTP proxy
	proxyToOrchestrator(w, "/agents")
}

func gatewayAgents() (map[string]any, bool) {
	resp, err := httpClient.Get(gatewayHTTPBase() + "/events/status")
	if err != nil {
		slog.Warn("gateway agents status failed", "err", err)
		return nil, false
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		slog.Warn("gateway agents status non-2xx", "status", resp.StatusCode)
		return nil, false
	}

	var status struct {
		Connections []struct {
			ConnectionID string `json:"connection_id"`
			ConsumerID   string `json:"consumer_id"`
			AppID        string `json:"app_id"`
			Kind         string `json:"kind"`
			AgentID      string `json:"agent_id"`
			AgentType    string `json:"agent_type"`
			Ready        bool   `json:"ready"`
			ReadyType    string `json:"ready_type"`
			ConnectedAt  string `json:"connected_at"`
			LastSeenAt   string `json:"last_seen_at"`
		} `json:"connections"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		slog.Warn("gateway agents decode failed", "err", err)
		return nil, false
	}

	agents := make(map[string]any)
	for _, conn := range status.Connections {
		if conn.AgentID == "" || conn.AgentID == obAgentID {
			continue
		}
		if !conn.Ready {
			continue
		}
		agentType := conn.AgentType
		if agentType == "" {
			agentType = conn.Kind
		}
		agents[conn.AgentID] = map[string]any{
			"id":            conn.AgentID,
			"name":          conn.AgentID,
			"agent_name":    conn.AgentID,
			"agent_type":    agentType,
			"type":          conn.Kind,
			"status":        "online",
			"ready":         conn.Ready,
			"ready_type":    conn.ReadyType,
			"connection_id": conn.ConnectionID,
			"consumer_id":   conn.ConsumerID,
			"app_id":        conn.AppID,
			"connected_at":  conn.ConnectedAt,
			"last_seen_at":  conn.LastSeenAt,
		}
	}
	return agents, true
}

func gatewayHTTPBase() string {
	base := gatewayURL
	if strings.HasPrefix(base, "ws://") {
		base = "http://" + strings.TrimPrefix(base, "ws://")
	} else if strings.HasPrefix(base, "wss://") {
		base = "https://" + strings.TrimPrefix(base, "wss://")
	}
	return strings.TrimSuffix(base, "/ws")
}

// handleTasks returns task stats from WS cache, falling back to HTTP proxy.
func handleTasks(w http.ResponseWriter, r *http.Request) {
	cacheMut.RLock()
	loaded := cacheLoaded
	cacheMut.RUnlock()

	if loaded {
		cacheMut.RLock()
		data := taskCache
		cacheMut.RUnlock()
		writeJSON(w, 200, map[string]any{
			"tasks":  data,
			"source": "ws_cache",
		})
		return
	}

	proxyToOrchestrator(w, "/tasks/stats")
}

func handleGetConfig(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{
		"orchestrator_url": orchestratorURL,
		"gateway_url":      gatewayURL,
	})
}

func handlePutConfig(w http.ResponseWriter, r *http.Request) {
	var req map[string]string
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, 400, map[string]any{"error": "invalid body"})
		return
	}
	if u, ok := req["orchestrator_url"]; ok && u != "" {
		orchestratorURL = u
	}
	if g, ok := req["gateway_url"]; ok && g != "" {
		gatewayURL = g
	}
	writeJSON(w, 200, map[string]any{"status": "ok"})
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]any{
		"status":           "ok",
		"orchestrator_url": orchestratorURL,
		"gateway_url":      gatewayURL,
	})
}

// ── WebSocket message handler ─────────────────────────────────────────

func handleWSMessage(msg WSMessage) {
	switch msg.Type {
	case "server:welcome":
		slog.Info("ws welcome received, refreshing cache")
		refreshCache()

	case "agent:status", "agent:online", "agent:offline":
		var payload map[string]any
		if err := json.Unmarshal(msg.Payload, &payload); err == nil {
			cacheMut.Lock()
			if id, ok := payload["agent_id"].(string); ok {
				agentCache[id] = payload
				cacheLoaded = true
			}
			// Merge all agents if full list
			if agents, ok := payload["agents"]; ok {
				if agentMap, ok := agents.(map[string]any); ok {
					for k, v := range agentMap {
						agentCache[k] = v
					}
					cacheLoaded = true
				}
			}
			cacheMut.Unlock()
		}

	case "task:progress", "task:dispatched":
		var payload map[string]any
		if err := json.Unmarshal(msg.Payload, &payload); err == nil {
			cacheMut.Lock()
			if id, ok := payload["task_id"].(string); ok {
				taskCache[id] = payload
			}
			if tasks, ok := payload["tasks"]; ok {
				if taskMap, ok := tasks.(map[string]any); ok {
					for k, v := range taskMap {
						taskCache[k] = v
					}
				}
			}
			cacheMut.Unlock()
		}

	case "server:config":
		slog.Info("ws config update", "payload", string(msg.Payload))

	case "chat", "chat:reply":
		// Gateway sends type:"chat" with fields from/from_agent_id/text; legacy type:"chat:reply" used from_agent/content
		var chatReply struct {
			From        string `json:"from"`
			FromAgentID string `json:"from_agent_id"` // UUID — used by frontend to match selectedAgent
			FromAgent   string `json:"from_agent"`
			Text        string `json:"text"`
			Content     string `json:"content"`
			Subtype     string `json:"subtype"`
		}
		if err := json.Unmarshal(msg.Raw, &chatReply); err == nil {
			// Prefer UUID so frontend can match with selectedAgent
			fromAgent := chatReply.FromAgentID
			if fromAgent == "" {
				fromAgent = chatReply.FromAgent
			}
			if fromAgent == "" {
				fromAgent = chatReply.From
			}
			content := chatReply.Text
			if content == "" {
				content = chatReply.Content
			}
			if fromAgent != "" && content != "" {
				chatMsgMu.Lock()
				chatMsgCounter++
				cm := ChatMessage{
					ID:        chatMsgCounter,
					FromAgent: fromAgent,
					Content:   content,
					Subtype:   chatReply.Subtype,
					Timestamp: time.Now().UnixMilli(),
					Direction: "received",
				}
				chatMessages = append(chatMessages, cm)
				if len(chatMessages) > 200 {
					chatMessages = chatMessages[len(chatMessages)-200:]
				}
				chatMsgMu.Unlock()

				// Push to SSE clients
				if data, err := json.Marshal(cm); err == nil {
					select {
					case sseBroadcast <- data:
					default:
					}
				}
				slog.Info("chat reply stored", "from", chatReply.From, "agent_id", fromAgent, "subtype", chatReply.Subtype)
			}
		}

	default:
		slog.Debug("ws unhandled message", "type", msg.Type)
	}
}

// refreshCache fetches fresh data from the orchestrator to populate the cache.
func refreshCache() {
	if agents, ok := gatewayAgents(); ok {
		cacheMut.Lock()
		agentCache = agents
		cacheLoaded = true
		cacheMut.Unlock()
	}

	// Fetch agents
	resp, err := httpClient.Get(orchestratorURL + "/agents")
	if err != nil {
		slog.Warn("refresh agents failed", "err", err)
		return
	}
	defer resp.Body.Close()

	var agentsResp map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&agentsResp); err == nil {
		cacheMut.Lock()
		if rawAgents, ok := agentsResp["agents"]; ok {
			// Orchestrator returns agents as an array of objects: [{"id":"...","name":"C2"},...]
			// Convert to map for frontend lookup
			switch v := rawAgents.(type) {
			case []interface{}:
				newCache := make(map[string]any)
				for _, item := range v {
					if m, ok := item.(map[string]any); ok {
						if id, ok := m["id"].(string); ok {
							newCache[id] = m
						}
					}
				}
				agentCache = newCache
			case map[string]any:
				agentCache = v
			}
		} else {
			agentCache = agentsResp
		}
		cacheLoaded = true
		cacheMut.Unlock()
	}

	// Fetch task stats
	resp2, err := httpClient.Get(orchestratorURL + "/tasks/stats")
	if err != nil {
		slog.Warn("refresh tasks failed", "err", err)
		return
	}
	defer resp2.Body.Close()

	var tasksResp map[string]any
	if err := json.NewDecoder(resp2.Body).Decode(&tasksResp); err == nil {
		cacheMut.Lock()
		taskCache = tasksResp
		cacheMut.Unlock()
	}

	slog.Info("cache refreshed", "agents", len(agentCache))
}

// ── Task dispatch ──────────────────────────────────────────────────────

func buildTask(text string) map[string]any {
	taskType := detectTaskType(text)
	return map[string]any{
		"title":        truncate(text, 80),
		"description":  text,
		"task_type":    taskType,
		"context_goal": text,
		"priority":     50,
		"created_by":   "desktop",
		"payload": map[string]any{
			"context": map[string]any{
				"goal": text,
			},
		},
		"acceptance_check": map[string]any{
			"type": acceptanceType(taskType),
		},
		"required_capabilities": map[string]any{
			"source":     "desktop",
			"agent_type": agentTypeForTask(taskType),
		},
	}
}

func agentTypeForTask(taskType string) string {
	switch taskType {
	case "review", "audit", "analysis", "research":
		return "opencode"
	case "deployment":
		return "claude_code"
	default:
		return "generic"
	}
}

func acceptanceType(taskType string) string {
	switch taskType {
	case "coding", "deployment":
		return "command"
	default:
		return "describe"
	}
}

func detectTaskType(text string) string {
	lower := strings.ToLower(text)
	switch {
	case strings.Contains(lower, "审查") || strings.Contains(lower, "review"):
		return "review"
	case strings.Contains(lower, "修复") || strings.Contains(lower, "fix") || strings.Contains(lower, "bug"):
		return "coding"
	case strings.Contains(lower, "部署") || strings.Contains(lower, "deploy"):
		return "deployment"
	case strings.Contains(lower, "研究") || strings.Contains(lower, "research"):
		return "research"
	default:
		return "coding"
	}
}

// ── Chat API ──────────────────────────────────────────────────────────

// handleChatSend sends a chat message to a target agent via Gateway WSS.
func handleChatSend(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ToAgent string `json:"to_agent"`
		Content string `json:"content"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ToAgent == "" || req.Content == "" {
		writeJSON(w, 400, map[string]any{"error": "to_agent and content required"})
		return
	}

	if wsClient == nil || !wsClient.IsConnected() {
		writeJSON(w, 503, map[string]any{"error": "gateway not connected"})
		return
	}

	// POST to Gateway HTTP /chat (WS only handles control messages, not chat delivery)
	httpGateway := strings.Replace(gatewayURL, "ws://", "http://", 1)
	httpGateway = strings.Replace(httpGateway, "wss://", "https://", 1)
	httpGateway = strings.Replace(httpGateway, "/ws", "", 1)

	chatPayload := map[string]any{
		"from":            "老板",
		"from_agent_id":   obAgentID,
		"target_agent_id": req.ToAgent,
		"text":            req.Content,
		"conv_id":         obAgentID,
	}
	chatBody, _ := json.Marshal(chatPayload)
	resp, err := httpClient.Post(httpGateway+"/chat", "application/json", strings.NewReader(string(chatBody)))
	if err != nil {
		writeJSON(w, 502, map[string]any{"error": "gateway post failed: " + err.Error()})
		return
	}
	resp.Body.Close()
	if resp.StatusCode >= 300 {
		writeJSON(w, 502, map[string]any{"error": fmt.Sprintf("gateway returned %d", resp.StatusCode)})
		return
	}

	// Record sent message
	chatMsgMu.Lock()
	chatMsgCounter++
	chatMessages = append(chatMessages, ChatMessage{
		ID:        chatMsgCounter,
		ToAgent:   req.ToAgent,
		Content:   req.Content,
		Timestamp: time.Now().UnixMilli(),
		Direction: "sent",
	})
	if len(chatMessages) > 200 {
		chatMessages = chatMessages[len(chatMessages)-200:]
	}
	chatMsgMu.Unlock()

	slog.Info("chat sent", "to", req.ToAgent)
	writeJSON(w, 200, map[string]any{"status": "sent"})
}

// handleChatMessages returns new messages since a given ID for polling.
func handleChatMessages(w http.ResponseWriter, r *http.Request) {
	sinceStr := r.URL.Query().Get("since")
	var since int64
	if sinceStr != "" {
		fmt.Sscanf(sinceStr, "%d", &since)
	}

	chatMsgMu.Lock()
	var newMsgs []ChatMessage
	for _, m := range chatMessages {
		if m.ID > since {
			newMsgs = append(newMsgs, m)
		}
	}
	chatMsgMu.Unlock()

	if newMsgs == nil {
		newMsgs = []ChatMessage{}
	}
	writeJSON(w, 200, map[string]any{"messages": newMsgs})
}

// ── SSE (Server-Sent Events) ─────────────────────────────────────────

// sseHub fans out SSE broadcasts to all connected frontend clients.
func sseHub() {
	for {
		select {
		case client := <-sseRegister:
			sseClientsMu.Lock()
			sseClients[client] = struct{}{}
			sseClientsMu.Unlock()

		case client := <-sseUnregister:
			sseClientsMu.Lock()
			delete(sseClients, client)
			close(client)
			sseClientsMu.Unlock()

		case msg := <-sseBroadcast:
			sseClientsMu.Lock()
			for client := range sseClients {
				select {
				case client <- msg:
				default:
					// slow client, skip
				}
			}
			sseClientsMu.Unlock()
		}
	}
}

// handleChatStream is an SSE endpoint that pushes new chat messages in real-time.
func handleChatStream(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	// Register this client
	ch := make(chan []byte, 32)
	sseRegister <- ch

	ctx := r.Context()
	defer func() { sseUnregister <- ch }()

	// Send current state (last 20 messages)
	chatMsgMu.Lock()
	start := 0
	if len(chatMessages) > 20 {
		start = len(chatMessages) - 20
	}
	for _, m := range chatMessages[start:] {
		data, _ := json.Marshal(m)
		fmt.Fprintf(w, "data: %s\n\n", data)
	}
	chatMsgMu.Unlock()
	flusher.Flush()

	// Stream new messages
	for {
		select {
		case <-ctx.Done():
			return
		case msg, ok := <-ch:
			if !ok {
				return
			}
			fmt.Fprintf(w, "data: %s\n\n", msg)
			flusher.Flush()
		}
	}
}

// ── Auth ──────────────────────────────────────────────────────────────

// tryLogin attempts to get a JWT token from the gateway.
func tryLogin() string {
	username := envDefault("UA_AUTH_USERNAME", "admin")
	password := os.Getenv("UA_AUTH_PASSWORD")
	if password == "" {
		slog.Warn("no UA_AUTH_PASSWORD set, WS will connect unauthenticated")
		return ""
	}

	body, _ := json.Marshal(map[string]string{
		"username": username,
		"password": password,
		"name":     "OB Cockpit",
		"agent_id": obAgentID,
	})

	// Gateway URL from ws:// to http://
	httpGateway := strings.Replace(gatewayURL, "ws://", "http://", 1)
	httpGateway = strings.Replace(httpGateway, "wss://", "https://", 1)
	// Strip /ws path
	httpGateway = strings.Replace(httpGateway, "/ws", "", 1)

	resp, err := httpClient.Post(
		httpGateway+"/auth/login",
		"application/json",
		strings.NewReader(string(body)),
	)
	if err != nil {
		slog.Warn("login failed", "err", err)
		return ""
	}
	defer resp.Body.Close()

	var result map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return ""
	}

	token := result["token"]
	obAppID = result["app_id"]
	slog.Info("login successful", "agent_id", obAgentID, "app_id", obAppID)
	return token
}

// ── Proxy fallback ────────────────────────────────────────────────────

func proxyToOrchestrator(w http.ResponseWriter, path string) {
	resp, err := httpClient.Get(orchestratorURL + path)
	if err != nil {
		writeJSON(w, 502, map[string]any{"error": "orchestrator unreachable"})
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	io.Copy(w, resp.Body)
}

// ── Helpers ───────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func envDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// parseWSPayload safely extracts payload from a WS message (handles both string and object).
func parseWSPayload(raw json.RawMessage) map[string]any {
	var result map[string]any
	if err := json.Unmarshal(raw, &result); err != nil {
		// Try as a string-encoded JSON
		var s string
		if err2 := json.Unmarshal(raw, &s); err2 == nil {
			json.Unmarshal([]byte(s), &result)
		}
	}
	if result == nil {
		result = make(map[string]any)
	}
	return result
}

func truncate(s string, max int) string {
	runes := []rune(s)
	if len(runes) <= max {
		return s
	}
	return string(runes[:max])
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		slog.Info("http",
			"method", r.Method,
			"path", r.URL.Path,
			"ms", time.Since(start).Milliseconds())
	})
}
