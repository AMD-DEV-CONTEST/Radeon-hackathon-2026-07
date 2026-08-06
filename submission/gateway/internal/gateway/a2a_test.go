package gateway

import (
	"bytes"
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

// testGateway spins up a minimal Gateway with /ws, /chat, /events/ack, /events/replay endpoints.
func testGateway(t *testing.T) (*httptest.Server, func()) {
	t.Helper()

	eventMu.Lock()
	eventDelivery = map[string]*eventDeliveryRecord{}
	eventBuffer = nil
	eventMu.Unlock()

	mux := http.NewServeMux()

	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		appID := r.URL.Query().Get("app_id")
		token := r.URL.Query().Get("token")
		if appID == "" || token == "" {
			http.Error(w, "missing app_id/token", http.StatusUnauthorized)
			return
		}
		if !VerifyAppIDToken(appID, token) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		HandleClientWS(w, r, appID)
	})

	mux.HandleFunc("/chat", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			EventType       string                 `json:"event_type"`
			ClientMessageID string                 `json:"client_message_id"`
			From            string                 `json:"from"`
			FromAgentID     string                 `json:"from_agent_id"`
			TargetAgentID   string                 `json:"target_agent_id"`
			Text            string                 `json:"text"`
			ConvID          string                 `json:"conv_id"`
			Source          map[string]interface{} `json:"source"`
			Target          map[string]interface{} `json:"target"`
			Delivery        map[string]interface{} `json:"delivery"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeTestJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid body"})
			return
		}
		if req.Text == "" {
			writeTestJSON(w, http.StatusBadRequest, map[string]string{"error": "text is required"})
			return
		}

		eventID := "evt_" + randString(12)
		messageID := "msg_" + randString(12)
		convID := req.ConvID
		if convID == "" {
			convID = "conv_" + randString(12)
		}
		if req.EventType == "" {
			req.EventType = "chat.message.created"
		}

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
			"ts":                time.Now().UTC().Format(time.RFC3339),
			"delivery":          map[string]interface{}{"requires_ack": true, "attempt": 1},
		}

		resolvedTargetID := req.TargetAgentID
		if resolvedTargetID != "" {
			if uuid := ResolveAgentID(resolvedTargetID); uuid != "" {
				resolvedTargetID = uuid
				msg["target_agent_id"] = resolvedTargetID
			}
		}
		payload, _ := json.Marshal(msg)

		var delivery DeliveryResult
		retryRoute := "ob_clients"
		retryAppID := ""
		if req.TargetAgentID != "" {
			appID := GetAgentAppID(resolvedTargetID)
			if appID == "" && req.TargetAgentID != resolvedTargetID {
				appID = GetAgentAppID(req.TargetAgentID)
			}
			if appID != "" {
				delivery = BroadcastToApp(appID, payload)
				retryRoute = "agent_app"
				retryAppID = appID
			} else {
				delivery = BroadcastToAgent(resolvedTargetID, payload)
				retryRoute = "agent_legacy"
			}
		} else {
			delivery = BroadcastToAllClients(payload)
		}

		StoreEventForReplay(eventID, "chat", payload)
		RecordEventDeliveryRouted(eventID, "chat", delivery.DeliveredToConnections, retryAppID, retryRoute)

		writeTestJSON(w, http.StatusOK, map[string]interface{}{
			"status":                   "accepted",
			"event_id":                 eventID,
			"message_id":               messageID,
			"conv_id":                  convID,
			"target_connected":         delivery.TargetConnected,
			"delivered_to_connections":  delivery.DeliveredToConnections,
			"ack_required":             true,
		})
	})

	mux.HandleFunc("/events/ack", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			EventID    string `json:"event_id"`
			EventKey   string `json:"event_key"`
			ConsumerID string `json:"consumer_id"`
			Status     string `json:"status"`
		}
		json.NewDecoder(r.Body).Decode(&req)
		if req.EventKey == "" {
			req.EventKey = "chat"
		}
		if req.Status == "" {
			req.Status = "ack"
		}
		RecordEventConsumerStatus(req.EventID, req.EventKey, req.ConsumerID, req.Status)
		writeTestJSON(w, http.StatusOK, map[string]interface{}{"status": "ok", "event_id": req.EventID})
	})

	mux.HandleFunc("/events/replay", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			EventKey     string `json:"event_key"`
			SinceEventID string `json:"since_event_id"`
		}
		json.NewDecoder(r.Body).Decode(&req)
		events := ReplayEventsSince(req.EventKey, req.SinceEventID)
		writeTestJSON(w, http.StatusOK, map[string]interface{}{"events": events})
	})

	server := httptest.NewServer(mux)
	return server, func() { server.Close() }
}

func writeTestJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

type testAgent struct {
	ID     string
	Name   string
	AppID  string
	Token  string
	Conn   *websocket.Conn
	ConnID string
	Inbox  chan map[string]interface{}
	stopCh chan struct{}
}

func connectAgent(t *testing.T, serverURL, agentID, agentName string) *testAgent {
	t.Helper()
	identity, token, err := RegisterAgent(agentID, agentName, "test-agent")
	if err != nil {
		t.Fatalf("RegisterAgent %s: %v", agentID, err)
	}

	wsURL := "ws" + serverURL[len("http"):] + "/ws?app_id=" + identity.AppID + "&token=" + token
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial ws %s: %v", agentID, err)
	}

	var welcome map[string]interface{}
	conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	if err := conn.ReadJSON(&welcome); err != nil {
		t.Fatalf("read welcome %s: %v", agentID, err)
	}
	connID, _ := welcome["connection_id"].(string)

	if err := conn.WriteJSON(map[string]interface{}{
		"type":          "agent.ready",
		"connection_id": connID,
	}); err != nil {
		t.Fatalf("write ready %s: %v", agentID, err)
	}

	agent := &testAgent{
		ID:     agentID,
		Name:   agentName,
		AppID:  identity.AppID,
		Token:  token,
		Conn:   conn,
		ConnID: connID,
		Inbox:  make(chan map[string]interface{}, 100),
		stopCh: make(chan struct{}),
	}

	go func() {
		for {
			conn.SetReadDeadline(time.Now().Add(10 * time.Second))
			var msg map[string]interface{}
			if err := conn.ReadJSON(&msg); err != nil {
				select {
				case <-agent.stopCh:
				default:
				}
				return
			}
			agent.Inbox <- msg
		}
	}()

	return agent
}

func (a *testAgent) close() {
	close(a.stopCh)
	a.Conn.Close()
}

func (a *testAgent) recv(t *testing.T, timeout time.Duration) map[string]interface{} {
	t.Helper()
	select {
	case msg := <-a.Inbox:
		return msg
	case <-time.After(timeout):
		t.Fatalf("agent %s: recv timeout after %v", a.ID, timeout)
		return nil
	}
}

func (a *testAgent) sendAckWS(t *testing.T, eventID string) {
	t.Helper()
	if err := a.Conn.WriteJSON(map[string]interface{}{
		"type":     "event:ack",
		"event_id": eventID,
		"status":   "ack",
	}); err != nil {
		t.Fatalf("agent %s: send ack: %v", a.ID, err)
	}
}

func postChat(t *testing.T, baseURL, from, fromAgentID, targetAgentID, text string) map[string]interface{} {
	t.Helper()
	body, _ := json.Marshal(map[string]interface{}{
		"from":            from,
		"from_agent_id":   fromAgentID,
		"target_agent_id": targetAgentID,
		"text":            text,
	})
	resp, err := http.Post(baseURL+"/chat", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST /chat: %v", err)
	}
	defer resp.Body.Close()
	var result map[string]interface{}
	json.NewDecoder(resp.Body).Decode(&result)
	if resp.StatusCode != 200 {
		t.Fatalf("POST /chat status %d: %v", resp.StatusCode, result)
	}
	return result
}

func postAck(t *testing.T, baseURL, eventID, consumerID string) {
	t.Helper()
	body, _ := json.Marshal(map[string]interface{}{
		"event_id":    eventID,
		"consumer_id": consumerID,
		"status":      "ack",
	})
	resp, err := http.Post(baseURL+"/events/ack", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST /events/ack: %v", err)
	}
	resp.Body.Close()
}

// ═══════════════════════════════════════════════════════════════════════
// T1: Agent ↔ Agent full duplex — A sends to B, B replies to A, both ack
// ═══════════════════════════════════════════════════════════════════════

func TestA2A_FullDuplex(t *testing.T) {
	server, cleanup := testGateway(t)
	defer cleanup()

	agentA := connectAgent(t, server.URL, "agent-alpha", "alpha")
	defer agentA.close()
	agentB := connectAgent(t, server.URL, "agent-bravo", "bravo")
	defer agentB.close()

	chatResp := postChat(t, server.URL, "alpha", "agent-alpha", "agent-bravo", "PING-FROM-A")
	eventIDA2B, _ := chatResp["event_id"].(string)
	if eventIDA2B == "" {
		t.Fatal("A→B: missing event_id")
	}
	delivered, _ := chatResp["delivered_to_connections"].(float64)
	if delivered < 1 {
		t.Fatalf("A→B: not delivered, resp=%v", chatResp)
	}

	msgB := agentB.recv(t, 3*time.Second)
	if msgB["text"] != "PING-FROM-A" {
		t.Fatalf("B received wrong text: %v", msgB["text"])
	}
	if msgB["from_agent_id"] != "agent-alpha" {
		t.Fatalf("B received wrong from_agent_id: %v", msgB["from_agent_id"])
	}

	agentB.sendAckWS(t, eventIDA2B)
	time.Sleep(50 * time.Millisecond)

	chatResp2 := postChat(t, server.URL, "bravo", "agent-bravo", "agent-alpha", "PONG-FROM-B")
	eventIDB2A, _ := chatResp2["event_id"].(string)
	if eventIDB2A == "" {
		t.Fatal("B→A: missing event_id")
	}

	msgA := agentA.recv(t, 3*time.Second)
	if msgA["text"] != "PONG-FROM-B" {
		t.Fatalf("A received wrong text: %v", msgA["text"])
	}
	if msgA["from_agent_id"] != "agent-bravo" {
		t.Fatalf("A received wrong from_agent_id: %v", msgA["from_agent_id"])
	}

	agentA.sendAckWS(t, eventIDB2A)
	time.Sleep(50 * time.Millisecond)

	eventMu.Lock()
	recA2B := eventDelivery[eventIDA2B]
	recB2A := eventDelivery[eventIDB2A]
	eventMu.Unlock()

	if recA2B == nil || recA2B.Pending != 0 {
		t.Fatalf("A→B delivery: pending=%d (want 0)", safePending(recA2B))
	}
	if recB2A == nil || recB2A.Pending != 0 {
		t.Fatalf("B→A delivery: pending=%d (want 0)", safePending(recB2A))
	}
}

func safePending(rec *eventDeliveryRecord) int {
	if rec == nil {
		return -1
	}
	return rec.Pending
}

// ═══════════════════════════════════════════════════════════════════════
// T2: OB Client ↔ Agent full duplex
// ═══════════════════════════════════════════════════════════════════════

func TestA2A_OBAgentDuplex(t *testing.T) {
	server, cleanup := testGateway(t)
	defer cleanup()

	obIdentity, obToken, err := RegisterClient("ob-duplex-test", "ob-main")
	if err != nil {
		t.Fatalf("RegisterClient OB: %v", err)
	}

	obWS := "ws" + server.URL[len("http"):] + "/ws?app_id=" + obIdentity.AppID + "&token=" + obToken
	obConn, _, err := websocket.DefaultDialer.Dial(obWS, nil)
	if err != nil {
		t.Fatalf("dial OB ws: %v", err)
	}
	defer obConn.Close()

	var obWelcome map[string]interface{}
	obConn.SetReadDeadline(time.Now().Add(3 * time.Second))
	obConn.ReadJSON(&obWelcome)
	obConnID, _ := obWelcome["connection_id"].(string)
	obConn.WriteJSON(map[string]interface{}{"type": "client.ready", "connection_id": obConnID})

	obInbox := make(chan map[string]interface{}, 100)
	go func() {
		for {
			obConn.SetReadDeadline(time.Now().Add(10 * time.Second))
			var msg map[string]interface{}
			if err := obConn.ReadJSON(&msg); err != nil {
				return
			}
			obInbox <- msg
		}
	}()

	agent := connectAgent(t, server.URL, "h5-hermes-test", "h5-hermes")
	defer agent.close()

	// OB → Agent (targeted)
	resp1 := postChat(t, server.URL, "user", "", "h5-hermes-test", "hello agent")
	evtOB2Agent, _ := resp1["event_id"].(string)

	agentMsg := agent.recv(t, 3*time.Second)
	if agentMsg["text"] != "hello agent" {
		t.Fatalf("agent received wrong text: %v", agentMsg["text"])
	}
	agent.sendAckWS(t, evtOB2Agent)

	// Agent → OB (broadcast, no target_agent_id)
	resp2 := postChat(t, server.URL, "h5-hermes", "h5-hermes-test", "", "hello user")
	evtAgent2OB, _ := resp2["event_id"].(string)

	select {
	case obMsg := <-obInbox:
		if obMsg["text"] != "hello user" {
			t.Fatalf("OB received wrong text: %v", obMsg["text"])
		}
		if obMsg["from_agent_id"] != "h5-hermes-test" {
			t.Fatalf("OB received wrong from_agent_id: %v", obMsg["from_agent_id"])
		}
	case <-time.After(3 * time.Second):
		t.Fatal("OB: recv timeout")
	}

	postAck(t, server.URL, evtAgent2OB, "ob-main")
	time.Sleep(50 * time.Millisecond)

	eventMu.Lock()
	r1 := eventDelivery[evtOB2Agent]
	r2 := eventDelivery[evtAgent2OB]
	eventMu.Unlock()

	if r1 == nil || r1.Acked < 1 {
		t.Fatalf("OB→Agent ack missing: %+v", r1)
	}
	if r2 == nil || r2.Acked < 1 {
		t.Fatalf("Agent→OB ack missing: %+v", r2)
	}
}

// ═══════════════════════════════════════════════════════════════════════
// T3: Ack 闭环 — Pending drops to 0 after ack
// ═══════════════════════════════════════════════════════════════════════

func TestA2A_AckClosesLoop(t *testing.T) {
	server, cleanup := testGateway(t)
	defer cleanup()

	agentA := connectAgent(t, server.URL, "ack-sender", "sender")
	defer agentA.close()
	agentB := connectAgent(t, server.URL, "ack-receiver", "receiver")
	defer agentB.close()

	resp := postChat(t, server.URL, "sender", "ack-sender", "ack-receiver", "ack-test")
	eventID, _ := resp["event_id"].(string)

	agentB.recv(t, 3*time.Second)
	time.Sleep(50 * time.Millisecond)

	eventMu.Lock()
	rec := eventDelivery[eventID]
	pendingBefore := rec.Pending
	eventMu.Unlock()

	if pendingBefore < 1 {
		t.Fatalf("expected Pending >= 1 before ack, got %d", pendingBefore)
	}

	agentB.sendAckWS(t, eventID)
	time.Sleep(100 * time.Millisecond)

	eventMu.Lock()
	pendingAfter := rec.Pending
	ackedAfter := rec.Acked
	eventMu.Unlock()

	if pendingAfter != 0 {
		t.Fatalf("expected Pending=0 after ack, got %d", pendingAfter)
	}
	if ackedAfter < 1 {
		t.Fatalf("expected Acked >= 1, got %d", ackedAfter)
	}
}

// ═══════════════════════════════════════════════════════════════════════
// T4: Unacked + auto-retry integration
// ═══════════════════════════════════════════════════════════════════════

func TestA2A_RetryOnNoAck(t *testing.T) {
	server, cleanup := testGateway(t)
	defer cleanup()

	agent := connectAgent(t, server.URL, "retry-target", "retry-bot")
	defer agent.close()

	resp := postChat(t, server.URL, "user", "", "retry-target", "retry-me")
	eventID, _ := resp["event_id"].(string)

	msg1 := agent.recv(t, 3*time.Second)
	if msg1["text"] != "retry-me" {
		t.Fatalf("wrong text: %v", msg1["text"])
	}

	// Force LastUpdated to trigger retry
	eventMu.Lock()
	rec := eventDelivery[eventID]
	rec.LastUpdated = time.Now().UTC().Add(-31 * time.Second)
	eventMu.Unlock()

	retryUnackedEvents()

	msg2 := agent.recv(t, 3*time.Second)
	if msg2["text"] != "retry-me" {
		t.Fatalf("retry: wrong text: %v", msg2["text"])
	}

	// Ack covers the retry delivery too
	agent.sendAckWS(t, eventID)
	time.Sleep(100 * time.Millisecond)

	eventMu.Lock()
	retryCount := rec.RetryCount
	acked := rec.Acked
	eventMu.Unlock()

	if retryCount < 1 {
		t.Fatalf("expected RetryCount >= 1, got %d", retryCount)
	}
	if acked < 1 {
		t.Fatalf("expected Acked >= 1, got %d", acked)
	}
}

// ═══════════════════════════════════════════════════════════════════════
// T5: Disconnect + replay recovery
// ═══════════════════════════════════════════════════════════════════════

func TestA2A_DisconnectReplay(t *testing.T) {
	server, cleanup := testGateway(t)
	defer cleanup()

	agentA := connectAgent(t, server.URL, "replay-sender", "sender")
	defer agentA.close()
	agentB := connectAgent(t, server.URL, "replay-receiver", "receiver")

	resp1 := postChat(t, server.URL, "sender", "replay-sender", "replay-receiver", "msg-before-disconnect")
	evt1, _ := resp1["event_id"].(string)
	agentB.recv(t, 3*time.Second)
	agentB.sendAckWS(t, evt1)

	agentB.close()
	time.Sleep(100 * time.Millisecond)

	// A sends while B offline
	postChat(t, server.URL, "sender", "replay-sender", "replay-receiver", "msg-while-offline")

	// B reconnects
	agentB2 := connectAgent(t, server.URL, "replay-receiver", "receiver")
	defer agentB2.close()

	body, _ := json.Marshal(map[string]interface{}{
		"event_key":      "chat",
		"since_event_id": evt1,
	})
	replayResp, err := http.Post(server.URL+"/events/replay", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatalf("POST /events/replay: %v", err)
	}
	defer replayResp.Body.Close()

	var replayResult struct {
		Events []json.RawMessage `json:"events"`
	}
	json.NewDecoder(replayResp.Body).Decode(&replayResult)

	if len(replayResult.Events) < 1 {
		t.Fatalf("expected at least 1 replayed event, got %d", len(replayResult.Events))
	}

	found := false
	for _, raw := range replayResult.Events {
		var e map[string]interface{}
		json.Unmarshal(raw, &e)
		if e["text"] == "msg-while-offline" {
			found = true
			break
		}
	}
	if !found {
		t.Fatal("replayed events do not contain the offline message")
	}
}

// ═══════════════════════════════════════════════════════════════════════
// T6: Concurrent bidirectional N messages
// ═══════════════════════════════════════════════════════════════════════

func TestA2A_ConcurrentBidirectional(t *testing.T) {
	server, cleanup := testGateway(t)
	defer cleanup()

	agentA := connectAgent(t, server.URL, "conc-alpha", "alpha")
	defer agentA.close()
	agentB := connectAgent(t, server.URL, "conc-bravo", "bravo")
	defer agentB.close()

	const N = 10
	var wg sync.WaitGroup
	var errCount int32

	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < N; i++ {
			resp := postChat(t, server.URL, "alpha", "conc-alpha", "conc-bravo", fmt.Sprintf("A→B-%d", i))
			if _, ok := resp["event_id"].(string); !ok {
				atomic.AddInt32(&errCount, 1)
			}
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < N; i++ {
			resp := postChat(t, server.URL, "bravo", "conc-bravo", "conc-alpha", fmt.Sprintf("B→A-%d", i))
			if _, ok := resp["event_id"].(string); !ok {
				atomic.AddInt32(&errCount, 1)
			}
		}
	}()

	wg.Wait()

	if errCount > 0 {
		t.Fatalf("concurrent sends had %d errors", errCount)
	}

	aReceived := drainInbox(agentA, N, 5*time.Second)
	bReceived := drainInbox(agentB, N, 5*time.Second)

	if len(aReceived) != N {
		t.Fatalf("A received %d/%d messages", len(aReceived), N)
	}
	if len(bReceived) != N {
		t.Fatalf("B received %d/%d messages", len(bReceived), N)
	}

	aTexts := map[string]bool{}
	for _, m := range aReceived {
		if txt, ok := m["text"].(string); ok {
			aTexts[txt] = true
		}
	}
	for i := 0; i < N; i++ {
		key := fmt.Sprintf("B→A-%d", i)
		if !aTexts[key] {
			t.Fatalf("A missing message: %s", key)
		}
	}

	bTexts := map[string]bool{}
	for _, m := range bReceived {
		if txt, ok := m["text"].(string); ok {
			bTexts[txt] = true
		}
	}
	for i := 0; i < N; i++ {
		key := fmt.Sprintf("A→B-%d", i)
		if !bTexts[key] {
			t.Fatalf("B missing message: %s", key)
		}
	}
}

func drainInbox(agent *testAgent, expected int, timeout time.Duration) []map[string]interface{} {
	var msgs []map[string]interface{}
	deadline := time.After(timeout)
	for len(msgs) < expected {
		select {
		case m := <-agent.Inbox:
			msgs = append(msgs, m)
		case <-deadline:
			return msgs
		}
	}
	return msgs
}
