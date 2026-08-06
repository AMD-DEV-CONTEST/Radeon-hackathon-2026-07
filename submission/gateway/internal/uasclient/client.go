package uasclient

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// Client is the user-facing handle. Construct one with New, then
// call Connect to start the long-connection loop, and Send/Request/
// Reply to interact. A Client is single-connection-per-process; do
// not share across goroutines that each want their own state.
type Client struct {
	cfg Config

	// wsClient is the gorilla dialer; we use a single instance for
	// every reconnect so TLS state is reused.
	wsClient *websocket.Dialer

	// httpClient is shared between auth and the Send/Request path.
	// It honors ILS_HTTP_TIMEOUT_SECONDS via the caller's env config
	// if set, otherwise defaults to 30s (matches legacy).
	httpClient *http.Client

	// identity is the result of the last successful register* call.
	// It is re-acquired on 401.
	identity identityState

	// conn is the current live WS connection, or nil when not
	// connected. Guarded by connMu.
	connMu sync.RWMutex
	conn   *websocket.Conn

	// state for the status snapshot
	stateMu        sync.Mutex
	stateStr       string
	reconnectCount int
	lastReconnect  time.Time
	lastErr        string

	// dedupe + cursor are loaded lazily in Connect and persisted
	// in Close. The dedupeStore and cursorStore are defined in
	// dedupe.go.
	dedupe *dedupeStore
	cursor *cursorStore

	// readyCh is closed (and re-opened on reconnect) at the moment
	// the post-handshake OnReady callback completes. Callers wait
	// on it to know the connection is fully usable.
	readyMu   sync.Mutex
	readyCond *sync.Cond
	inSession bool
}

type identityState struct {
	appID   string
	token   string
	mode    string // "agent" or "client"
	version string
}

// New constructs a Client. It does not perform any network I/O;
// that happens inside Connect.
func New(cfg Config) *Client {
	if cfg.GatewayURL == "" {
		cfg.GatewayURL = envOr("GATEWAY_URL", "ws://111.228.42.18:8001")
	}
	if cfg.AgentID == "" {
		cfg.AgentID = os.Getenv("AGENT_ID")
	}
	if cfg.AgentName == "" {
		cfg.AgentName = envOr("AGENT_NAME", "uasclient")
	}
	if cfg.AgentType == "" {
		cfg.AgentType = envOr("AGENT_TYPE", "generic")
	}
	if cfg.Password == "" {
		cfg.Password = os.Getenv("GATEWAY_PASSWORD")
	}
	if cfg.OrchestratorURL == "" {
		cfg.OrchestratorURL = envOr("ORCHESTRATOR_URL", "http://111.228.42.18:8000")
	}
	if cfg.Stderr == nil {
		cfg.Stderr = os.Stderr
	}

	ws := &websocket.Dialer{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
	}
	hc := &http.Client{Timeout: envSeconds("ILS_HTTP_TIMEOUT_SECONDS", 30) * time.Second}

	c := &Client{
		cfg:        cfg,
		wsClient:   ws,
		httpClient: hc,
		stateStr:   "idle",
		dedupe:     newDedupeStore(resolveWorkspace(cfg), "chat", cfg.Stderr),
		cursor:     newCursorStore(resolveWorkspace(cfg), "chat"),
	}
	c.readyCond = sync.NewCond(&c.readyMu)
	return c
}

// State reports the current state. Cheap; doesn't block.
func (c *Client) State() string {
	c.stateMu.Lock()
	defer c.stateMu.Unlock()
	return c.stateStr
}

func (c *Client) setState(s string) {
	c.stateMu.Lock()
	c.stateStr = s
	c.stateMu.Unlock()
}

func (c *Client) recordReconnect() {
	c.stateMu.Lock()
	c.reconnectCount++
	c.lastReconnect = time.Now().UTC()
	c.stateMu.Unlock()
}

func (c *Client) recordErr(err error) {
	if err == nil {
		return
	}
	c.stateMu.Lock()
	c.lastErr = err.Error()
	c.stateMu.Unlock()
}

// Status is a snapshot of the client's state, used by status commands.
func (c *Client) Status() Status {
	c.stateMu.Lock()
	defer c.stateMu.Unlock()
	return Status{
		State:           c.stateStr,
		ReconnectCount:  c.reconnectCount,
		LastReconnectAt: c.lastReconnect,
		LastError:       c.lastErr,
	}
}

// Subscribe installs the chat-event handler used by long-running
// consumers such as `ils inbox watch`. It must be called before
// Connect starts. The client still handles dedupe, ack, and
// reconnect; the handler only decides what to do with each event.
func (c *Client) Subscribe(handler func(context.Context, Event) error) {
	c.cfg.OnEvent = handler
}

// Connect runs the reconnect loop until ctx is cancelled. Returns
// nil on graceful shutdown (ctx cancelled), or the last error
// otherwise. Even on error the function returns nil if the user
// cancelled; callers that want to distinguish should watch ctx.
func (c *Client) Connect(ctx context.Context) error {
	// Load dedupe + cursor from disk once at the top. After this,
	// dedupe.add() may append in memory; the file is rewritten on
	// Close and periodically during the run.
	if err := c.dedupe.load(); err != nil {
		fmt.Fprintf(c.cfg.Stderr, "[uasclient] dedupe load: %v (continuing in-memory)\n", err)
	}
	if err := c.cursor.load(); err != nil {
		fmt.Fprintf(c.cfg.Stderr, "[uasclient] cursor load: %v (replay will be skipped)\n", err)
	}
	defer func() {
		if err := c.dedupe.persist(); err != nil {
			fmt.Fprintf(c.cfg.Stderr, "[uasclient] dedupe persist: %v\n", err)
		}
		if err := c.cursor.persist(); err != nil {
			fmt.Fprintf(c.cfg.Stderr, "[uasclient] cursor persist: %v\n", err)
		}
	}()

	backoff := 2 * time.Second
	const maxBackoff = 60 * time.Second

	for {
		if ctx.Err() != nil {
			return nil
		}
		c.setState("connecting")
		wasReady, err := c.connectOnce(ctx)
		if ctx.Err() != nil {
			return nil
		}
		c.recordErr(err)
		c.setState("reconnecting")
		c.recordReconnect()
		fmt.Fprintf(c.cfg.Stderr, "[uasclient] reconnecting after error: %v (backoff=%s)\n", err, backoff)

		select {
		case <-ctx.Done():
			return nil
		case <-time.After(backoff):
		}
		if wasReady || err == nil {
			backoff = 2 * time.Second
		} else {
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
		}
	}
}

// connectOnce runs a single connection lifecycle: acquire identity,
// dial, handshake, replay missed events, run the read loop until it
// exits. Returns (wasReady, err): wasReady is true if the connection
// reached the ready state before failing — the outer loop uses this
// to reset backoff.
func (c *Client) connectOnce(ctx context.Context) (wasReady bool, err error) {
	if err := c.acquireIdentity(ctx); err != nil {
		return false, err
	}

	urlStr := wsURL(c.cfg.GatewayURL, c.identity.appID, c.identity.token)
	dialCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	conn, _, err := c.wsClient.DialContext(dialCtx, urlStr, nil)
	if err != nil {
		return false, fmt.Errorf("ws dial: %w", err)
	}
	releaseConn(conn)
	readyType := "client.ready"
	if c.cfg.AgentID != "" {
		readyType = "agent.ready"
	}
	connID, err := doHandshake(ctx, conn, readyType)
	if err != nil {
		_ = conn.Close()
		return false, err
	}
	fmt.Fprintf(c.cfg.Stderr, "[uasclient] ready connection_id=%s mode=%s\n", connID, c.identity.mode)

	c.connMu.Lock()
	c.conn = conn
	c.connMu.Unlock()
	defer func() {
		c.connMu.Lock()
		c.conn = nil
		c.connMu.Unlock()
		releaseConn(conn)
		_ = conn.Close()
	}()

	c.markReady()

	// Replay events missed while disconnected.
	if sinceID := c.cursor.get(); sinceID != "" {
		n, rerr := c.replayEvents(ctx, sinceID, func(raw []byte) {
			evt, derr := decodeEvent(raw)
			if derr != nil {
				return
			}
			if evt.Type != "chat" {
				return
			}
			if evt.EventID != "" && c.dedupe.seen(evt.EventID) {
				return
			}
			if c.cfg.OnEvent != nil {
				_ = c.cfg.OnEvent(ctx, evt)
			}
			if evt.EventID != "" {
				_ = c.dedupe.add(evt.EventID)
				_ = c.cursor.update(evt.EventID)
			}
		})
		if rerr != nil {
			fmt.Fprintf(c.cfg.Stderr, "[uasclient] replay error: %v\n", rerr)
		} else if n > 0 {
			fmt.Fprintf(c.cfg.Stderr, "[uasclient] replayed %d events\n", n)
		}
	}

	if c.cfg.OnReady != nil {
		if err := c.cfg.OnReady(ctx); err != nil {
			fmt.Fprintf(c.cfg.Stderr, "[uasclient] OnReady callback error: %v\n", err)
		}
	}

	pingCtx, pingCancel := context.WithCancel(ctx)
	defer pingCancel()
	go c.pingLoop(pingCtx, conn)

	c.setState("ready")
	err = c.readLoop(ctx, conn)
	c.setState("closed")
	return true, err
}

// acquireIdentity performs login + register once, populating
// c.identity. For client mode login is a no-op (the Gateway issues
// a token regardless when AUTH_ENABLED=0). For agent mode a real
// password is required; we 401 if it's wrong.
func (c *Client) acquireIdentity(ctx context.Context) error {
	if c.cfg.AgentID != "" {
		token, err := Login(ctx, c.httpClient, c.cfg.GatewayURL, "admin", c.cfg.Password)
		if err != nil {
			return fmt.Errorf("login: %w", err)
		}
		appID, wsToken, err := RegisterAgent(ctx, c.httpClient, c.cfg.GatewayURL, token,
			c.cfg.AgentID, c.cfg.AgentName, c.cfg.AgentType, "uasclient/0.1")
		if err != nil {
			return fmt.Errorf("register agent: %w", err)
		}
		c.identity = identityState{
			appID:   appID,
			token:   wsToken,
			mode:    "agent",
			version: "uasclient/0.1",
		}
		return nil
	}
	appID, wsToken, err := RegisterClient(ctx, c.httpClient, c.cfg.GatewayURL, c.cfg.AgentName, "uasclient/0.1", c.cfg.ClientAgentID)
	if err != nil {
		return fmt.Errorf("register client: %w", err)
	}
	c.identity = identityState{
		appID:   appID,
		token:   wsToken,
		mode:    "client",
		version: "uasclient/0.1",
	}
	return nil
}

// markReady signals any goroutine waiting on the ready condition.
func (c *Client) markReady() {
	c.readyMu.Lock()
	c.inSession = true
	c.readyCond.Broadcast()
	c.readyMu.Unlock()
}

// pingLoop writes a ping every 30s until ctx is done.
func (c *Client) pingLoop(ctx context.Context, conn *websocket.Conn) {
	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if err := sendPing(conn); err != nil {
				// Write failed �?connection is dead, close it so
				// the read loop unblocks. The outer reconnect loop
				// will pick this up.
				_ = conn.Close()
				return
			}
		}
	}
}

// readLoop reads frames until ctx or the conn dies. It dispatches
// each chat event to the OnEvent callback, deduplicating by
// event_id. Every accepted frame is acked.
func (c *Client) readLoop(ctx context.Context, conn *websocket.Conn) error {
	for {
		if ctx.Err() != nil {
			return nil
		}
		_, raw, err := conn.ReadMessage()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("read: %w", err)
		}
		evt, derr := decodeEvent(raw)
		if derr != nil {
			// not a parseable event; skip silently (the legacy
			// code does the same).
			continue
		}
		// OnRawEvent hook: let callers (daemon) intercept any
		// event type before the chat-only filter. Return true
		// to consume the frame (no ack/dedupe/OnEvent).
		if c.cfg.OnRawEvent != nil && c.cfg.OnRawEvent(ctx, evt.Raw) {
			continue
		}
		if evt.Type != "chat" {
			// We only care about chat. Other event types
			// (e.g. server:welcome replay) are ignored.
			continue
		}
		if evt.EventID != "" && c.dedupe.seen(evt.EventID) {
			fmt.Fprintf(c.cfg.Stderr, "[uasclient] dedupe event_id=%s\n", evt.EventID)
			// still ack so the server's pending counter goes down,
			// even though we won't re-deliver to the callback.
			_ = sendAck(conn, evt.EventKey, evt.EventID, "ack")
			if evt.EventID != "" {
				_ = c.cursor.update(evt.EventID)
			}
			continue
		}
		if c.cfg.OnEvent != nil {
			if err := c.cfg.OnEvent(ctx, evt); err != nil {
				fmt.Fprintf(c.cfg.Stderr, "[uasclient] OnEvent error for event_id=%s: %v\n", evt.EventID, err)
			}
		}
		_ = sendAck(conn, evt.EventKey, evt.EventID, "ack")
		if evt.EventID != "" {
			_ = c.dedupe.add(evt.EventID)
			_ = c.cursor.update(evt.EventID)
		}
		if ctx.Err() != nil {
			return nil
		}
	}
}

// Close releases the current connection (if any) and the
// per-connection write mutexes. The reconnect loop will spin up a
// fresh connection on the next tick if Connect is still running.
func (c *Client) Close() error {
	c.connMu.Lock()
	conn := c.conn
	c.conn = nil
	c.connMu.Unlock()
	if conn != nil {
		releaseConn(conn)
		_ = conn.Close()
	}
	_ = c.dedupe.persist()
	_ = c.cursor.persist()
	return nil
}

// currentConn returns the live connection for use by Send/Reply.
// Returns nil if not ready.
func (c *Client) currentConn() *websocket.Conn {
	c.connMu.RLock()
	defer c.connMu.RUnlock()
	return c.conn
}

// waitReady blocks until a connection is ready or ctx fires.
// Used by Send/Request.
func (c *Client) waitReady(ctx context.Context) error {
	c.readyMu.Lock()
	defer c.readyMu.Unlock()
	for !c.inSession {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		// Wait in a way that's interruptible. We use a goroutine
		// to fire the cond when ctx is done.
		done := make(chan struct{})
		go func() {
			select {
			case <-ctx.Done():
				c.readyMu.Lock()
				c.inSession = false
				c.readyMu.Unlock()
				c.readyCond.Broadcast()
			case <-done:
			}
		}()
		c.readyCond.Wait()
		close(done)
		if !c.inSession {
			return ctx.Err()
		}
	}
	return nil
}

// RunOnce is a convenience for one-shot CLI commands: it starts
// Connect in the background, waits for the first ready, runs fn,
// then tears the connection down and returns. ctx bounds the
// whole flow. fn may call Send, Request, or Reply.
//
// This is the right entry point for `ils chat send` and
// `ils chat request`, which want library-managed reliability for
// the duration of a single command invocation but don't want to
// keep the process alive afterwards.
func (c *Client) RunOnce(ctx context.Context, fn func() error) error {
	errCh := make(chan error, 1)
	go func() {
		errCh <- c.Connect(ctx)
	}()
	if err := c.waitReady(ctx); err != nil {
		return err
	}
	runErr := fn()
	_ = c.Close()
	// Give Connect a chance to observe the close and exit
	// cleanly. Don't block forever; ctx will cap it.
	select {
	case <-errCh:
	case <-time.After(2 * time.Second):
	case <-ctx.Done():
	}
	return runErr
}

// errNotReady is returned by Send/Request when no live connection
// is available. (chat.go references it directly.)
var errNotReady = errors.New("uasclient: no live connection (Connect not started or not yet ready)")

// urlValues is a tiny helper around url.Values used in chat.go.
// Defined here to avoid a circular import and to keep the
// chat-path types close together.
func urlValuesLocal(p map[string]string) url.Values {
	v := url.Values{}
	for k, val := range p {
		v.Set(k, val)
	}
	return v
}
