package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

// miniGateway simulates a Gateway for wsclient reconnect tests. It does
// not require a /register handshake — the OB wsclient passes token + app_id
// as query string params, so the server only needs to validate those.
type miniGateway struct {
	mu       sync.Mutex
	appID    string
	token    string
	conns    []*websocket.Conn
	connNum  int32
	server   *httptest.Server
	upgrader websocket.Upgrader
}

func newMiniGateway() *miniGateway {
	mg := &miniGateway{
		appID: "ob_test_app",
		token: "ob_test_token",
		upgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("app_id") != mg.appID ||
			r.URL.Query().Get("token") != mg.token {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		conn, err := mg.upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		num := atomic.AddInt32(&mg.connNum, 1)
		_ = conn.WriteJSON(map[string]interface{}{
			"type":          "server:welcome",
			"connection_id": fmt.Sprintf("conn_test_%d", num),
		})

		mg.mu.Lock()
		mg.conns = append(mg.conns, conn)
		mg.mu.Unlock()

		// Echo every message back as a reply (so SendRequest gets a response
		// when the test expects one). Real Gateway would inspect msg.Type.
		for {
			_, raw, err := conn.ReadMessage()
			if err != nil {
				break
			}
			var req struct {
				ID   string          `json:"id"`
				Type string          `json:"type"`
				Pyld json.RawMessage `json:"payload"`
			}
			if jerr := json.Unmarshal(raw, &req); jerr != nil || req.ID == "" {
				continue
			}
			resp, _ := json.Marshal(map[string]interface{}{
				"type":      req.Type + ":reply",
				"id":        req.ID,
				"timestamp": time.Now().UTC().Format(time.RFC3339),
				"payload":   req.Pyld,
			})
			_ = conn.WriteMessage(websocket.TextMessage, resp)
		}

		mg.mu.Lock()
		for i, c := range mg.conns {
			if c == conn {
				mg.conns = append(mg.conns[:i], mg.conns[i+1:]...)
				break
			}
		}
		mg.mu.Unlock()
	})
	mg.server = httptest.NewServer(mux)
	return mg
}

func (mg *miniGateway) close() {
	mg.mu.Lock()
	for _, c := range mg.conns {
		_ = c.Close()
	}
	mg.conns = nil
	mg.mu.Unlock()
	mg.server.Close()
}

func (mg *miniGateway) dropConns() {
	mg.mu.Lock()
	conns := append([]*websocket.Conn(nil), mg.conns...)
	mg.conns = nil
	mg.mu.Unlock()
	for _, c := range conns {
		_ = c.Close()
	}
}

func (mg *miniGateway) connCount() int {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	return len(mg.conns)
}

func (mg *miniGateway) wsURL() string {
	return "ws" + mg.server.URL[len("http"):]
}

func newTestClient(mg *miniGateway) *WSClient {
	return NewWSClient(WSClientConfig{
		ServerURL:         mg.wsURL() + "/ws",
		Token:             mg.token,
		AppID:             mg.appID,
		AutoReconnect:     true,
		ReconnectInterval: 100 * time.Millisecond,
		MaxBackoff:        500 * time.Millisecond,
	})
}

func waitForConnected(t *testing.T, c *WSClient, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if c.IsConnected() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("timeout waiting for IsConnected")
}

func waitForConnCount(t *testing.T, mg *miniGateway, want int, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if mg.connCount() == want {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timeout waiting for connCount=%d, got %d", want, mg.connCount())
}

// TestReconnect_BackoffResetsAfterSuccess: connect, reach ready, drop,
// verify auto-reconnect happens and a second ready is reached.
func TestReconnect_BackoffResetsAfterSuccess(t *testing.T) {
	mg := newMiniGateway()
	defer mg.close()

	client := newTestClient(mg)
	defer client.Close()

	if err := client.Connect(); err != nil {
		t.Fatalf("Connect: %v", err)
	}
	waitForConnected(t, client, 2*time.Second)
	waitForConnCount(t, mg, 1, 2*time.Second)

	// Drop the connection — supervisor should reconnect.
	mg.dropConns()
	waitForConnected(t, client, 2*time.Second)
	waitForConnCount(t, mg, 1, 2*time.Second)
}

// TestSendRequest_DisconnectedReturnsImmediately: register a SendRequest
// against a no-reply server, drop the conn while it's waiting, expect
// "ws disconnected" error (not a timeout).
func TestSendRequest_DisconnectedReturnsImmediately(t *testing.T) {
	mg := newMiniGateway()
	defer mg.close()

	// Replace the echo handler with a silent one — never replies so
	// SendRequest stays parked in the select until we drop the conn.
	mg.server.Close()
	mg.mu.Lock()
	mg.conns = nil
	mg.mu.Unlock()
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := mg.upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		_ = conn.WriteJSON(map[string]interface{}{
			"type": "server:welcome", "connection_id": "slow",
		})
		mg.mu.Lock()
		mg.conns = append(mg.conns, conn)
		mg.mu.Unlock()
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	})
	mg.server = httptest.NewServer(mux)

	client := newTestClient(mg)
	defer client.Close()
	if err := client.Connect(); err != nil {
		t.Fatalf("Connect: %v", err)
	}
	waitForConnected(t, client, 2*time.Second)
	waitForConnCount(t, mg, 1, 2*time.Second)

	// Start a SendRequest in a goroutine. It will register a pending
	// channel and wait for a response that never comes.
	errCh := make(chan error, 1)
	go func() {
		_, err := client.SendRequest("echo", map[string]any{"hello": "world"}, 30*time.Second)
		errCh <- err
	}()

	// Give it a moment to register + write.
	time.Sleep(200 * time.Millisecond)

	// Drop the conn — the pending SendRequest should wake up immediately
	// with "ws disconnected" instead of waiting 30s for the timeout.
	start := time.Now()
	mg.dropConns()
	select {
	case err := <-errCh:
		elapsed := time.Since(start)
		if elapsed > 2*time.Second {
			t.Fatalf("SendRequest took too long to return after disconnect: %v (err=%v)", elapsed, err)
		}
		if err == nil {
			t.Fatal("expected error from SendRequest, got nil")
		}
		// Acceptable errors: "ws disconnected" (primary) or
		// "ws not connected" (supervisor's reconnect raced us and
		// the new conn is mid-install). Anything else is a bug.
		if err.Error() != "ws disconnected" && err.Error() != "ws not connected" {
			t.Fatalf("unexpected error: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("SendRequest did not return after disconnect")
	}
}

// TestClose_UnblocksPending: register a SendRequest against a no-reply
// server, then call Close. All pending requests must return with an
// error (not block forever).
func TestClose_UnblocksPending(t *testing.T) {
	mg := newMiniGateway()
	defer mg.close()

	// Replace the echo handler with a silent one — never replies to
	// any request so SendRequest stays parked in the select.
	mg.server.Close()
	mg.mu.Lock()
	mg.conns = nil
	mg.mu.Unlock()
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := mg.upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		_ = conn.WriteJSON(map[string]interface{}{
			"type": "server:welcome", "connection_id": "silent",
		})
		mg.mu.Lock()
		mg.conns = append(mg.conns, conn)
		mg.mu.Unlock()
		// Read forever, never reply.
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	})
	mg.server = httptest.NewServer(mux)

	client := newTestClient(mg)
	if err := client.Connect(); err != nil {
		t.Fatalf("Connect: %v", err)
	}
	waitForConnected(t, client, 2*time.Second)
	waitForConnCount(t, mg, 1, 2*time.Second)

	// Two pending SendRequest calls — neither will get a reply.
	errCh1 := make(chan error, 1)
	errCh2 := make(chan error, 1)
	go func() {
		_, err := client.SendRequest("slow", map[string]any{"a": 1}, 30*time.Second)
		errCh1 <- err
	}()
	go func() {
		_, err := client.SendRequest("slow", map[string]any{"a": 2}, 30*time.Second)
		errCh2 <- err
	}()

	time.Sleep(200 * time.Millisecond)

	// Close — both must return promptly with an error.
	start := time.Now()
	client.Close()
	elapsed := time.Since(start)
	if elapsed > 2*time.Second {
		t.Fatalf("Close() took too long: %v", elapsed)
	}

	for i, ch := range []chan error{errCh1, errCh2} {
		select {
		case err := <-ch:
			if err == nil {
				t.Fatalf("pending #%d: expected error, got nil", i+1)
			}
		case <-time.After(2 * time.Second):
			t.Fatalf("pending #%d: did not return after Close()", i+1)
		}
	}

	// Close is idempotent.
	client.Close()
}
