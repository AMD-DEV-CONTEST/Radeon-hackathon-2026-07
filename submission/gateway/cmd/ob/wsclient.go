package main

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// ── Message types (mirrors gateway.WSMessage) ──────────────────────────

type WSMessage struct {
	Type      string          `json:"type"`
	ID        string          `json:"id,omitempty"`
	Timestamp string          `json:"timestamp"`
	Payload   json.RawMessage `json:"payload,omitempty"`
	Raw       json.RawMessage `json:"-"` // original raw bytes for types without payload wrapper
}

// ── Callbacks ──────────────────────────────────────────────────────────

// OnMessageFunc is called for every non-control message received.
type OnMessageFunc func(msg WSMessage)

// OnReconnectFunc is called when the client starts/stops reconnecting.
type OnReconnectFunc func()

// ── Client ─────────────────────────────────────────────────────────────

// WSClient is a persistent WebSocket client that mirrors the lark_oapi
// pattern: handshake → connect → heartbeat → message loop → reconnect.
//
// Lifecycle: NewWSClient → Connect (starts supervisor) → ... → Close.
// The supervisor goroutine owns reconnects with exponential backoff.
// SendRequest blocks on a per-call response channel; pending requests
// are unblocked (with a ws disconnected error) when the connection
// drops or the client is closed.
type WSClient struct {
	serverURL string // wss://host:port/ws?token=xxx&app_id=xxx
	userAgent string

	// Connection state. Guarded by connMu.
	connMu sync.RWMutex
	conn   *websocket.Conn

	// Per-connection write mutex. gorilla/websocket forbids concurrent
	// writers on the same Conn; pingLoop, SendRequest, and the
	// connectOnce teardown all need to write. Acquire writeMu before
	// any WriteMessage / WriteControl call.
	writeMu sync.Mutex

	// Per-connection disconnect signal. closed in disconnect() so that
	// any SendRequest call waiting on the response channel is released.
	// New pending requests get a fresh signal captured at registration.
	discMu     sync.Mutex
	discSignal chan struct{} // closed when the current conn is gone
	discGen    int           // monotonic generation counter

	// Handlers
	onMessage      OnMessageFunc
	onReconnecting OnReconnectFunc
	onReconnected  OnReconnectFunc

	// Reconnect config
	reconnectInterval time.Duration // initial backoff (default 1s)
	maxBackoff        time.Duration // cap (default 60s)
	autoReconnect     bool

	// Request-response (RPC over WS)
	pending   map[string]*pendingReq
	pendingMu sync.Mutex

	// Internal
	stopCh  chan struct{}
	stopped bool
	stopMu  sync.Mutex
}

// pendingReq represents one outstanding SendRequest call.
type pendingReq struct {
	respCh chan WSMessage
	discCh chan struct{} // captured disconnect signal at registration
}

// WSClientConfig holds configuration for the WS client.
type WSClientConfig struct {
	ServerURL         string        // wss://host:port/ws
	Token             string        // JWT bearer token
	AppID             string        // optional app_id for identity-backed client routing
	UserAgent         string        // client identifier
	ReconnectInterval time.Duration // initial backoff (default 1s)
	MaxBackoff        time.Duration // cap (default 60s)
	AutoReconnect     bool          // enable reconnect (default true)
	OnMessage         OnMessageFunc
	OnReconnecting    OnReconnectFunc
	OnReconnected     OnReconnectFunc
}

// NewWSClient creates a new WebSocket client.
func NewWSClient(cfg WSClientConfig) *WSClient {
	if cfg.ReconnectInterval == 0 {
		cfg.ReconnectInterval = 1 * time.Second
	}
	if cfg.MaxBackoff == 0 {
		cfg.MaxBackoff = 60 * time.Second
	}
	if cfg.UserAgent == "" {
		cfg.UserAgent = "UAS-OB/1.0"
	}

	// Build full URL with token
	serverURL := cfg.ServerURL
	if cfg.Token != "" {
		u, err := url.Parse(serverURL)
		if err == nil {
			q := u.Query()
			q.Set("token", cfg.Token)
			if cfg.AppID != "" {
				q.Set("app_id", cfg.AppID)
			}
			u.RawQuery = q.Encode()
			serverURL = u.String()
		}
	}

	return &WSClient{
		serverURL:         serverURL,
		userAgent:         cfg.UserAgent,
		onMessage:         cfg.OnMessage,
		onReconnecting:    cfg.OnReconnecting,
		onReconnected:     cfg.OnReconnected,
		reconnectInterval: cfg.ReconnectInterval,
		maxBackoff:        cfg.MaxBackoff,
		autoReconnect:     cfg.AutoReconnect,
		pending:           make(map[string]*pendingReq),
		stopCh:            make(chan struct{}),
		discSignal:        make(chan struct{}),
	}
}

// IsConnected returns true if the WebSocket is currently connected.
func (c *WSClient) IsConnected() bool {
	c.connMu.RLock()
	defer c.connMu.RUnlock()
	return c.conn != nil
}

// currentConn returns the live connection, or nil if not ready. RL-guarded.
func (c *WSClient) currentConn() *websocket.Conn {
	c.connMu.RLock()
	defer c.connMu.RUnlock()
	return c.conn
}

// currentDiscSignal returns the disconnect signal valid for the current
// connection generation. A new generation is started on every successful
// dial, so a SendRequest registered under generation N is unblocked when
// that generation's discSignal is closed (i.e. on the next disconnect).
func (c *WSClient) currentDiscSignal() chan struct{} {
	c.discMu.Lock()
	defer c.discMu.Unlock()
	return c.discSignal
}

// bumpDiscGeneration replaces discSignal with a fresh unclosed channel.
// Called by connectOnce after a successful dial, so any SendRequest
// registered against the old generation is released.
func (c *WSClient) bumpDiscGeneration() {
	c.discMu.Lock()
	defer c.discMu.Unlock()
	c.discSignal = make(chan struct{})
	c.discGen++
}

// SendRequest sends a message and waits for a matching response (by msg ID).
// Returns the response or an error if the connection is gone or the timeout
// elapses. Pending requests are unblocked (with a "ws disconnected" error)
// when the connection drops or the client is closed — callers don't have to
// wait out the timeout.
func (c *WSClient) SendRequest(msgType string, payload interface{}, timeout time.Duration) (*WSMessage, error) {
	conn := c.currentConn()
	if conn == nil {
		return nil, fmt.Errorf("ws not connected")
	}

	reqID := generateRequestID()
	msg := WSMessage{
		Type: msgType,
		ID:   reqID,
	}
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			return nil, fmt.Errorf("marshal payload: %w", err)
		}
		msg.Payload = data
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return nil, fmt.Errorf("marshal: %w", err)
	}

	// Register pending response channel BEFORE writing, so a fast reply
	// doesn't beat the registration.
	pr := &pendingReq{
		respCh: make(chan WSMessage, 1),
		discCh: c.currentDiscSignal(),
	}
	c.pendingMu.Lock()
	c.pending[reqID] = pr
	c.pendingMu.Unlock()

	defer func() {
		c.pendingMu.Lock()
		delete(c.pending, reqID)
		c.pendingMu.Unlock()
	}()

	c.writeMu.Lock()
	conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	err = conn.WriteMessage(websocket.TextMessage, data)
	c.writeMu.Unlock()
	if err != nil {
		return nil, fmt.Errorf("ws write: %w", err)
	}

	select {
	case resp := <-pr.respCh:
		return &resp, nil
	case <-pr.discCh:
		return nil, fmt.Errorf("ws disconnected")
	case <-time.After(timeout):
		return nil, fmt.Errorf("request timeout")
	}
}

// resolveResponse routes an incoming message to a pending request if it has a matching ID.
func (c *WSClient) resolveResponse(msg WSMessage) {
	if msg.ID == "" {
		return
	}
	c.pendingMu.Lock()
	pr, ok := c.pending[msg.ID]
	c.pendingMu.Unlock()
	if !ok {
		return
	}
	select {
	case pr.respCh <- msg:
	default:
		// Pending slot already cancelled or filled; drop the response.
	}
}

// resolveOrClosePending forwards the message if there is a matching
// pending req, otherwise calls onMessage. It always returns.
func (c *WSClient) dispatchMessage(msg WSMessage) {
	c.resolveResponse(msg)
	if c.onMessage != nil {
		safeCall(func() { c.onMessage(msg) })
	}
}

// Connect dials the server once synchronously. If the initial dial
// succeeds, a supervisor goroutine is started that owns the read loop
// and reconnects on failure. If the initial dial fails, a supervisor
// is still started and will keep retrying with exponential backoff;
// callers that need to wait for first-ready can poll IsConnected.
//
// Returns nil on a successful initial dial, or the dial error otherwise.
func (c *WSClient) Connect() error {
	c.stopMu.Lock()
	if c.stopped {
		c.stopMu.Unlock()
		return fmt.Errorf("ws client closed")
	}
	c.stopMu.Unlock()

	// Pre-dial so the caller can synchronously know "are we connected".
	// The supervisor will pick up the stashed conn on its first
	// connectOnce call (when initialConn != nil).
	conn, err := c.dialOnce()
	if err != nil {
		slog.Info("ws initial dial failed, supervisor will retry", "err", err)
	} else {
		// Install the conn synchronously so IsConnected() returns true
		// right after Connect() returns nil. The supervisor's first
		// connectOnce() will see initialConn != nil and skip dialing.
		c.bumpDiscGeneration()
		c.connMu.Lock()
		c.conn = conn
		c.connMu.Unlock()
	}

	go c.run(conn)
	return err
}

// Close gracefully shuts down the client. Idempotent. Pending SendRequest
// callers are released with a "ws disconnected" error.
func (c *WSClient) Close() {
	c.stopMu.Lock()
	if c.stopped {
		c.stopMu.Unlock()
		return
	}
	c.stopped = true
	close(c.stopCh)
	c.stopMu.Unlock()

	c.disconnect()
}

func (c *WSClient) isStopped() bool {
	c.stopMu.Lock()
	defer c.stopMu.Unlock()
	return c.stopped
}

// ── Supervisor ─────────────────────────────────────────────────────────

// run is the long-lived supervisor. initialConn is the conn produced by
// Connect's pre-dial (may be nil if the pre-dial failed). On the first
// iteration we use that conn instead of dialing again; subsequent
// iterations dial fresh and apply exponential backoff.
func (c *WSClient) run(initialConn *websocket.Conn) {
	backoff := c.reconnectInterval
	const maxBackoff = 60 * time.Second

	// Fire onReconnecting only if we are not currently connected. The
	// first cycle after a successful Connect() pre-dial is "not a
	// reconnect" — it is the original connect.
	if !c.IsConnected() && c.onReconnecting != nil {
		safeCall(c.onReconnecting)
	}

	wasReady, err := c.connectOnce(initialConn)
	if c.isStopped() {
		return
	}

	if err != nil {
		slog.Warn("ws connect failed, will retry", "err", err, "backoff", backoff)
	} else {
		slog.Info("ws connection ended", "was_ready", wasReady)
	}

	if wasReady {
		backoff = c.reconnectInterval
	} else {
		backoff *= 2
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
	}

	for {
		select {
		case <-c.stopCh:
			return
		case <-time.After(backoff):
		}

		if !c.IsConnected() && c.onReconnecting != nil {
			safeCall(c.onReconnecting)
		}

		wasReady, err := c.connectOnce(nil)
		if c.isStopped() {
			return
		}

		if err != nil {
			slog.Warn("ws connect failed, will retry", "err", err, "backoff", backoff)
		} else {
			slog.Info("ws connection ended", "was_ready", wasReady)
		}

		if wasReady {
			backoff = c.reconnectInterval
		} else {
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
		}
	}
}

// connectOnce runs a single connection lifecycle. If existing is non-nil
// (the initial pre-dial from Connect), use it directly; otherwise dial
// fresh. The function installs c.conn, runs readLoop + pingLoop, and
// returns when the read loop exits. Returns (wasReady, err): wasReady
// is true if the connection produced at least one successful read.
func (c *WSClient) connectOnce(existing *websocket.Conn) (bool, error) {
	var conn *websocket.Conn
	var err error
	if existing != nil {
		conn = existing
	} else {
		conn, err = c.dialOnce()
		if err != nil {
			return false, err
		}
		c.bumpDiscGeneration()
		c.connMu.Lock()
		c.conn = conn
		c.connMu.Unlock()
	}

	defer func() {
		c.connMu.Lock()
		c.conn = nil
		c.connMu.Unlock()
		_ = conn.Close()
		// Release all pending requests with "ws disconnected" error.
		c.cancelAllPending()
	}()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go c.pingLoop(ctx, conn)

	wasReady, readErr := c.readLoop(conn)
	if readErr != nil {
		slog.Warn("ws read loop ended", "err", readErr, "was_ready", wasReady)
	}
	return wasReady, readErr
}

// dialOnce dials the server and returns the connection. It does NOT
// install c.conn — that's connectOnce's job.
func (c *WSClient) dialOnce() (*websocket.Conn, error) {
	slog.Info("ws connecting", "url", c.serverURL)
	dialer := websocket.Dialer{
		HandshakeTimeout: 10 * time.Second,
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: true, // self-signed cert, desktop internal use
		},
	}
	headers := http.Header{}
	headers.Set("User-Agent", c.userAgent)
	conn, _, err := dialer.Dial(c.serverURL, headers)
	if err != nil {
		return nil, fmt.Errorf("ws dial: %w", err)
	}
	slog.Info("ws connected", "url", c.serverURL)
	return conn, nil
}

// disconnect closes the current conn and cancels all pending requests.
// Safe to call concurrently; idempotent.
func (c *WSClient) disconnect() {
	c.connMu.Lock()
	conn := c.conn
	c.conn = nil
	c.connMu.Unlock()
	if conn != nil {
		_ = conn.Close()
		slog.Info("ws disconnected")
	}
	c.cancelAllPending()
}

// cancelAllPending closes the current disconnect signal so every
// SendRequest registered under this generation returns immediately
// with "ws disconnected". The signal is replaced by bumpDiscGeneration
// after the next successful dial.
func (c *WSClient) cancelAllPending() {
	c.discMu.Lock()
	sig := c.discSignal
	c.discMu.Unlock()
	select {
	case <-sig:
		// already closed
	default:
		close(sig)
	}
}

// pingLoop sends periodic pings until ctx fires. Mirrors the lark_oapi
// _ping_loop pattern but uses gorilla PingMessage which the server
// already handles.
func (c *WSClient) pingLoop(ctx context.Context, conn *websocket.Conn) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopCh:
			return
		case <-ticker.C:
			c.writeMu.Lock()
			conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			werr := conn.WriteMessage(websocket.PingMessage, nil)
			c.writeMu.Unlock()
			if werr != nil {
				slog.Warn("ws ping failed", "err", werr)
				// Don't try to close the conn here — the read loop will
				// observe the failure on its next read and trigger
				// teardown. Closing here would race with the read loop.
				return
			}
		}
	}
}

// readLoop reads messages and dispatches them. Returns (wasReady, err):
// wasReady is true if at least one frame was successfully read.
// On error, returns the error so the supervisor can decide to reconnect.
func (c *WSClient) readLoop(conn *websocket.Conn) (bool, error) {
	// 90s = 3x ping interval. Pong handler refreshes the deadline so
	// the read doesn't expire while the server is alive but quiet.
	conn.SetReadDeadline(time.Now().Add(90 * time.Second))
	conn.SetPongHandler(func(string) error {
		conn.SetReadDeadline(time.Now().Add(90 * time.Second))
		return nil
	})

	wasReady := false
	for {
		_, msg, err := conn.ReadMessage()
		if err != nil {
			return wasReady, err
		}
		wasReady = true

		var wsMsg WSMessage
		if uerr := json.Unmarshal(msg, &wsMsg); uerr != nil {
			slog.Warn("ws parse error", "err", uerr, "raw", string(msg[:min(len(msg), 200)]))
			continue
		}
		wsMsg.Raw = msg
		c.dispatchMessage(wsMsg)
	}
}

// ── Helpers ────────────────────────────────────────────────────────────

func generateRequestID() string {
	b := make([]byte, 8)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func safeCall(fn func()) {
	defer func() {
		if r := recover(); r != nil {
			slog.Warn("callback panic recovered", "panic", r)
		}
	}()
	fn()
}
