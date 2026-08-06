package gateway

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/konspace/unionagents-go/internal/router"
)

// AppIdentity represents a registered client or agent identity
type AppIdentity struct {
	AppID        string // unique app identifier (cli_xxxx or agent_xxxx)
	Secret       string // signing secret for JWT generation
	Type         string // "client" or "agent"
	AgentID      string // if type == "agent", the UUID of the agent
	AgentType    string // runtime label supplied by agent, e.g. reasonix/hermes
	Name         string // display name
	RegisteredAt time.Time
	ExpiresAt    time.Time
}

// DeliveryResult reports what the Gateway actually attempted on live WS connections.
type DeliveryResult struct {
	Target                 string `json:"target,omitempty"`
	TargetConnected        bool   `json:"target_connected"`
	ConnectionCount        int    `json:"connection_count"`
	DeliveredToConnections int    `json:"delivered_to_connections"`
	FailedWrites           int    `json:"failed_writes"`
}

type eventDeliveryRecord struct {
	EventID     string
	EventKey    string
	Delivered   int
	Acked       int
	Nacked      int
	Pending     int
	LastUpdated time.Time
	Consumers   map[string]string
	TargetAppID string // "" = broadcast to all OB clients
	Route       string // "agent_app", "agent_legacy", "ob_clients"
	RetryCount  int
	MaxRetries  int
	CreatedAt   time.Time
}

type EventKeyStatus struct {
	EventKey    string `json:"event_key"`
	LastEventID string `json:"last_event_id,omitempty"`
	Delivered   int    `json:"delivered"`
	Acked       int    `json:"acked"`
	Nacked      int    `json:"nacked"`
	Pending     int    `json:"pending"`
}

type ConnectionStatus struct {
	ConnectionID string    `json:"connection_id"`
	ConsumerID   string    `json:"consumer_id"`
	AppID        string    `json:"app_id,omitempty"`
	Kind         string    `json:"kind"`
	AgentID      string    `json:"agent_id,omitempty"`
	AgentType    string    `json:"agent_type,omitempty"`
	Ready        bool      `json:"ready"`
	ReadyType    string    `json:"ready_type,omitempty"`
	ConnectedAt  time.Time `json:"connected_at"`
	ReadyAt      time.Time `json:"ready_at,omitempty"`
	LastSeenAt   time.Time `json:"last_seen_at"`
}

type bufferedEvent struct {
	EventID  string
	EventKey string
	Payload  json.RawMessage
	StoredAt time.Time
	Seq      int64 // global monotonic sequence number
}

// globalSeq is the gateway-wide monotonically increasing message counter.
// Every /chat message receives the next seq, enabling ordered replay.
var globalSeq atomic.Int64

// NextSeq returns the next global sequence number.
func NextSeq() int64 {
	return globalSeq.Add(1)
}

var (
	upgrader = websocket.Upgrader{
		ReadBufferSize:  1024,
		WriteBufferSize: 1024,
		CheckOrigin:     func(r *http.Request) bool { return true },
	}

	TokenTTL = 86400 // 24 hours

	// authEnabled controls whether authentication is enforced.
	authEnabled  bool
	authUsername string
	authPassword string
	authSecret   string

	// Identity registry: app_id → AppIdentity
	identityDB = &sync.Map{}

	// WebSocket registry: app_id → []*websocket.Conn
	activeConnections = &sync.Map{}

	// Agent routing: agent_id → app_id
	agentIDToAppID   = &sync.Map{}
	agentNameToAppID = &sync.Map{}

	// DB pool for identity persistence (set via InitPool)
	gatewayPool *pgxpool.Pool

	// Per-connection write mutex. gorilla/websocket allows only ONE concurrent
	// writer per connection. The ping goroutine and the broadcast paths
	// (BroadcastToAllClients / BroadcastToApp / BroadcastToAgent / DispatchTask)
	// otherwise write the same conn concurrently → corrupted frames → the
	// connection errors out and drops. All writes MUST go through safeWrite*.
	connWriteMu = &sync.Map{} // *websocket.Conn → *sync.Mutex

	eventMu       sync.Mutex
	eventDelivery = map[string]*eventDeliveryRecord{}
	eventBuffer   []bufferedEvent

	connectionMu     sync.Mutex
	connectionStatus = map[string]*ConnectionStatus{}
	connToID         = &sync.Map{} // *websocket.Conn → connection_id

	// agentKeys holds one-time registration keys: agent_id → sha256(key) hex.
	// A key is minted by GenerateAgentKey, proven once via ValidateAgentKey at
	// /register/agent time, then consumed (deleted) so it cannot be reused.
	agentKeys = &sync.Map{}
)

const (
	maxBufferedEvents = 100
	eventBufferTTL    = 5 * time.Minute
)

// roomMgr is the RoomManager for agent presence tracking (Phase 5).
// Injected via InitRoom from cmd/gateway so WS connect/disconnect updates the room.
var roomMgr *router.RoomManager

// InitRoom injects the RoomManager so connection lifecycle handlers can Join/Leave.
func InitRoom(r *router.RoomManager) {
	roomMgr = r
}

var connIDToConn = &sync.Map{} // connection_id -> *websocket.Conn

func connMutex(c *websocket.Conn) *sync.Mutex {
	mu, _ := connWriteMu.LoadOrStore(c, &sync.Mutex{})
	return mu.(*sync.Mutex)
}

// safeWrite serializes WriteMessage per connection.
func safeWrite(c *websocket.Conn, messageType int, data []byte) error {
	mu := connMutex(c)
	mu.Lock()
	defer mu.Unlock()
	c.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.WriteMessage(messageType, data)
}

// safeWriteJSON serializes WriteJSON per connection.
func safeWriteJSON(c *websocket.Conn, v interface{}) error {
	mu := connMutex(c)
	mu.Lock()
	defer mu.Unlock()
	c.SetWriteDeadline(time.Now().Add(10 * time.Second))
	return c.WriteJSON(v)
}

func newConnectionID() string {
	return "conn_" + randString(16)
}

func appIdentity(appID string) *AppIdentity {
	if appID == "" {
		return nil
	}
	if val, ok := identityDB.Load(appID); ok {
		return val.(*AppIdentity)
	}
	return nil
}

func appIdentityAgentType(appID string) string {
	if identity := appIdentity(appID); identity != nil {
		return identity.AgentType
	}
	return ""
}

func registerConnection(conn *websocket.Conn, consumerID, appID, kind, agentID string) string {
	connectionID := newConnectionID()
	now := time.Now().UTC()
	agentType := ""
	if identity := appIdentity(appID); identity != nil {
		agentType = identity.AgentType
	}
	connToID.Store(conn, connectionID)
	connIDToConn.Store(connectionID, conn)
	connectionMu.Lock()
	connectionStatus[connectionID] = &ConnectionStatus{
		ConnectionID: connectionID,
		ConsumerID:   consumerID,
		AppID:        appID,
		Kind:         kind,
		AgentID:      agentID,
		AgentType:    agentType,
		ConnectedAt:  now,
		LastSeenAt:   now,
	}
	connectionMu.Unlock()
	return connectionID
}

func markConnectionSeen(connectionID string) {
	connectionMu.Lock()
	defer connectionMu.Unlock()
	if rec := connectionStatus[connectionID]; rec != nil {
		rec.LastSeenAt = time.Now().UTC()
	}
}

func markConnectionReady(connectionID, readyType string) {
	connectionMu.Lock()
	defer connectionMu.Unlock()
	if rec := connectionStatus[connectionID]; rec != nil {
		rec.Ready = true
		rec.ReadyType = readyType
		rec.ReadyAt = time.Now().UTC()
		rec.LastSeenAt = rec.ReadyAt
	}
}

func removeConnectionStatus(conn *websocket.Conn) {
	if val, ok := connToID.LoadAndDelete(conn); ok {
		connIDToConn.Delete(val.(string))
		connectionMu.Lock()
		delete(connectionStatus, val.(string))
		connectionMu.Unlock()
	}
}

func StartConnectionSweeper(ctx context.Context, interval, staleAfter time.Duration) {
	if interval <= 0 {
		interval = 30 * time.Second
	}
	if staleAfter <= 0 {
		staleAfter = 3 * time.Minute
	}
	ticker := time.NewTicker(interval)
	go func() {
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				sweepStaleConnections(staleAfter)
			}
		}
	}()
}

func sweepStaleConnections(staleAfter time.Duration) {
	cutoff := time.Now().UTC().Add(-staleAfter)
	type staleConn struct {
		connectionID string
		consumerID   string
		conn         *websocket.Conn
		lastSeenAt   time.Time
	}
	stale := make([]staleConn, 0)

	connectionMu.Lock()
	for connectionID, rec := range connectionStatus {
		if rec.LastSeenAt.Before(cutoff) {
			if val, ok := connIDToConn.Load(connectionID); ok {
				stale = append(stale, staleConn{
					connectionID: connectionID,
					consumerID:   rec.ConsumerID,
					conn:         val.(*websocket.Conn),
					lastSeenAt:   rec.LastSeenAt,
				})
			}
		}
	}
	connectionMu.Unlock()

	for _, item := range stale {
		slog.Warn("closing stale ws connection", "connection_id", item.connectionID, "consumer", item.consumerID, "last_seen_at", item.lastSeenAt)
		item.conn.Close()
		removeConnection(item.consumerID, item.conn)
		removeConnectionStatus(item.conn)
	}
}

func ConnectionStatusSnapshot() []ConnectionStatus {
	connectionMu.Lock()
	defer connectionMu.Unlock()
	out := make([]ConnectionStatus, 0, len(connectionStatus))
	for _, rec := range connectionStatus {
		out = append(out, *rec)
	}
	return out
}

// InitPool stores the DB pool for identity persistence.
func InitPool(p *pgxpool.Pool) {
	gatewayPool = p
}

// LoadIdentitiesFromDB restores agent identity mappings from PostgreSQL on startup.
// Recovers identityDB and agentIDToAppID so in-flight agents don't need to re-register
// after a Gateway restart.
func LoadIdentitiesFromDB(ctx context.Context) {
	if gatewayPool == nil {
		return
	}
	rows, err := gatewayPool.Query(ctx,
		`SELECT agent_id, app_id, agent_name, secret, registered_at, expires_at
		 FROM gateway_agent_identities
		 WHERE expires_at > now()`)
	if err != nil {
		slog.Warn("load agent identities from db", "err", err)
		return
	}
	defer rows.Close()

	count := 0
	for rows.Next() {
		var agentID, appID, agentName, secret string
		var registeredAt, expiresAt time.Time
		if err := rows.Scan(&agentID, &appID, &agentName, &secret, &registeredAt, &expiresAt); err != nil {
			slog.Warn("scan agent identity row", "err", err)
			continue
		}
		identity := &AppIdentity{
			AppID:        appID,
			Secret:       secret,
			Type:         "agent",
			AgentID:      agentID,
			AgentType:    "unknown",
			Name:         agentName,
			RegisteredAt: registeredAt,
			ExpiresAt:    expiresAt,
		}
		identityDB.Store(appID, identity)
		agentIDToAppID.Store(agentID, appID)
		agentNameToAppID.Store(agentName, appID)
		count++
	}
	slog.Info("gateway identities loaded from db", "count", count)
}

// InitAuth reads auth configuration from environment variables.
func InitAuth() {
	authEnabled = os.Getenv("AUTH_ENABLED") != "0"
	authUsername = envDefault("AUTH_USERNAME", "admin")
	authPassword = os.Getenv("AUTH_PASSWORD")
	authSecret = os.Getenv("AUTH_SECRET")

	if authEnabled && (authPassword == "" || authSecret == "") {
		slog.Error("AUTH_ENABLED=1 but AUTH_PASSWORD or AUTH_SECRET is not set")
		os.Exit(1)
	}
}

// Login rate limiting: bounded in-memory failure counter per client key
// (caller passes the remote IP). /auth/login had no throttling at all
// (2026-07-07 audit) — unlimited password guesses against the one admin
// account. maxLoginAttempts failures within loginLockoutWindow locks that key
// out for the rest of the window; a successful login resets its counter.
const (
	maxLoginAttempts   = 5
	loginLockoutWindow = 5 * time.Minute
)

type loginAttemptState struct {
	mu          sync.Mutex
	count       int
	windowStart time.Time
}

var loginAttempts = &sync.Map{} // clientKey (string) -> *loginAttemptState

func loginRateLimited(clientKey string) bool {
	if clientKey == "" {
		clientKey = "unknown"
	}
	val, _ := loginAttempts.LoadOrStore(clientKey, &loginAttemptState{})
	st := val.(*loginAttemptState)
	st.mu.Lock()
	defer st.mu.Unlock()
	if time.Since(st.windowStart) > loginLockoutWindow {
		st.count = 0
		st.windowStart = time.Now()
	}
	return st.count >= maxLoginAttempts
}

func recordLoginFailure(clientKey string) {
	if clientKey == "" {
		clientKey = "unknown"
	}
	val, _ := loginAttempts.LoadOrStore(clientKey, &loginAttemptState{})
	st := val.(*loginAttemptState)
	st.mu.Lock()
	defer st.mu.Unlock()
	if st.count == 0 {
		st.windowStart = time.Now()
	}
	st.count++
}

func recordLoginSuccess(clientKey string) {
	if clientKey == "" {
		clientKey = "unknown"
	}
	loginAttempts.Delete(clientKey)
}

// Login verifies credentials and returns a signed token. clientKey (typically
// the caller's remote IP) is used purely for rate limiting; pass "" to fall
// back to a single shared bucket.
func Login(clientKey, username, password string) (string, error) {
	if !authEnabled {
		return generateToken(), nil
	}
	if loginRateLimited(clientKey) {
		return "", fmt.Errorf("too many failed login attempts, try again later")
	}
	// Constant-time comparison: a plain == here leaks a timing signal on how
	// many leading bytes of the password guess matched (2026-07-07 audit).
	usernameOK := subtle.ConstantTimeCompare([]byte(username), []byte(authUsername)) == 1
	passwordOK := subtle.ConstantTimeCompare([]byte(password), []byte(authPassword)) == 1
	if usernameOK && passwordOK {
		recordLoginSuccess(clientKey)
		return generateToken(), nil
	}
	recordLoginFailure(clientKey)
	return "", fmt.Errorf("invalid credentials")
}

// LoginClient verifies admin credentials and optionally creates an identity-backed
// client session. Legacy callers pass an empty agentID and receive the old admin
// JWT. OB/cockpit callers pass agentID so replies can route back through
// agentIDToAppID and the app_id-authenticated WebSocket path.
func LoginClient(clientKey, username, password, name, agentID string) (*AppIdentity, string, error) {
	if agentID == "" {
		token, err := Login(clientKey, username, password)
		return nil, token, err
	}
	if _, err := Login(clientKey, username, password); err != nil {
		return nil, "", err
	}
	if name == "" {
		name = agentID
	}
	return RegisterClient(name, agentID)
}

// VerifyToken checks a token against HMAC signature and DB persistence.
func VerifyToken(ctx context.Context, pool *pgxpool.Pool, token string) bool {
	if token == "" {
		return false
	}

	if !verifyHMAC(token) {
		return false
	}

	if pool == nil {
		return true
	}

	// Check/refresh in DB
	expiresAt := time.Now().UTC().Add(time.Duration(TokenTTL) * time.Second)
	_, err := pool.Exec(ctx,
		`INSERT INTO active_tokens (token, expires_at) VALUES ($1, $2)
		 ON CONFLICT (token) DO UPDATE SET expires_at = $2, updated_at = now()`,
		token, expiresAt)
	if err != nil {
		slog.Warn("token db insert", "err", err)
	}

	// Cleanup expired tokens periodically
	pool.Exec(ctx, `SELECT cleanup_expired_tokens()`)

	return true
}

// Logout revokes a token.
func Logout(ctx context.Context, pool *pgxpool.Pool, token string) {
	if pool != nil {
		pool.Exec(ctx, `DELETE FROM active_tokens WHERE token = $1`, token)
	}
}

// ExtractToken pulls a Bearer token from the request.
func ExtractToken(r *http.Request) string {
	auth := r.Header.Get("Authorization")
	if len(auth) > 7 && auth[:7] == "Bearer " {
		return auth[7:]
	}
	return r.URL.Query().Get("token")
}

// AuthMiddleware is an HTTP middleware that enforces token authentication.
//
// 2026-07-07 audit: /broadcast, /chat, /api/gateway/chat, /events/status,
// /events/replay, /events/ack, and /register/client used to be blanket-exempt
// here — anyone reaching the port could inject chat messages, forge task
// dispatch, or read/ack event history with zero credentials. /register/client
// stays exempt (it's the bootstrap enrollment call, callers have no token yet
// by definition — see registerClientAuthCheck in cmd/gateway for its own,
// separate opt-in secret gate). The rest now require a token: /broadcast is
// genuinely orchestrator-only, so it stays admin-token-scoped (VerifyToken).
// /chat and the /events/* endpoints are called by registered clients/agents
// using their own RegisterClient/RegisterAgent token (confirmed against the
// real gatewayclient package: ChatSend/FetchAgents already send
// "Authorization: Bearer <token>" using that per-identity token today) — those
// must use verifyAnyKnownToken, not VerifyToken, or every real caller's own
// token would be rejected.
func AuthMiddleware(pool *pgxpool.Pool) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !authEnabled {
				next.ServeHTTP(w, r)
				return
			}

			path := r.URL.Path
			// Public by design: login itself, health/boundary probes, static
			// downloads, CORS preflight, and the bootstrap enrollment calls
			// (register client/agent plus the one-time agent-key mint — all
			// pre-token by definition).
			if path == "/auth/login" || path == "/health" || path == "/boundary" || path == "/register/client" || path == "/register/agent" || path == "/register/agent/generate-key" || strings.HasPrefix(path, "/download/") || r.Method == "OPTIONS" {
				next.ServeHTTP(w, r)
				return
			}

			token := ExtractToken(r)

			if path == "/chat" || path == "/api/gateway/chat" || path == "/events/status" || path == "/events/replay" || path == "/events/ack" {
				if !verifyAnyKnownToken(token) {
					http.Error(w, `{"detail":"Missing or invalid token"}`, http.StatusUnauthorized)
					return
				}
				next.ServeHTTP(w, r)
				return
			}

			if !VerifyToken(r.Context(), pool, token) {
				http.Error(w, `{"detail":"Missing or invalid token"}`, http.StatusUnauthorized)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}

// HandleAgentOutput handles WebSocket upgrades for agent output streaming.
func HandleAgentOutput(w http.ResponseWriter, r *http.Request, pool *pgxpool.Pool, agentID string) {
	if authEnabled {
		token := ExtractToken(r)
		if !verifyAgentOutputAccess(agentID, token) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
	}

	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		slog.Error("ws upgrade", "agent", agentID, "err", err)
		return
	}
	connectionID := registerConnection(conn, agentID, "", "agent", agentID)

	// Phase 5: Join the RoomManager so /agents/status reflects this connection.
	if roomMgr != nil {
		roomMgr.Join(agentID, agentID, "", connectionID)
	}

	// Track connection
	conns, _ := activeConnections.LoadOrStore(agentID, []*websocket.Conn{})
	connList := conns.([]*websocket.Conn)
	connList = append(connList, conn)
	activeConnections.Store(agentID, connList)

	slog.Info("ws connected", "agent", agentID, "total", len(connList))
	safeWriteJSON(conn, map[string]interface{}{
		"type":           "server:welcome",
		"connection_id":  connectionID,
		"consumer_id":    agentID,
		"kind":           "agent",
		"agent_id":       agentID,
		"agent_type":     appIdentityAgentType(""),
		"ready_required": true,
	})

	// Read loop — keep connection alive and handle incoming messages
	go func() {
		defer func() {
			conn.Close()
			removeConnection(agentID, conn)
			removeConnectionStatus(conn)
			if roomMgr != nil {
				roomMgr.Leave(agentID)
			}
		}()

		conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		conn.SetPongHandler(func(string) error {
			conn.SetReadDeadline(time.Now().Add(60 * time.Second))
			markConnectionSeen(connectionID)
			return nil
		})

		for {
			_, msg, err := conn.ReadMessage()
			if err != nil {
				if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
					slog.Warn("ws read error", "agent", agentID, "err", err)
				}
				return
			}
			markConnectionSeen(connectionID)
			handleWSControlMessage(agentID, msg)
			slog.Info("ws message", "agent", agentID, "msg", string(msg))
		}
	}()

	// Send ping every 30 seconds
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			if err := safeWrite(conn, websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}()
}

// BroadcastToAgent sends a message to all WebSocket connections for an agent.
func BroadcastToAgent(agentID string, message []byte) DeliveryResult {
	result := DeliveryResult{Target: agentID}
	conns, ok := activeConnections.Load(agentID)
	if !ok {
		return result
	}
	list := conns.([]*websocket.Conn)
	result.ConnectionCount = len(list)
	result.TargetConnected = result.ConnectionCount > 0
	for _, c := range list {
		if err := safeWrite(c, websocket.TextMessage, message); err != nil {
			result.FailedWrites++
			slog.Warn("ws write error", "agent", agentID, "err", err)
			continue
		}
		result.DeliveredToConnections++
	}
	return result
}

// DispatchTask notifies an agent about a new task via WebSocket.
func DispatchTask(agentID string, taskData map[string]interface{}) error {
	conns, ok := activeConnections.Load(agentID)
	if !ok {
		return fmt.Errorf("agent %s not connected", agentID)
	}

	// payload, _ := json.Marshal(taskData)
	// BroadcastToAgent handles the write
	list := conns.([]*websocket.Conn)
	if len(list) == 0 {
		return fmt.Errorf("agent %s has no active connections", agentID)
	}

	for _, c := range list {
		if err := safeWriteJSON(c, taskData); err != nil {
			slog.Warn("ws dispatch error", "agent", agentID, "err", err)
		}
	}
	return nil
}

func removeConnection(id string, conn *websocket.Conn) {
	connWriteMu.Delete(conn) // release the per-connection write mutex
	conns, ok := activeConnections.Load(id)
	if !ok {
		return
	}
	list := conns.([]*websocket.Conn)
	newList := make([]*websocket.Conn, 0, len(list)-1)
	for _, c := range list {
		if c != conn {
			newList = append(newList, c)
		}
	}
	if len(newList) == 0 {
		activeConnections.Delete(id)
		slog.Info("ws disconnected", "id", id, "remaining", 0)
	} else {
		activeConnections.Store(id, newList)
		slog.Info("ws disconnected", "id", id, "remaining", len(newList))
	}
}

// ── Identity registration ──────────────────────────────────────────────────

// RegisterClient creates a new client identity and returns app_id + secret + token
func RegisterClient(name, agentID string) (*AppIdentity, string, error) {
	appID := "cli_" + randString(16)
	secret := randString(32)

	identity := &AppIdentity{
		AppID:        appID,
		Secret:       secret,
		Type:         "client",
		AgentID:      agentID,
		Name:         name,
		RegisteredAt: time.Now().UTC(),
		ExpiresAt:    time.Now().UTC().Add(time.Duration(TokenTTL) * time.Second),
	}

	identityDB.Store(appID, identity)
	if agentID != "" {
		agentIDToAppID.Store(agentID, appID)
		if name != "" {
			agentNameToAppID.Store(name, appID)
		}
	}

	token := generateTokenForAppID(appID, secret)
	return identity, token, nil
}

// RegisterAgent creates a new agent identity and returns app_id + secret + token
func RegisterAgent(agentID, agentName, agentType string) (*AppIdentity, string, error) {
	appID := "agent_" + randString(16)
	secret := randString(32)
	agentType = normalizeAgentType(agentType)

	identity := &AppIdentity{
		AppID:        appID,
		Secret:       secret,
		Type:         "agent",
		AgentID:      agentID,
		AgentType:    agentType,
		Name:         agentName,
		RegisteredAt: time.Now().UTC(),
		ExpiresAt:    time.Now().UTC().Add(time.Duration(TokenTTL) * time.Second),
	}

	identityDB.Store(appID, identity)

	// Record agent_id → app_id mapping for broadcast routing
	agentIDToAppID.Store(agentID, appID)
	if agentName != "" {
		agentNameToAppID.Store(agentName, appID)
	}

	// Persist to DB so the mapping survives Gateway restarts
	if gatewayPool != nil {
		_, err := gatewayPool.Exec(context.Background(),
			`INSERT INTO gateway_agent_identities (agent_id, app_id, agent_name, secret, expires_at)
			 VALUES ($1, $2, $3, $4, $5)
			 ON CONFLICT (agent_id) DO UPDATE SET
			     app_id = EXCLUDED.app_id,
			     agent_name = EXCLUDED.agent_name,
			     secret = EXCLUDED.secret,
			     expires_at = EXCLUDED.expires_at,
			     updated_at = now()`,
			agentID, appID, agentName, secret, identity.ExpiresAt,
		)
		if err != nil {
			slog.Warn("persist agent identity", "agent_id", agentID, "err", err)
		}
	}

	token := generateTokenForAppID(appID, secret)
	return identity, token, nil
}

func normalizeAgentType(agentType string) string {
	agentType = strings.ToLower(strings.TrimSpace(agentType))
	if agentType == "" || agentType == "agent" {
		return "generic"
	}
	var b strings.Builder
	for _, r := range agentType {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '_' || r == '-' {
			b.WriteRune(r)
		}
	}
	out := b.String()
	if out == "" {
		return "generic"
	}
	if len(out) > 64 {
		return out[:64]
	}
	return out
}

// VerifyAppIDToken verifies that a token is valid for the given app_id
func VerifyAppIDToken(appID, token string) bool {
	if appID == "" || token == "" {
		return false
	}

	idVal, ok := identityDB.Load(appID)
	if !ok {
		return false
	}

	identity := idVal.(*AppIdentity)
	return verifyTokenForAppID(appID, token, identity.Secret)
}

// verifyAnyKnownToken accepts either the admin token (verifyHMAC) or a
// per-identity token for any currently registered app_id. Endpoints that are
// called by registered clients/agents using their own RegisterClient/
// RegisterAgent token (not the admin login token) — e.g. /chat, /events/status —
// must use this instead of VerifyToken, which only accepts the admin secret
// and would otherwise reject every real client's own token (2026-07-07 audit:
// this gap is why those endpoints were previously left unauthenticated
// entirely, rather than actually broken-but-protected).
func verifyAnyKnownToken(token string) bool {
	if token == "" {
		return false
	}
	if verifyHMAC(token) {
		return true
	}
	matched := false
	identityDB.Range(func(_, val any) bool {
		identity, ok := val.(*AppIdentity)
		if !ok {
			return true
		}
		if verifyTokenForAppID(identity.AppID, token, identity.Secret) {
			matched = true
			return false
		}
		return true
	})
	return matched
}

// verifyAgentOutputAccess reports whether token grants access to agentID's
// output stream: either the admin token, or a per-identity token whose own
// AgentID matches the requested one. Fixes a broken-object-level-authorization
// gap where any valid token (for any identity) could subscribe to any other
// agent's output (2026-07-07 audit).
func verifyAgentOutputAccess(agentID, token string) bool {
	if token == "" {
		return false
	}
	if verifyHMAC(token) {
		return true
	}
	if agentID == "" {
		return false
	}
	granted := false
	identityDB.Range(func(_, val any) bool {
		identity, ok := val.(*AppIdentity)
		if !ok || identity.AgentID != agentID {
			return true
		}
		if verifyTokenForAppID(identity.AppID, token, identity.Secret) {
			granted = true
			return false
		}
		return true
	})
	return granted
}

// ── Token utilities ────────────────────────────────────────────────────

func generateToken() string {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	sig := hmacSHA256(authSecret, ts)[:16]
	return fmt.Sprintf("%s:%s", ts, sig)
}

// generateTokenForAppID creates a token signed with the app's secret
func generateTokenForAppID(appID, secret string) string {
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	sig := hmacSHA256(secret, appID+":"+ts)[:16]
	return fmt.Sprintf("%s:%s", ts, sig)
}

// verifyTokenForAppID verifies a token using the app's secret
func verifyTokenForAppID(appID, token, secret string) bool {
	parts := splitToken(token)
	if len(parts) != 2 {
		return false
	}
	tsStr, sig := parts[0], parts[1]
	ts, err := strconv.ParseInt(tsStr, 10, 64)
	if err != nil {
		return false
	}
	if time.Now().Unix()-ts > int64(TokenTTL) {
		return false
	}
	expected := hmacSHA256(secret, appID+":"+tsStr)[:16]
	return hmac.Equal([]byte(sig), []byte(expected))
}

func verifyHMAC(token string) bool {
	parts := splitToken(token)
	if len(parts) != 2 {
		return false
	}
	tsStr, sig := parts[0], parts[1]
	ts, err := strconv.ParseInt(tsStr, 10, 64)
	if err != nil {
		return false
	}
	if time.Now().Unix()-ts > int64(TokenTTL) {
		return false
	}
	expected := hmacSHA256(authSecret, tsStr)[:16]
	return hmac.Equal([]byte(sig), []byte(expected))
}

func hmacSHA256(key, data string) string {
	h := hmac.New(sha256.New, []byte(key))
	h.Write([]byte(data))
	return hex.EncodeToString(h.Sum(nil))
}

func splitToken(token string) []string {
	for i := 0; i < len(token); i++ {
		if token[i] == ':' {
			return []string{token[:i], token[i+1:]}
		}
	}
	return []string{token}
}

func envDefault(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// randString generates a cryptographically-secure random alphanumeric string.
// Used to mint per-identity signing secrets and app_ids — a predictable generator
// here would let an attacker forge tokens for any app_id and impersonate agents/clients.
func randString(length int) string {
	const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
	b := make([]byte, length)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand should never fail; if it does, fail loud rather than emit weak secrets.
		panic(fmt.Sprintf("crypto/rand failed: %v", err))
	}
	for i := range b {
		b[i] = charset[int(b[i])%len(charset)]
	}
	return string(b)
}

// HandleClientWS handles WebSocket connections from OB/Cockpit clients.
// appID is optional (for new identity-based auth), falls back to connection-based ID.
func HandleClientWS(w http.ResponseWriter, r *http.Request, appID string) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		slog.Error("ws upgrade (client)", "err", err)
		return
	}

	// Use app_id if provided, otherwise fall back to connection-based ID
	clientID := appID
	if clientID == "" {
		clientID = "client-" + fmt.Sprintf("%p", conn)
	}
	kind := "client"
	agentID := ""
	if identity := appIdentity(appID); identity != nil {
		kind = identity.Type
		agentID = identity.AgentID
	}
	connectionID := registerConnection(conn, clientID, appID, kind, agentID)

	// Phase 5: Join the RoomManager for agent connections so /agents/status tracks them.
	if roomMgr != nil && agentID != "" {
		name := ""
		atype := ""
		if id := appIdentity(appID); id != nil {
			name = id.Name
			atype = id.AgentType
		}
		roomMgr.Join(agentID, name, atype, connectionID)
	}

	conns, _ := activeConnections.LoadOrStore(clientID, []*websocket.Conn{})
	connList := conns.([]*websocket.Conn)
	connList = append(connList, conn)
	activeConnections.Store(clientID, connList)

	// Also register under the logical agent_id (distinct from clientID, which
	// is this connection's own app_id) so DispatchTask's activeConnections.Load(agentID)
	// can find it. Without this, any identity-based agent connecting through
	// this general /ws endpoint (H5/H6 and similar ils-based agents) is
	// dispatchable-unreachable forever, even though /events/status correctly
	// shows it as kind=agent/ready=true — the two code paths were reading
	// from the same map but only HandleAgentOutput (/agents/{id}/output) was
	// writing to it under the agentID key.
	if agentID != "" && agentID != clientID {
		aconns, _ := activeConnections.LoadOrStore(agentID, []*websocket.Conn{})
		aList := aconns.([]*websocket.Conn)
		aList = append(aList, conn)
		activeConnections.Store(agentID, aList)
	}

	slog.Info("client ws connected", "id", clientID)

	// Send welcome message
	safeWriteJSON(conn, map[string]interface{}{
		"type":           "server:welcome",
		"connection_id":  connectionID,
		"consumer_id":    clientID,
		"app_id":         appID,
		"kind":           kind,
		"agent_id":       agentID,
		"agent_type":     appIdentityAgentType(appID),
		"ready_required": true,
	})

	// Read loop — keep connection alive
	go func() {
		defer func() {
			conn.Close()
			removeConnection(clientID, conn)
			if agentID != "" && agentID != clientID {
				removeConnection(agentID, conn)
			}
			removeConnectionStatus(conn)
			if roomMgr != nil && agentID != "" {
				roomMgr.Leave(agentID)
			}
			slog.Info("client ws disconnected", "id", clientID)
		}()

		conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		conn.SetPongHandler(func(string) error {
			conn.SetReadDeadline(time.Now().Add(60 * time.Second))
			markConnectionSeen(connectionID)
			return nil
		})

		for {
			_, msg, err := conn.ReadMessage()
			if err != nil {
				if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseNormalClosure) {
					slog.Warn("client ws read error", "id", clientID, "err", err)
				}
				return
			}
			markConnectionSeen(connectionID)
			handleWSControlMessage(clientID, msg)
		}
	}()

	// Send ping every 30 seconds
	go func() {
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			if err := safeWrite(conn, websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}()
}

// BroadcastToAllClients sends a message to all connected OB clients (not agents).
// Only broadcasts to keys starting with "cli_" (client app_ids).
func BroadcastToAllClients(message []byte) DeliveryResult {
	result := DeliveryResult{Target: "ob_clients"}
	activeConnections.Range(func(key, value interface{}) bool {
		keyStr := key.(string)
		// Only broadcast to client connections (app_id starts with "cli_" or legacy "client-")
		if !strings.HasPrefix(keyStr, "cli_") && !strings.HasPrefix(keyStr, "client-") {
			return true // Skip agent connections
		}
		conns := value.([]*websocket.Conn)
		result.ConnectionCount += len(conns)
		for _, c := range conns {
			if err := safeWrite(c, websocket.TextMessage, message); err != nil {
				result.FailedWrites++
				slog.Debug("ws broadcast write error", "err", err)
				continue
			}
			result.DeliveredToConnections++
		}
		return true
	})
	result.TargetConnected = result.ConnectionCount > 0
	return result
}

// BroadcastToAll sends a message to all connected WebSocket clients (both agents and OB).
func BroadcastToAll(message []byte) DeliveryResult {
	result := DeliveryResult{Target: "all"}
	activeConnections.Range(func(key, value interface{}) bool {
		conns := value.([]*websocket.Conn)
		result.ConnectionCount += len(conns)
		for _, c := range conns {
			if err := safeWrite(c, websocket.TextMessage, message); err != nil {
				result.FailedWrites++
				slog.Debug("ws broadcast all write error", "err", err)
				continue
			}
			result.DeliveredToConnections++
		}
		return true
	})
	result.TargetConnected = result.ConnectionCount > 0
	return result
}

// GetAgentAppID retrieves the app_id for a given agent_id or agent_name.
func GetAgentAppID(agentID string) string {
	val, ok := agentIDToAppID.Load(agentID)
	if ok {
		return val.(string)
	}
	if val, ok := agentNameToAppID.Load(agentID); ok {
		return val.(string)
	}
	return ""
}

// ResolveAgentID resolves an agent name or UUID to the canonical agent_id (UUID).
// If the input is already a UUID (found in agentIDToAppID), it's returned as-is.
// If it's a name (found in agentNameToAppID), the corresponding AppIdentity's
// AgentID (UUID) is returned. Returns empty string if not found.
func ResolveAgentID(nameOrUUID string) string {
	// First check if it's already a UUID
	if _, ok := agentIDToAppID.Load(nameOrUUID); ok {
		return nameOrUUID
	}
	// Try name lookup → app_id → identity → agent_id
	if val, ok := agentNameToAppID.Load(nameOrUUID); ok {
		appID := val.(string)
		if id := appIdentity(appID); id != nil {
			return id.AgentID
		}
	}
	return ""
}

// BroadcastToApp sends a message to all WebSocket connections for a given app_id
func BroadcastToApp(appID string, message []byte) DeliveryResult {
	result := DeliveryResult{Target: appID}
	conns, ok := activeConnections.Load(appID)
	if !ok {
		slog.Warn("ws broadcast target not connected", "app_id", appID)
		return result
	}
	list := conns.([]*websocket.Conn)
	result.ConnectionCount = len(list)
	result.TargetConnected = result.ConnectionCount > 0
	for _, c := range list {
		if err := safeWrite(c, websocket.TextMessage, message); err != nil {
			result.FailedWrites++
			slog.Warn("ws write error", "app_id", appID, "err", err)
			continue
		}
		result.DeliveredToConnections++
	}
	return result
}

func RecordEventDelivery(eventID, eventKey string, delivered int) {
	RecordEventDeliveryRouted(eventID, eventKey, delivered, "", "")
}

func RecordEventDeliveryRouted(eventID, eventKey string, delivered int, targetAppID, route string) {
	if eventID == "" {
		return
	}
	eventMu.Lock()
	defer eventMu.Unlock()

	rec := eventDelivery[eventID]
	if rec == nil {
		now := time.Now().UTC()
		rec = &eventDeliveryRecord{
			EventID:     eventID,
			EventKey:    eventKey,
			Consumers:   map[string]string{},
			TargetAppID: targetAppID,
			Route:       route,
			MaxRetries:  3,
			CreatedAt:   now,
		}
		eventDelivery[eventID] = rec
	}
	rec.EventKey = eventKey
	if targetAppID != "" {
		rec.TargetAppID = targetAppID
	}
	if route != "" {
		rec.Route = route
	}
	rec.Delivered = delivered
	rec.Pending = delivered - rec.Acked - rec.Nacked
	if rec.Pending < 0 {
		rec.Pending = 0
	}
	rec.LastUpdated = time.Now().UTC()
}

func StoreEventForReplay(eventID, eventKey string, payload []byte) {
	StoreEventForReplaySeq(eventID, eventKey, payload, 0)
}

// StoreEventForReplaySeq stores an event with an explicit seq number.
func StoreEventForReplaySeq(eventID, eventKey string, payload []byte, seq int64) {
	if eventID == "" || len(payload) == 0 {
		return
	}
	eventMu.Lock()
	defer eventMu.Unlock()
	pruneEventBufferLocked(time.Now().UTC())
	eventBuffer = append(eventBuffer, bufferedEvent{
		EventID:  eventID,
		EventKey: eventKey,
		Payload:  append([]byte(nil), payload...),
		StoredAt: time.Now().UTC(),
		Seq:      seq,
	})
	if len(eventBuffer) > maxBufferedEvents {
		eventBuffer = eventBuffer[len(eventBuffer)-maxBufferedEvents:]
	}
}

func ReplayEventsSince(eventKey, sinceEventID string) []json.RawMessage {
	return ReplayEventsSinceSeq(eventKey, sinceEventID, 0)
}

// ReplayEventsSinceSeq returns events after sinceEventID or with seq > sinceSeq.
func ReplayEventsSinceSeq(eventKey, sinceEventID string, sinceSeq int64) []json.RawMessage {
	eventMu.Lock()
	defer eventMu.Unlock()
	pruneEventBufferLocked(time.Now().UTC())

	start := 0
	if sinceEventID != "" {
		for i, evt := range eventBuffer {
			if evt.EventID == sinceEventID {
				start = i + 1
				break
			}
		}
	}

	events := make([]json.RawMessage, 0)
	for _, evt := range eventBuffer[start:] {
		if eventKey != "" && evt.EventKey != eventKey {
			continue
		}
		// Filter by seq if provided.
		if sinceSeq > 0 && evt.Seq > 0 && evt.Seq <= sinceSeq {
			continue
		}
		events = append(events, append([]byte(nil), evt.Payload...))
		recordReplayDeliveryLocked(evt.EventID, evt.EventKey)
	}
	return events
}

func pruneEventBufferLocked(now time.Time) {
	cutoff := now.Add(-eventBufferTTL)
	keep := eventBuffer[:0]
	for _, evt := range eventBuffer {
		if evt.StoredAt.After(cutoff) {
			keep = append(keep, evt)
		}
	}
	eventBuffer = keep
}

func recordReplayDeliveryLocked(eventID, eventKey string) {
	rec := eventDelivery[eventID]
	if rec == nil {
		rec = &eventDeliveryRecord{
			EventID:   eventID,
			EventKey:  eventKey,
			Consumers: map[string]string{},
		}
		eventDelivery[eventID] = rec
	}
	rec.Delivered++
	rec.Pending = rec.Delivered - rec.Acked - rec.Nacked
	if rec.Pending < 0 {
		rec.Pending = 0
	}
	rec.LastUpdated = time.Now().UTC()
}

func EventStatusSnapshot() map[string]interface{} {
	eventMu.Lock()
	defer eventMu.Unlock()

	byKey := map[string]*EventKeyStatus{}
	for _, rec := range eventDelivery {
		key := rec.EventKey
		if key == "" {
			key = "unknown"
		}
		status := byKey[key]
		if status == nil {
			status = &EventKeyStatus{EventKey: key}
			byKey[key] = status
		}
		status.LastEventID = rec.EventID
		status.Delivered += rec.Delivered
		status.Acked += rec.Acked
		status.Nacked += rec.Nacked
		status.Pending += rec.Pending
	}

	events := make([]EventKeyStatus, 0, len(byKey))
	for _, status := range byKey {
		events = append(events, *status)
	}
	return map[string]interface{}{
		"status":      "ok",
		"events":      events,
		"connections": ConnectionStatusSnapshot(),
	}
}

func handleWSControlMessage(consumerID string, raw []byte) {
	var msg struct {
		Type         string `json:"type"`
		EventID      string `json:"event_id"`
		EventKey     string `json:"event_key"`
		Status       string `json:"status"`
		ConnectionID string `json:"connection_id"`
	}
	if err := json.Unmarshal(raw, &msg); err != nil {
		return
	}
	if msg.Type == "client.ready" || msg.Type == "agent.ready" {
		markConnectionReady(msg.ConnectionID, msg.Type)
		slog.Info("connection ready", "connection_id", msg.ConnectionID, "consumer", consumerID, "type", msg.Type)
		return
	}
	if msg.Type != "event:ack" && msg.Type != "event:nack" {
		return
	}
	if msg.Status == "" {
		if msg.Type == "event:nack" {
			msg.Status = "nack"
		} else {
			msg.Status = "ack"
		}
	}
	recordEventConsumerStatus(msg.EventID, msg.EventKey, consumerID, msg.Status)
}

func recordEventConsumerStatus(eventID, eventKey, consumerID, status string) {
	if eventID == "" || consumerID == "" {
		return
	}
	eventMu.Lock()
	defer eventMu.Unlock()

	rec := eventDelivery[eventID]
	if rec == nil {
		rec = &eventDeliveryRecord{
			EventID:   eventID,
			EventKey:  eventKey,
			Consumers: map[string]string{},
		}
		eventDelivery[eventID] = rec
	}
	if rec.EventKey == "" {
		rec.EventKey = eventKey
	}
	if prev := rec.Consumers[consumerID]; prev == status {
		return
	} else if prev == "ack" {
		rec.Acked--
	} else if prev == "nack" {
		rec.Nacked--
	}

	rec.Consumers[consumerID] = status
	if status == "nack" {
		rec.Nacked++
	} else {
		rec.Acked++
	}
	rec.Pending = rec.Delivered - rec.Acked - rec.Nacked
	if rec.Pending < 0 {
		rec.Pending = 0
	}
	rec.LastUpdated = time.Now().UTC()
	slog.Info("event consumer status", "event_id", eventID, "event_key", rec.EventKey, "consumer", consumerID, "status", status)
}

func RecordEventConsumerStatus(eventID, eventKey, consumerID, status string) {
	recordEventConsumerStatus(eventID, eventKey, consumerID, status)
}

// EventAckStatus returns the delivery/ack snapshot for a single event.
// Used by GET /events/ack/{event_id} so senders can verify delivery.
func EventAckStatus(eventID string) map[string]interface{} {
	if eventID == "" {
		return nil
	}
	eventMu.Lock()
	defer eventMu.Unlock()

	rec := eventDelivery[eventID]
	if rec == nil {
		return nil
	}
	consumers := make(map[string]string, len(rec.Consumers))
	for k, v := range rec.Consumers {
		consumers[k] = v
	}
	return map[string]interface{}{
		"event_id":     rec.EventID,
		"event_key":    rec.EventKey,
		"delivered":    rec.Delivered,
		"acked":        rec.Acked,
		"nacked":       rec.Nacked,
		"pending":      rec.Pending,
		"route":        rec.Route,
		"target_app":   rec.TargetAppID,
		"retry_count":  rec.RetryCount,
		"max_retries":  rec.MaxRetries,
		"consumers":    consumers,
		"last_updated": rec.LastUpdated.Format(time.RFC3339),
		"created_at":   rec.CreatedAt.Format(time.RFC3339),
	}
}

// ── Retry loop (Phase 1.1) ───────────────────────────────────────────

const (
	retryCheckInterval = 10 * time.Second
	retryAckTimeout    = 30 * time.Second
)

func StartRetryLoop(ctx context.Context) {
	go func() {
		ticker := time.NewTicker(retryCheckInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				retryUnackedEvents()
			}
		}
	}()
	slog.Info("retry loop started", "interval", retryCheckInterval, "ack_timeout", retryAckTimeout)
}

func retryUnackedEvents() {
	now := time.Now().UTC()
	eventMu.Lock()
	var pending []*eventDeliveryRecord
	for _, rec := range eventDelivery {
		if rec.Pending > 0 && rec.RetryCount < rec.MaxRetries && now.Sub(rec.LastUpdated) > retryAckTimeout {
			pending = append(pending, rec)
		}
	}
	eventMu.Unlock()

	for _, rec := range pending {
		payload := lookupEventPayload(rec.EventID)
		if payload == nil {
			slog.Warn("retry: payload expired from buffer", "event_id", rec.EventID)
			eventMu.Lock()
			rec.RetryCount = rec.MaxRetries // stop further retries
			eventMu.Unlock()
			continue
		}

		var delivery DeliveryResult
		switch rec.Route {
		case "agent_app":
			if rec.TargetAppID != "" {
				delivery = BroadcastToApp(rec.TargetAppID, payload)
			}
		case "ob_clients":
			delivery = BroadcastToAllClients(payload)
		default:
			slog.Warn("retry: unknown route, skipping", "event_id", rec.EventID, "route", rec.Route)
			eventMu.Lock()
			rec.RetryCount = rec.MaxRetries
			eventMu.Unlock()
			continue
		}

		eventMu.Lock()
		rec.RetryCount++
		rec.Delivered += delivery.DeliveredToConnections
		rec.Pending = rec.Delivered - rec.Acked - rec.Nacked
		if rec.Pending < 0 {
			rec.Pending = 0
		}
		rec.LastUpdated = now
		eventMu.Unlock()

		slog.Info("retry: re-sent event",
			"event_id", rec.EventID,
			"retry", rec.RetryCount,
			"max", rec.MaxRetries,
			"route", rec.Route,
			"delivered", delivery.DeliveredToConnections,
			"pending", rec.Pending,
		)

		if rec.RetryCount >= rec.MaxRetries && rec.Pending > 0 {
			slog.Warn("retry: exhausted retries, message may be lost",
				"event_id", rec.EventID,
				"pending", rec.Pending,
			)
		}
	}
}

func lookupEventPayload(eventID string) json.RawMessage {
	eventMu.Lock()
	defer eventMu.Unlock()
	for _, evt := range eventBuffer {
		if evt.EventID == eventID {
			return append(json.RawMessage(nil), evt.Payload...)
		}
	}
	return nil
}

// ── One-time agent registration keys (Phase 1A) ────────────────────────────
//
// Flow: the desktop user types a codename → GenerateAgentKey(codename) mints
// "sk-xg-<hex>" and stores sha256(key) server-side → the user hands the key to
// their Agent → the Agent calls POST /register/agent with {agent_id, key} →
// the handler validates the key (constant-time) and, on success, consumes it
// so the same key cannot register twice.
//
// Only the hash is stored; the plaintext key leaves the process once, in the
// generate-key response. A Gateway restart forgets unconsumed keys (in-memory
// sync.Map by design — unconsumed keys are short-lived bootstrap secrets).

// GenerateAgentKey mints a one-time registration key for codename.
// Returns an error if the codename is empty, already registered, or already
// has an unconsumed key outstanding.
func GenerateAgentKey(codename string) (string, error) {
	codename = strings.TrimSpace(codename)
	if codename == "" {
		return "", fmt.Errorf("codename is required")
	}
	if _, exists := agentIDToAppID.Load(codename); exists {
		return "", fmt.Errorf("codename %q is already registered", codename)
	}
	if _, exists := agentNameToAppID.Load(codename); exists {
		return "", fmt.Errorf("codename %q is already registered", codename)
	}
	if _, exists := agentKeys.Load(codename); exists {
		return "", fmt.Errorf("codename %q already has an outstanding key", codename)
	}

	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("crypto/rand failed: %w", err)
	}
	key := "sk-xg-" + hex.EncodeToString(raw)
	sum := sha256.Sum256([]byte(key))
	agentKeys.Store(codename, hex.EncodeToString(sum[:]))
	slog.Info("agent key generated", "codename", codename)
	return key, nil
}

// ValidateAgentKey reports whether key matches the outstanding one-time key
// for agentID. Comparison is constant-time on the sha256 hashes.
func ValidateAgentKey(agentID, key string) bool {
	agentID = strings.TrimSpace(agentID)
	key = strings.TrimSpace(key)
	if agentID == "" || key == "" {
		return false
	}
	stored, ok := agentKeys.Load(agentID)
	if !ok {
		return false
	}
	sum := sha256.Sum256([]byte(key))
	got := hex.EncodeToString(sum[:])
	want, ok := stored.(string)
	if !ok {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(got), []byte(want)) == 1
}

// ConsumeAgentKey deletes the outstanding key for agentID, if any. Called
// after a successful /register/agent so the key is single-use.
func ConsumeAgentKey(agentID string) {
	agentKeys.Delete(agentID)
}
