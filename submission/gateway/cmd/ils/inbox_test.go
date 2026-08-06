package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

type inboxMockGateway struct {
	t *testing.T

	server      *httptest.Server
	mu          sync.Mutex
	seenAgentID string
	connCount   int
	events      [][]map[string]interface{}
}

func newInboxMockGateway(t *testing.T, events [][]map[string]interface{}) *inboxMockGateway {
	t.Helper()
	gw := &inboxMockGateway{t: t, events: events}
	mux := http.NewServeMux()
	mux.HandleFunc("/register/client", gw.handleRegisterClient)
	mux.HandleFunc("/ws", gw.handleWS)
	gw.server = httptest.NewServer(mux)
	t.Cleanup(gw.server.Close)
	return gw
}

func (g *inboxMockGateway) wsURL() string {
	return "ws://" + strings.TrimPrefix(g.server.URL, "http://")
}

func (g *inboxMockGateway) handleRegisterClient(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Name    string `json:"name"`
		AgentID string `json:"agent_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		g.t.Errorf("register decode: %v", err)
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	g.mu.Lock()
	g.seenAgentID = req.AgentID
	g.mu.Unlock()
	_ = json.NewEncoder(w).Encode(map[string]interface{}{
		"app_id": "cli_test",
		"token":  "token_test",
	})
}

func (g *inboxMockGateway) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := (&websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}).Upgrade(w, r, nil)
	if err != nil {
		g.t.Errorf("ws upgrade: %v", err)
		return
	}
	defer conn.Close()

	g.mu.Lock()
	idx := g.connCount
	g.connCount++
	g.mu.Unlock()

	_ = conn.WriteJSON(map[string]interface{}{
		"type":          "server:welcome",
		"connection_id": "conn_test",
	})
	_, _, err = conn.ReadMessage()
	if err != nil {
		return
	}

	if idx < len(g.events) {
		for _, event := range g.events[idx] {
			_ = conn.WriteJSON(event)
		}
	}

	if idx+1 < len(g.events) {
		return
	}
	for {
		if _, _, err := conn.ReadMessage(); err != nil {
			return
		}
	}
}

func TestInboxWatchJSONLPrintsThreeMessages(t *testing.T) {
	gw := newInboxMockGateway(t, [][]map[string]interface{}{{
		chatEvent("evt_1", "msg_1", "conv_1", "h5", "x1", "one"),
		chatEvent("evt_2", "msg_2", "conv_1", "h5", "x1", "two"),
		chatEvent("evt_3", "msg_3", "conv_1", "h5", "x1", "three"),
	}})

	var out bytes.Buffer
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := runInboxWatch(ctx, inboxWatchOptions{
		AgentID:         "x1",
		GatewayURL:      gw.wsURL(),
		Format:          "jsonl",
		MaxEvents:       3,
		NoHeartbeat:     true,
		DedupeWorkspace: t.TempDir(),
	}, &out); err != nil {
		t.Fatalf("runInboxWatch: %v", err)
	}

	lines := readNonEmptyLines(out.String())
	if len(lines) != 3 {
		t.Fatalf("line count: got %d want 3\n%s", len(lines), out.String())
	}
	var first inboxLine
	if err := json.Unmarshal([]byte(lines[0]), &first); err != nil {
		t.Fatalf("first line json: %v", err)
	}
	if first.From != "h5" || first.To != "x1" || first.Text != "one" || first.ConvID != "conv_1" {
		t.Fatalf("unexpected first line: %+v", first)
	}
	if gw.seenAgentID != "x1" {
		t.Fatalf("register client agent_id: got %q want x1", gw.seenAgentID)
	}
}

func TestInboxWatchOnceExitsAfterFirstMessage(t *testing.T) {
	gw := newInboxMockGateway(t, [][]map[string]interface{}{{
		chatEvent("evt_once_1", "msg_1", "conv_1", "h5", "x1", "first"),
		chatEvent("evt_once_2", "msg_2", "conv_1", "h5", "x1", "second"),
	}})

	var out bytes.Buffer
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := runInboxWatch(ctx, inboxWatchOptions{
		AgentID:         "x1",
		GatewayURL:      gw.wsURL(),
		Format:          "text",
		Once:            true,
		NoHeartbeat:     true,
		DedupeWorkspace: t.TempDir(),
	}, &out); err != nil {
		t.Fatalf("runInboxWatch: %v", err)
	}
	lines := readNonEmptyLines(out.String())
	if len(lines) != 1 {
		t.Fatalf("line count: got %d want 1\n%s", len(lines), out.String())
	}
	if !strings.Contains(lines[0], "h5->x1: first") {
		t.Fatalf("unexpected text line: %q", lines[0])
	}
}

func TestInboxWatchReconnectContinuesAfterDisconnect(t *testing.T) {
	gw := newInboxMockGateway(t, [][]map[string]interface{}{
		{chatEvent("evt_reconnect_1", "msg_1", "conv_1", "h5", "x1", "before reconnect")},
		{chatEvent("evt_reconnect_2", "msg_2", "conv_1", "h5", "x1", "after reconnect")},
	})

	var out bytes.Buffer
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if err := runInboxWatch(ctx, inboxWatchOptions{
		AgentID:         "x1",
		GatewayURL:      gw.wsURL(),
		Format:          "jsonl",
		MaxEvents:       2,
		NoHeartbeat:     true,
		DedupeWorkspace: t.TempDir(),
	}, &out); err != nil {
		t.Fatalf("runInboxWatch: %v", err)
	}
	lines := readNonEmptyLines(out.String())
	if len(lines) != 2 {
		t.Fatalf("line count: got %d want 2\n%s", len(lines), out.String())
	}
	if !strings.Contains(lines[1], "after reconnect") {
		t.Fatalf("expected second line after reconnect, got %q", lines[1])
	}
}

func chatEvent(eventID, messageID, convID, from, target, text string) map[string]interface{} {
	return map[string]interface{}{
		"type":            "chat",
		"event_id":        eventID,
		"event_key":       "chat",
		"message_id":      messageID,
		"conv_id":         convID,
		"from_agent_id":   from,
		"target_agent_id": target,
		"text":            text,
		"ts":              "2026-06-20T22:30:00Z",
	}
}

func readNonEmptyLines(s string) []string {
	scanner := bufio.NewScanner(strings.NewReader(s))
	var lines []string
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line != "" {
			lines = append(lines, line)
		}
	}
	return lines
}
