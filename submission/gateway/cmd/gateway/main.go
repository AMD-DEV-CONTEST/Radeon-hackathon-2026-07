package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/konspace/unionagents-go/internal/boundary"
	"github.com/konspace/unionagents-go/internal/db"
	"github.com/konspace/unionagents-go/internal/gateway"
	"github.com/konspace/unionagents-go/internal/router"
)

func main() {
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})))
	slog.Info("UnionAgents Go — Gateway starting...")

	// ── Auth init ────────────────────────────────────────────────
	gateway.InitAuth()
	sweeperCtx, sweeperCancel := context.WithCancel(context.Background())
	defer sweeperCancel()
	gateway.StartConnectionSweeper(
		sweeperCtx,
		time.Duration(envInt("GATEWAY_CONNECTION_SWEEP_SECONDS", 30))*time.Second,
		time.Duration(envInt("GATEWAY_CONNECTION_STALE_SECONDS", 180))*time.Second,
	)
	gateway.StartRetryLoop(sweeperCtx)

	// ── Database (optional — gateway can work without) ──────────
	var pool *pgxpool.Pool

	p, err := db.Connect(context.Background())
	if err != nil {
		slog.Warn("db connect failed (gateway will run without token persistence)", "err", err)
	} else {
		pool = p
		defer pool.Close()
		db.RunMigrations(context.Background())
		gateway.InitPool(pool)
		gateway.LoadIdentitiesFromDB(context.Background())
	}

	// ── HTTP Router (stdlib) ─────────────────────────────────────
	mux := http.NewServeMux()

	// ── Model Router Layer ────────────────────────────────────────
	providerReg := router.NewRegistry()
	booter := router.NewBooter(providerReg)
	dispatcher := router.NewDispatcher(providerReg, booter)
	handoffMgr := router.NewHandoffManager(providerReg, dispatcher)

	// Seed default providers (9b-cpu, 35b-gpu, deepseek).
	seedProviders(providerReg)

	registerRouterRoutes(mux, providerReg, booter, dispatcher, handoffMgr)

	// ── Room Manager (Phase 5: AgentRoster) ───────────────────────
	room := router.NewRoomManager()
	// Phase 5: inject room into gateway so WS connect/disconnect updates presence.
	gateway.InitRoom(room)

	// health
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{
			"status":  "ok",
			"service": "unionagents-go-gateway",
			"time":    time.Now().UTC().Format(time.RFC3339),
		})
	})

	mux.HandleFunc("GET /boundary", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, boundary.NewSnapshot(
			"uas-gateway",
			"UAS-owned JD-ECS HTTP/WS relay for chat delivery, ready/ack/replay, and event status.",
		))
	})

	// Auth
	mux.HandleFunc("POST /auth/login", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Username string `json:"username"`
			Password string `json:"password"`
			Name     string `json:"name"`
			AgentID  string `json:"agent_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		identity, token, err := gateway.LoginClient(clientIP(r), req.Username, req.Password, req.Name, req.AgentID)
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": err.Error()})
			return
		}
		resp := map[string]string{"token": token}
		if identity != nil {
			resp["app_id"] = identity.AppID
			resp["expires_at"] = identity.ExpiresAt.Format(time.RFC3339)
		}
		writeJSON(w, http.StatusOK, resp)
	})

	mux.HandleFunc("POST /auth/logout", func(w http.ResponseWriter, r *http.Request) {
		token := gateway.ExtractToken(r)
		gateway.Logout(r.Context(), pool, token)
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	// Register client (for OB/Cockpit). This is the bootstrap enrollment call —
	// callers have no token yet by definition, so AuthMiddleware leaves it
	// exempt. 2026-07-07 audit: with no gate at all, anyone reaching the port
	// could self-mint a valid app_id/secret/token. registrationSecretOK adds an
	// opt-in shared-secret check (GATEWAY_REGISTRATION_SECRET): unset by
	// default, so existing deployments and the real gatewayclient (which does
	// not send this header today) keep working unchanged; operators who set it
	// close the anonymous-registration hole once their client is updated to
	// send X-Registration-Secret.
	mux.HandleFunc("POST /register/client", func(w http.ResponseWriter, r *http.Request) {
		if !registrationSecretOK(r) {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid or missing registration secret"})
			return
		}
		var req struct {
			Type    string `json:"type"`
			Name    string `json:"name"`
			AgentID string `json:"agent_id"`
			Version string `json:"version"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}

		identity, token, err := gateway.RegisterClient(req.Name, req.AgentID)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}

		writeJSON(w, http.StatusOK, map[string]interface{}{
			"app_id":     identity.AppID,
			"secret":     identity.Secret,
			"expires_at": identity.ExpiresAt.Format(time.RFC3339),
			"token":      token,
		})
	})

	// Generate agent key: user enters a codename on their desktop, the Gateway
	// mints a one-time "sk-xg-..." key, the user hands it to their Agent, and
	// the Agent presents it at /register/agent. Exempt from auth (same class as
	// /register/agent: the caller has no token yet by definition).
	mux.HandleFunc("POST /register/agent/generate-key", func(w http.ResponseWriter, r *http.Request) {
		if !registrationSecretOK(r) {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid or missing registration secret"})
			return
		}
		var req struct {
			Codename string `json:"codename"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		key, err := gateway.GenerateAgentKey(req.Codename)
		if err != nil {
			writeJSON(w, http.StatusConflict, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{
			"codename": req.Codename,
			"key":      key,
		})
	})

	// Register agent (for UAS-CLI)
	mux.HandleFunc("POST /register/agent", func(w http.ResponseWriter, r *http.Request) {
		if !registrationSecretOK(r) {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid or missing registration secret"})
			return
		}
		var req struct {
			Type      string `json:"type"`
			AgentType string `json:"agent_type"`
			AgentID   string `json:"agent_id"`
			AgentName string `json:"agent_name"`
			Version   string `json:"version"`
			Key       string `json:"key"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}

		// One-time key gate: a key must have been minted for this agent_id via
		// /register/agent/generate-key and must match. Without it, anyone who
		// can reach the port could claim any codename.
		if !gateway.ValidateAgentKey(req.AgentID, req.Key) {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid or missing agent key"})
			return
		}

		agentType := req.AgentType
		if agentType == "" && req.Type != "agent" {
			agentType = req.Type
		}
		identity, token, err := gateway.RegisterAgent(req.AgentID, req.AgentName, agentType)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		// Key proven — burn it so it cannot be reused for a second registration.
		gateway.ConsumeAgentKey(req.AgentID)

		writeJSON(w, http.StatusOK, map[string]interface{}{
			"app_id":     identity.AppID,
			"secret":     identity.Secret,
			"agent_type": identity.AgentType,
			"expires_at": identity.ExpiresAt.Format(time.RFC3339),
			"token":      token,
		})
	})

	// Client WebSocket (for OB / Cockpit) — authenticates with app_id + token
	mux.HandleFunc("GET /ws", func(w http.ResponseWriter, r *http.Request) {
		appID := r.URL.Query().Get("app_id")
		token := r.URL.Query().Get("token")

		if appID != "" {
			// New app_id-based authentication (agents and registered clients)
			if !gateway.VerifyAppIDToken(appID, token) {
				http.Error(w, "unauthorized", http.StatusUnauthorized)
				return
			}
		} else {
			// Legacy: admin JWT token in query param or Authorization header
			if token == "" {
				token = gateway.ExtractToken(r)
			}
			if !gateway.VerifyToken(r.Context(), pool, token) {
				http.Error(w, "unauthorized", http.StatusUnauthorized)
				return
			}
		}

		gateway.HandleClientWS(w, r, appID)
	})

	// Agent output WebSocket
	mux.HandleFunc("GET /agents/{agentID}/output", func(w http.ResponseWriter, r *http.Request) {
		agentID := r.PathValue("agentID")
		gateway.HandleAgentOutput(w, r, pool, agentID)
	})

	// GET /agents/status — Room Manager: list connected agents with presence.
	mux.HandleFunc("GET /agents/status", func(w http.ResponseWriter, r *http.Request) {
		agents := room.ListAll()
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status":       "ok",
			"agents":       agents,
			"online_count": room.Count(),
			"total_known":  len(agents),
		})
	})

	// POST /agents/{agentID}/presence — update agent presence status.
	mux.HandleFunc("POST /agents/{agentID}/presence", func(w http.ResponseWriter, r *http.Request) {
		agentID := r.PathValue("agentID")
		var req struct {
			Status string `json:"status"` // online_idle | online_busy | offline
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Status == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "status is required"})
			return
		}
		// 坑5 修复：presence API 不自带 join，新 agent 首次调用不生效。
		// 若 agent 尚未在 room 中，先 auto-join 再更新状态。
		if room.Get(agentID) == nil {
			room.Join(agentID, agentID, "", "")
		}
		room.SetStatus(agentID, req.Status)
		writeJSON(w, http.StatusOK, map[string]string{"status": "updated", "agent_id": agentID, "presence": req.Status})
	})

	// Phase 5: /tasks/dispatch REMOVED (Orchestrator decoupled — use /chat for all A2A).
	// Phase 5: /broadcast REMOVED (deprecated — all routing via /chat direct).

	mux.HandleFunc("GET /events/status", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, gateway.EventStatusSnapshot())
	})

	mux.HandleFunc("GET /events/replay", func(w http.ResponseWriter, r *http.Request) {
		eventKey := r.URL.Query().Get("event_key")
		sinceEventID := r.URL.Query().Get("since_event_id")
		var sinceSeq int64
		if raw := r.URL.Query().Get("since_seq"); raw != "" {
			sinceSeq, _ = strconv.ParseInt(raw, 10, 64)
		}
		events := gateway.ReplayEventsSinceSeq(eventKey, sinceEventID, sinceSeq)
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status":         "ok",
			"event_key":      eventKey,
			"since_event_id": sinceEventID,
			"since_seq":      sinceSeq,
			"events":         events,
		})
	})

	mux.HandleFunc("POST /events/ack", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			EventID    string `json:"event_id"`
			EventKey   string `json:"event_key"`
			ConsumerID string `json:"consumer_id"`
			Status     string `json:"status"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		if req.EventID == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "event_id is required"})
			return
		}
		if req.EventKey == "" {
			req.EventKey = "chat"
		}
		if req.ConsumerID == "" {
			req.ConsumerID = "http-replay-consumer"
		}
		if req.Status == "" {
			req.Status = "ack"
		}
		gateway.RecordEventConsumerStatus(req.EventID, req.EventKey, req.ConsumerID, req.Status)
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status":   "ok",
			"event_id": req.EventID,
		})
	})

	// #6: ACK query — sender checks delivery/ack status of an event.
	mux.HandleFunc("GET /events/ack/{eventID}", func(w http.ResponseWriter, r *http.Request) {
		eventID := r.PathValue("eventID")
		snapshot := gateway.EventAckStatus(eventID)
		if snapshot == nil {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "event not found", "event_id": eventID})
			return
		}
		writeJSON(w, http.StatusOK, snapshot)
	})

	// Chat endpoint — real-time conversation relay (event-stream model, like lark event bus).
	// Bypasses the Orchestrator task table entirely: a message in → routed straight to the
	// target consumer's live WebSocket. target_agent_id set → push to that agent;
	// empty (an agent's reply) → broadcast to all OB clients.
	// Phase 5: supports system sender (from_agent_id="system") and session_invite event type.
	chatHandler := func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			EventType       string                 `json:"event_type"`
			ClientMessageID string                 `json:"client_message_id"`
			From            string                 `json:"from"`            // sender display name (user, or agent codename)
			FromAgentID     string                 `json:"from_agent_id"`   // set by an agent when replying; "system" for gateway-originated
			TargetAgentID   string                 `json:"target_agent_id"` // set by OB when addressing an agent
			Text            string                 `json:"text"`
			ConvID          string                 `json:"conv_id"` // optional conversation id for multi-session routing
			Source          map[string]interface{} `json:"source"`
			Target          map[string]interface{} `json:"target"`
			Delivery        map[string]interface{} `json:"delivery"`
			SessionID       string                 `json:"session_id"` // for session_invite: the session to join
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		if req.Text == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "text is required"})
			return
		}

		now := time.Now().UTC()
		eventID := newPrefixedID("evt")
		messageID := newPrefixedID("msg")
		convID := req.ConvID
		if convID == "" {
			convID = newPrefixedID("conv")
		}

		if req.EventType == "" {
			req.EventType = "chat.message.created"
		}
		source := req.Source
		if source == nil {
			kind := chatSourceKind(req.FromAgentID)
			if req.FromAgentID == "system" {
				kind = "system"
			}
			source = map[string]interface{}{
				"kind":     kind,
				"agent_id": req.FromAgentID,
				"name":     req.From,
			}
		}
		target := req.Target
		if target == nil {
			target = map[string]interface{}{
				"kind":     chatTargetKind(req.TargetAgentID),
				"agent_id": req.TargetAgentID,
			}
		}
		deliveryMeta := req.Delivery
		if deliveryMeta == nil {
			deliveryMeta = map[string]interface{}{
				"requires_ack": true,
				"attempt":      1,
			}
		}
		deliveryMeta["requires_ack"] = true

		msg := map[string]interface{}{
			"type":              "chat",
			"event_id":          eventID,
			"event_type":        req.EventType,
			"message_id":        messageID,
			"client_message_id": req.ClientMessageID,
			"conversation_id":   convID,
			"from":              req.From,
			"from_agent_id":     req.FromAgentID,
			"target_agent_id":   req.TargetAgentID,
			"text":              req.Text,
			"conv_id":           convID,
			"ts":                now.Format(time.RFC3339),
			"source":            source,
			"target":            target,
			"delivery":          deliveryMeta,
		}
		// Phase 5: session_invite carries a session_id for the target to join.
		if req.EventType == "session_invite" && req.SessionID != "" {
			msg["session_id"] = req.SessionID
		}
		// #5: assign global monotonic seq for ordered replay.
		seq := gateway.NextSeq()
		msg["seq"] = seq
		// Resolve target_agent_id to canonical UUID if it's a name.
		// This ensures isReplyFor matching works: the delivered message
		// carries the UUID, and the agent's reply from_agent_id matches.
		resolvedTargetID := req.TargetAgentID
		if resolvedTargetID != "" {
			if uuid := gateway.ResolveAgentID(resolvedTargetID); uuid != "" {
				resolvedTargetID = uuid
				// Update the message payload with the resolved UUID
				msg["target_agent_id"] = resolvedTargetID
			}
		}
		payload, _ := json.Marshal(msg)

		var delivery gateway.DeliveryResult
		route := "gateway.ws.clients"
		retryRoute := "ob_clients"
		retryAppID := ""
		if req.TargetAgentID != "" {
			// OB → Agent: stream straight to the target agent's live connection.
			appID := gateway.GetAgentAppID(resolvedTargetID)
			if appID == "" && req.TargetAgentID != resolvedTargetID {
				appID = gateway.GetAgentAppID(req.TargetAgentID)
			}
			slog.Info("chat route lookup", "target_agent_id", req.TargetAgentID, "resolved", resolvedTargetID, "found_app_id", appID)
			if appID != "" {
				delivery = gateway.BroadcastToApp(appID, payload)
				route = "gateway.ws.agent_app"
				retryRoute = "agent_app"
				retryAppID = appID
				slog.Info("chat → agent (via app_id)", "agent", req.TargetAgentID, "resolved", resolvedTargetID, "app_id", appID, "event_id", eventID, "delivered", delivery.DeliveredToConnections)
			} else {
				delivery = gateway.BroadcastToAgent(resolvedTargetID, payload)
				route = "gateway.ws.agent_legacy"
				retryRoute = "agent_legacy"
				slog.Info("chat → agent (legacy)", "agent", req.TargetAgentID, "resolved", resolvedTargetID, "event_id", eventID, "delivered", delivery.DeliveredToConnections)
			}
		} else {
			// Agent → OB: broadcast the reply to connected OB/Cockpit clients only.
			// Do NOT broadcast to agents — they only receive targeted messages.
			// Broadcasting to agents caused R5 to spam error replies to every
			// message, flooding the Gateway and breaking other agents' comms.
			delivery = gateway.BroadcastToAllClients(payload)
			slog.Info("chat → ob_clients", "from_agent", req.FromAgentID, "event_id", eventID, "delivered", delivery.DeliveredToConnections)
		}
		gateway.StoreEventForReplaySeq(eventID, "chat", payload, seq)
		gateway.RecordEventDeliveryRouted(eventID, "chat", delivery.DeliveredToConnections, retryAppID, retryRoute)
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status":                   "accepted",
			"accepted":                 true,
			"event_id":                 eventID,
			"event_type":               req.EventType,
			"message_id":               messageID,
			"client_message_id":        req.ClientMessageID,
			"conversation_id":          convID,
			"conv_id":                  convID,
			"target_connected":         delivery.TargetConnected,
			"connection_count":         delivery.ConnectionCount,
			"delivered_to_connections": delivery.DeliveredToConnections,
			"failed_writes":            delivery.FailedWrites,
			"ack_required":             true,
			"route":                    route,
		})
	}
	mux.HandleFunc("POST /chat", chatHandler)
	mux.HandleFunc("POST /api/gateway/chat", chatHandler) // alias for legacy clients

	// Binary download (no auth needed — public)
	mux.HandleFunc("GET /download/ils", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("Content-Disposition", "attachment; filename=ils")
		http.ServeFile(w, r, "/usr/local/bin/ils")
	})

	// Middleware chain: CORS → auth → recover → log → timeout
	// WebSocket paths MUST bypass TimeoutHandler — http.TimeoutHandler wraps ResponseWriter
	// and prevents http.Hijacker, which breaks WebSocket upgrades entirely.
	var handler http.Handler = mux
	handler = gateway.AuthMiddleware(pool)(handler)
	handler = corsMiddleware(handler)
	handler = recoverMiddleware(handler)
	handler = loggingMiddleware(handler)

	// Apply timeout only to non-WS paths
	withTimeout := http.TimeoutHandler(handler, 60*time.Second, "")
	rootHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/ws") || strings.HasPrefix(r.URL.Path, "/agents/") {
			handler.ServeHTTP(w, r)
		} else {
			withTimeout.ServeHTTP(w, r)
		}
	})

	// ── Start HTTP server ────────────────────────────────────────
	port := os.Getenv("GATEWAY_PORT")
	if port == "" {
		port = "8001"
	}

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      rootHandler,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 0, // 0 = no timeout for WebSocket connections
		IdleTimeout:  120 * time.Second,
	}

	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		slog.Info("Shutting down...")
		sweeperCancel()
		shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer shutdownCancel()
		srv.Shutdown(shutdownCtx)
	}()

	slog.Info("Gateway listening", "port", port)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		slog.Error("gateway failed", "err", err)
		os.Exit(1)
	}
	slog.Info("Gateway stopped.")
}

func writeJSON(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(data); err != nil {
		slog.Warn("writeJSON encode", "err", err)
	}
}

func newPrefixedID(prefix string) string {
	var b [12]byte
	if _, err := rand.Read(b[:]); err != nil {
		return prefix + "_" + strconv.FormatInt(time.Now().UnixNano(), 36)
	}
	return prefix + "_" + hex.EncodeToString(b[:])
}

func chatSourceKind(fromAgentID string) string {
	if fromAgentID != "" {
		return "ils_daemon"
	}
	return "ob"
}

func chatTargetKind(targetAgentID string) string {
	if targetAgentID != "" {
		return "ils_daemon"
	}
	return "ob"
}

// registrationSecretOK gates POST /register/client. When
// GATEWAY_REGISTRATION_SECRET is unset (default), it always allows the
// request — this preserves today's open-registration behavior so no existing
// caller breaks. When set, the caller must send a matching
// X-Registration-Secret header.
func registrationSecretOK(r *http.Request) bool {
	want := os.Getenv("GATEWAY_REGISTRATION_SECRET")
	if want == "" {
		return true
	}
	got := r.Header.Get("X-Registration-Secret")
	return subtle.ConstantTimeCompare([]byte(got), []byte(want)) == 1
}

// clientIP returns the best-effort caller address for login rate limiting.
// Trusts X-Forwarded-For/X-Real-IP when present (typical behind a reverse
// proxy); falls back to the raw connection address otherwise. This is a
// rate-limit heuristic, not an auth boundary, so a spoofed header only costs
// an attacker their own throttling bucket, not a bypass of the check itself.
func clientIP(r *http.Request) string {
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		if i := strings.Index(fwd, ","); i >= 0 {
			return strings.TrimSpace(fwd[:i])
		}
		return strings.TrimSpace(fwd)
	}
	if ip := r.Header.Get("X-Real-IP"); ip != "" {
		return strings.TrimSpace(ip)
	}
	return r.RemoteAddr
}

func envInt(key string, fallback int) int {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n <= 0 {
		return fallback
	}
	return n
}

// corsMiddleware adds permissive CORS headers (replaces chi/cors).
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Accept, Authorization, Content-Type")
		w.Header().Set("Access-Control-Allow-Credentials", "true")
		w.Header().Set("Access-Control-Max-Age", "300")

		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// loggingMiddleware logs every request.
func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		slog.Info("http",
			"method", r.Method,
			"path", r.URL.Path,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

// recoverMiddleware recovers from panics in handlers.
func recoverMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rv := recover(); rv != nil {
				slog.Error("handler panic", "path", r.URL.Path, "panic", rv)
				http.Error(w, `{"error":"internal server error"}`, http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// ── Model Router Layer: seed + routes ─────────────────────────────────

// seedProviders registers the default three-provider topology.
func seedProviders(reg *router.Registry) {
	_ = reg.Register(&router.Provider{
		ID:           "9b-cpu",
		Name:         "Ornith-1.0-9B (CPU)",
		Model:        "ornith-1.0-9b",
		Status:       router.StatusOnline,
		Hardware:     router.HardwareCPU,
		Priority:     10,
		Endpoint:     "http://127.0.0.1:8080",
		Capabilities: []string{"chat", "code"},
	})
	_ = reg.Register(&router.Provider{
		ID:           "35b-gpu",
		Name:         "Omima-35B-LoRA (GPU ECS)",
		Model:        "omima-35b-lora",
		Status:       router.StatusOffline,
		Hardware:     router.HardwareGPU,
		Priority:     20,
		Endpoint:     "http://gpu-ecs:8080",
		Capabilities: []string{"chat", "code", "vddg"},
		HealthURL:    "http://gpu-ecs:8080/health",
		BootCommand:  os.Getenv("ROUTER_35B_BOOT_CMD"), // e.g. ssh root@gpu-ecs "systemctl start omima-35b"
		BootTimeout:  60 * time.Second,
	})
	_ = reg.Register(&router.Provider{
		ID:           "deepseek",
		Name:         "DeepSeek V4 Flash API",
		Model:        "deepseek-v4-flash",
		Status:       router.StatusOnline,
		Hardware:     router.HardwareAPI,
		Priority:     90,
		Endpoint:     "https://api.deepseek.com",
		Capabilities: []string{"chat", "code", "reasoning"},
	})
	slog.Info("router: seeded default providers", "count", 3)
}

// registerRouterRoutes wires the Model Router HTTP API onto the gateway mux.
func registerRouterRoutes(mux *http.ServeMux, reg *router.Registry, booter *router.Booter, disp *router.Dispatcher, ho *router.HandoffManager) {

	// GET /providers — list all providers.
	mux.HandleFunc("GET /providers", func(w http.ResponseWriter, r *http.Request) {
		providers := reg.ListAll()
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status":    "ok",
			"providers": providers,
			"count":     len(providers),
		})
	})

	// GET /providers/online — list only online providers.
	mux.HandleFunc("GET /providers/online", func(w http.ResponseWriter, r *http.Request) {
		providers := reg.ListOnline()
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status":    "ok",
			"providers": providers,
			"count":     len(providers),
		})
	})

	// POST /providers/register — register a new provider.
	mux.HandleFunc("POST /providers/register", func(w http.ResponseWriter, r *http.Request) {
		var p router.Provider
		if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		if err := reg.Register(&p); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"status": "registered", "provider": p})
	})

	// POST /providers/unregister — remove a provider.
	mux.HandleFunc("POST /providers/unregister", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			ID string `json:"id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.ID == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "id is required"})
			return
		}
		if !reg.Unregister(req.ID) {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "provider not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "unregistered", "id": req.ID})
	})

	// GET /providers/{id} — get a specific provider.
	mux.HandleFunc("GET /providers/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		p := reg.Get(id)
		if p == nil {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "provider not found"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"status": "ok", "provider": p})
	})

	// POST /providers/{id}/status — update provider status.
	mux.HandleFunc("POST /providers/{id}/status", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		var req struct {
			Status string `json:"status"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Status == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "status is required"})
			return
		}
		if err := reg.UpdateStatus(id, router.ProviderStatus(req.Status)); err != nil {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "updated", "id": id, "new_status": req.Status})
	})

	// POST /providers/{id}/boot — trigger async boot.
	mux.HandleFunc("POST /providers/{id}/boot", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		if err := booter.BootAsync(r.Context(), id); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusAccepted, map[string]string{"status": "booting", "id": id})
	})

	// POST /dispatch — route a request to the best provider.
	mux.HandleFunc("POST /dispatch", func(w http.ResponseWriter, r *http.Request) {
		var req router.DispatchRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		target, err := disp.Dispatch(r.Context(), req)
		if err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]interface{}{
				"status": "degraded",
				"error":  err.Error(),
			})
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{
			"status": "routed",
			"target": target,
		})
	})

	// POST /handoff — cascade a request to the next provider.
	mux.HandleFunc("POST /handoff", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			FromProvider string `json:"from_provider"`
			ToProvider   string `json:"to_provider"` // optional: force specific target
			Context      string `json:"context"`
			Reason       string `json:"reason"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		if req.FromProvider == "" {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "from_provider is required"})
			return
		}

		var result *router.HandoffResult
		var err error
		if req.ToProvider != "" {
			result, err = ho.HandoffToSpecific(r.Context(), req.FromProvider, req.ToProvider, req.Context, req.Reason)
		} else {
			result, err = ho.Handoff(r.Context(), req.FromProvider, req.Context, req.Reason)
		}
		if err != nil && result == nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]interface{}{
				"status": "handoff_failed",
				"error":  err.Error(),
			})
			return
		}
		status := http.StatusOK
		if !result.Success {
			status = http.StatusServiceUnavailable
		}
		writeJSON(w, status, map[string]interface{}{
			"status": "handoff_result",
			"result": result,
		})
	})
}
