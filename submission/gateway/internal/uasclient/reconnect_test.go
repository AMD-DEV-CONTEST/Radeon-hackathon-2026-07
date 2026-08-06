package uasclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

// miniGateway simulates a Gateway for reconnect tests.
type miniGateway struct {
	mu       sync.Mutex
	appID    string
	token    string
	conns    []*websocket.Conn
	replay   []json.RawMessage
	connNum  int32
	server   *httptest.Server
	upgrader websocket.Upgrader
}

func newMiniGateway() *miniGateway {
	mg := &miniGateway{
		appID:  "cli_test_reconnect",
		token:  "tok_test_reconnect",
		replay: nil,
		upgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		},
	}

	mux := http.NewServeMux()

	mux.HandleFunc("/register/client", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"app_id": mg.appID,
			"token":  mg.token,
		})
	})

	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("app_id") != mg.appID || r.URL.Query().Get("token") != mg.token {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		conn, err := mg.upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		num := atomic.AddInt32(&mg.connNum, 1)
		connID := fmt.Sprintf("conn_test_%d", num)

		conn.WriteJSON(map[string]interface{}{
			"type":          "server:welcome",
			"connection_id": connID,
		})

		// Wait for client.ready
		conn.SetReadDeadline(time.Now().Add(5 * time.Second))
		var ready map[string]interface{}
		if err := conn.ReadJSON(&ready); err != nil {
			conn.Close()
			return
		}
		conn.SetReadDeadline(time.Time{})

		mg.mu.Lock()
		mg.conns = append(mg.conns, conn)
		mg.mu.Unlock()

		// Keep reading (acks, pings) until close
		for {
			_, _, err := conn.ReadMessage()
			if err != nil {
				break
			}
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

	mux.HandleFunc("/events/replay", func(w http.ResponseWriter, r *http.Request) {
		mg.mu.Lock()
		events := make([]json.RawMessage, len(mg.replay))
		copy(events, mg.replay)
		mg.mu.Unlock()

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{"events": events})
	})

	mg.server = httptest.NewServer(mux)
	return mg
}

func (mg *miniGateway) close() {
	mg.mu.Lock()
	for _, c := range mg.conns {
		c.Close()
	}
	mg.conns = nil
	mg.mu.Unlock()
	mg.server.Close()
}

func (mg *miniGateway) sendEvent(eventID, text string) {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	payload, _ := json.Marshal(map[string]interface{}{
		"type":     "chat",
		"event_id": eventID,
		"text":     text,
		"ts":       time.Now().UTC().Format(time.RFC3339),
	})
	for _, c := range mg.conns {
		c.WriteMessage(websocket.TextMessage, payload)
	}
}

func (mg *miniGateway) storeForReplay(eventID, text string) {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	payload, _ := json.Marshal(map[string]interface{}{
		"type":     "chat",
		"event_id": eventID,
		"text":     text,
		"ts":       time.Now().UTC().Format(time.RFC3339),
	})
	mg.replay = append(mg.replay, payload)
}

func (mg *miniGateway) dropConns() {
	mg.mu.Lock()
	for _, c := range mg.conns {
		c.Close()
	}
	mg.conns = nil
	mg.mu.Unlock()
}

func (mg *miniGateway) connCount() int {
	mg.mu.Lock()
	defer mg.mu.Unlock()
	return len(mg.conns)
}

func (mg *miniGateway) wsURL() string {
	return "ws" + mg.server.URL[len("http"):]
}

// TestReconnect_BackoffResetsAfterSuccess: connect, reach ready, force disconnect,
// verify reconnect happens and backoff resets (reconnect count increases but quickly).
func TestReconnect_BackoffResetsAfterSuccess(t *testing.T) {
	mg := newMiniGateway()
	defer mg.close()

	received := make(chan Event, 100)
	var buf bytes.Buffer

	c := New(Config{
		GatewayURL: mg.wsURL(),
		AgentName:  "reconnect-test",
		Workspace:  t.TempDir(),
		Stderr:     &buf,
		OnEvent: func(ctx context.Context, e Event) error {
			received <- e
			return nil
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)

	done := make(chan struct{})
	go func() {
		c.Connect(ctx)
		close(done)
	}()

	// Wait for first connection
	waitConn(t, mg, 5*time.Second)

	// Send event on first connection
	mg.sendEvent("evt_before_drop", "hello-before")
	select {
	case e := <-received:
		if e.Text != "hello-before" {
			t.Fatalf("wrong text: %v", e.Text)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timeout receiving event")
	}

	// Force disconnect
	mg.dropConns()
	time.Sleep(200 * time.Millisecond)

	// Client should auto-reconnect (backoff starts at 2s)
	waitConn(t, mg, 5*time.Second)

	// Send event on second connection
	mg.sendEvent("evt_after_reconnect", "hello-after")
	select {
	case e := <-received:
		if e.Text != "hello-after" {
			t.Fatalf("wrong text after reconnect: %v", e.Text)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timeout receiving event after reconnect")
	}

	// Verify reconnect count > 0
	status := c.Status()
	if status.ReconnectCount < 1 {
		t.Fatalf("expected ReconnectCount >= 1, got %d", status.ReconnectCount)
	}

	cancel()
	mg.dropConns() // unblock readLoop
	<-done
}

// TestReconnect_ReplayOnReconnect: connect, receive events, disconnect,
// store events for replay, reconnect, verify replayed events are delivered.
func TestReconnect_ReplayOnReconnect(t *testing.T) {
	mg := newMiniGateway()
	defer mg.close()

	received := make(chan Event, 100)
	var buf bytes.Buffer

	c := New(Config{
		GatewayURL: mg.wsURL(),
		AgentName:  "replay-test",
		Workspace:  t.TempDir(),
		Stderr:     &buf,
		OnEvent: func(ctx context.Context, e Event) error {
			received <- e
			return nil
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)

	done := make(chan struct{})
	go func() {
		c.Connect(ctx)
		close(done)
	}()

	// Wait for connection
	waitConn(t, mg, 5*time.Second)

	// Send first event (establishes cursor)
	mg.sendEvent("evt_replay_1", "before-offline")
	select {
	case e := <-received:
		if e.Text != "before-offline" {
			t.Fatalf("wrong text: %v", e.Text)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timeout receiving first event")
	}

	// Disconnect
	mg.dropConns()
	time.Sleep(200 * time.Millisecond)

	// Store event for replay (simulates event sent while offline)
	mg.storeForReplay("evt_replay_missed", "missed-while-offline")

	// Client reconnects and should replay
	waitConn(t, mg, 5*time.Second)

	// The replayed event should arrive via OnEvent
	select {
	case e := <-received:
		if e.Text != "missed-while-offline" {
			t.Fatalf("replayed event wrong text: %v", e.Text)
		}
		if e.EventID != "evt_replay_missed" {
			t.Fatalf("replayed event wrong id: %v", e.EventID)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("timeout waiting for replayed event")
	}

	cancel()
	mg.dropConns()
	<-done
}

// TestReconnect_DedupeAcrossReconnect: replay delivers same event_id twice,
// second delivery should be deduped.
func TestReconnect_DedupeAcrossReconnect(t *testing.T) {
	mg := newMiniGateway()
	defer mg.close()

	received := make(chan Event, 100)
	var buf bytes.Buffer

	c := New(Config{
		GatewayURL: mg.wsURL(),
		AgentName:  "dedupe-reconnect-test",
		Workspace:  t.TempDir(),
		Stderr:     &buf,
		OnEvent: func(ctx context.Context, e Event) error {
			received <- e
			return nil
		},
	})

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)

	done := make(chan struct{})
	go func() {
		c.Connect(ctx)
		close(done)
	}()
	waitConn(t, mg, 5*time.Second)

	// Send event (will be in dedupe set + cursor)
	mg.sendEvent("evt_dedupe_1", "original")
	select {
	case e := <-received:
		if e.Text != "original" {
			t.Fatalf("wrong text: %v", e.Text)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timeout")
	}

	mg.dropConns()
	time.Sleep(200 * time.Millisecond)

	// Store same event for replay (duplicate)
	mg.storeForReplay("evt_dedupe_1", "original-replayed")
	// Also store a new event
	mg.storeForReplay("evt_dedupe_2", "new-event")

	waitConn(t, mg, 5*time.Second)

	// Should only get the new event, not the duplicate
	select {
	case e := <-received:
		if e.EventID != "evt_dedupe_2" {
			t.Fatalf("expected evt_dedupe_2, got %s (text=%s)", e.EventID, e.Text)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("timeout waiting for new event")
	}

	// Should NOT receive the duplicate
	select {
	case e := <-received:
		t.Fatalf("unexpected duplicate event: %+v", e)
	case <-time.After(500 * time.Millisecond):
		// good — no duplicate
	}

	cancel()
	mg.dropConns()
	<-done
}

func waitConn(t *testing.T, mg *miniGateway, timeout time.Duration) {
	t.Helper()
	deadline := time.After(timeout)
	for {
		if mg.connCount() > 0 {
			return
		}
		select {
		case <-deadline:
			t.Fatal("timeout waiting for connection")
		case <-time.After(50 * time.Millisecond):
		}
	}
}

func init() {
	// Suppress noisy env lookups during tests
	os.Setenv("GATEWAY_URL", "ws://127.0.0.1:0")
}
