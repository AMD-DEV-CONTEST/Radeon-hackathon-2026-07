package gateway

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestAuthLoginRegistersAgentID(t *testing.T) {
	authEnabled = true
	authUsername = "admin"
	authPassword = "secret"
	authSecret = "test-secret"
	t.Cleanup(func() {
		authEnabled = false
		authUsername = ""
		authPassword = ""
		authSecret = ""
	})

	identity, token, err := LoginClient("127.0.0.1", "admin", "secret", "ob-test", "ob-login-e2e")
	if err != nil {
		t.Fatalf("LoginClient: %v", err)
	}
	if identity == nil {
		t.Fatal("LoginClient returned nil identity")
	}
	if identity.Type != "client" || identity.AgentID != "ob-login-e2e" {
		t.Fatalf("identity: %+v", identity)
	}
	if token == "" {
		t.Fatal("empty token")
	}
	if got := GetAgentAppID("ob-login-e2e"); got != identity.AppID {
		t.Fatalf("GetAgentAppID: got %q want %q", got, identity.AppID)
	}
	if !VerifyAppIDToken(identity.AppID, token) {
		t.Fatal("app token did not verify")
	}
}

func TestAuthLoginClientReceivesAgentRoutedChat(t *testing.T) {
	authEnabled = true
	authUsername = "admin"
	authPassword = "secret"
	authSecret = "test-secret"
	t.Cleanup(func() {
		authEnabled = false
		authUsername = ""
		authPassword = ""
		authSecret = ""
	})

	identity, token, err := LoginClient("127.0.0.1", "admin", "secret", "ob-e2e", "ob-login-route-e2e")
	if err != nil {
		t.Fatalf("LoginClient: %v", err)
	}
	if identity == nil {
		t.Fatal("LoginClient returned nil identity")
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		if !VerifyAppIDToken(r.URL.Query().Get("app_id"), r.URL.Query().Get("token")) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		HandleClientWS(w, r, r.URL.Query().Get("app_id"))
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	wsURL := "ws" + server.URL[len("http"):] + "/ws?app_id=" + identity.AppID + "&token=" + token
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial client ws: %v", err)
	}
	defer conn.Close()

	var welcome map[string]interface{}
	if err := conn.ReadJSON(&welcome); err != nil {
		t.Fatalf("read welcome: %v", err)
	}
	connectionID, _ := welcome["connection_id"].(string)
	if connectionID == "" {
		t.Fatalf("welcome missing connection_id: %#v", welcome)
	}
	if err := conn.WriteJSON(map[string]interface{}{
		"type":          "client.ready",
		"connection_id": connectionID,
	}); err != nil {
		t.Fatalf("write ready: %v", err)
	}

	appID := GetAgentAppID("ob-login-route-e2e")
	if appID != identity.AppID {
		t.Fatalf("GetAgentAppID: got %q want %q", appID, identity.AppID)
	}
	payload, _ := json.Marshal(map[string]interface{}{
		"type":            "chat",
		"event_id":        "evt_ob_login_route",
		"event_key":       "chat",
		"message_id":      "msg_ob_login_route",
		"conv_id":         "conv_ob_login_route",
		"from_agent_id":   "h6-hermes-sz-aliyun",
		"target_agent_id": "ob-login-route-e2e",
		"text":            "OB-LOGIN-ROUTE-PING",
		"ts":              time.Now().UTC().Format(time.RFC3339),
	})
	result := BroadcastToApp(appID, payload)
	if !result.TargetConnected || result.DeliveredToConnections != 1 {
		t.Fatalf("BroadcastToApp result: %+v", result)
	}

	_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var got map[string]interface{}
	if err := conn.ReadJSON(&got); err != nil {
		t.Fatalf("read routed message: %v", err)
	}
	if got["text"] != "OB-LOGIN-ROUTE-PING" || got["target_agent_id"] != "ob-login-route-e2e" {
		t.Fatalf("unexpected payload: %#v", got)
	}
}

func TestRegisterClientWithAgentIDCreatesRoute(t *testing.T) {
	identity, _, err := RegisterClient("ils-inbox-x1-test", "x1-test")
	if err != nil {
		t.Fatalf("RegisterClient: %v", err)
	}
	if identity.Type != "client" {
		t.Fatalf("identity type: got %q want client", identity.Type)
	}
	if identity.AgentID != "x1-test" {
		t.Fatalf("agent id: got %q want x1-test", identity.AgentID)
	}
	if got := GetAgentAppID("x1-test"); got != identity.AppID {
		t.Fatalf("GetAgentAppID: got %q want %q", got, identity.AppID)
	}
	if got := ResolveAgentID("x1-test"); got != "x1-test" {
		t.Fatalf("ResolveAgentID: got %q want x1-test", got)
	}
}

func TestChatRoutesToClientWithAgentID(t *testing.T) {
	identity, token, err := RegisterClient("ils-inbox-x1-e2e", "x1-e2e")
	if err != nil {
		t.Fatalf("RegisterClient: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		if !VerifyAppIDToken(r.URL.Query().Get("app_id"), r.URL.Query().Get("token")) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		HandleClientWS(w, r, r.URL.Query().Get("app_id"))
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	wsURL := "ws" + server.URL[len("http"):] + "/ws?app_id=" + identity.AppID + "&token=" + token
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial client ws: %v", err)
	}
	defer conn.Close()

	var welcome map[string]interface{}
	if err := conn.ReadJSON(&welcome); err != nil {
		t.Fatalf("read welcome: %v", err)
	}
	connectionID, _ := welcome["connection_id"].(string)
	if connectionID == "" {
		t.Fatalf("welcome missing connection_id: %#v", welcome)
	}
	if err := conn.WriteJSON(map[string]interface{}{
		"type":          "client.ready",
		"connection_id": connectionID,
	}); err != nil {
		t.Fatalf("write ready: %v", err)
	}

	appID := GetAgentAppID("x1-e2e")
	if appID == "" {
		t.Fatal("GetAgentAppID returned empty app id")
	}
	payload, _ := json.Marshal(map[string]interface{}{
		"type":            "chat",
		"event_id":        "evt_client_route",
		"event_key":       "chat",
		"message_id":      "msg_client_route",
		"conv_id":         "conv_client_route",
		"from_agent_id":   "h5",
		"target_agent_id": "x1-e2e",
		"text":            "SELFTEST-PING",
		"ts":              time.Now().UTC().Format(time.RFC3339),
	})
	result := BroadcastToApp(appID, payload)
	if !result.TargetConnected || result.DeliveredToConnections != 1 {
		t.Fatalf("BroadcastToApp result: %+v", result)
	}

	_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var got map[string]interface{}
	if err := conn.ReadJSON(&got); err != nil {
		t.Fatalf("read routed message: %v", err)
	}
	if got["text"] != "SELFTEST-PING" || got["target_agent_id"] != "x1-e2e" {
		t.Fatalf("unexpected payload: %#v", got)
	}
}

func TestRetryUnackedEvents(t *testing.T) {
	// Clean up event state
	eventMu.Lock()
	eventDelivery = map[string]*eventDeliveryRecord{}
	eventBuffer = nil
	eventMu.Unlock()

	// Set up a connected client so BroadcastToApp has a target
	identity, token, err := RegisterClient("retry-test-client", "retry-test-agent")
	if err != nil {
		t.Fatalf("RegisterClient: %v", err)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		if !VerifyAppIDToken(r.URL.Query().Get("app_id"), r.URL.Query().Get("token")) {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		HandleClientWS(w, r, r.URL.Query().Get("app_id"))
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	wsURL := "ws" + server.URL[len("http"):] + "/ws?app_id=" + identity.AppID + "&token=" + token
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial ws: %v", err)
	}
	defer conn.Close()

	var welcome map[string]interface{}
	if err := conn.ReadJSON(&welcome); err != nil {
		t.Fatalf("read welcome: %v", err)
	}
	connID, _ := welcome["connection_id"].(string)
	if err := conn.WriteJSON(map[string]interface{}{
		"type":          "client.ready",
		"connection_id": connID,
	}); err != nil {
		t.Fatalf("write ready: %v", err)
	}

	eventID := "evt_retry_test_001"
	payload, _ := json.Marshal(map[string]interface{}{
		"type":     "chat",
		"event_id": eventID,
		"text":     "RETRY-TEST",
	})

	// Simulate: message delivered to 1 connection, stored, but never acked
	appID := identity.AppID
	BroadcastToApp(appID, payload)
	StoreEventForReplay(eventID, "chat", payload)
	RecordEventDeliveryRouted(eventID, "chat", 1, appID, "agent_app")

	// Drain the first message from WS
	conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var firstMsg map[string]interface{}
	if err := conn.ReadJSON(&firstMsg); err != nil {
		t.Fatalf("read first message: %v", err)
	}

	// Verify event record exists with Pending > 0
	eventMu.Lock()
	rec := eventDelivery[eventID]
	if rec == nil {
		eventMu.Unlock()
		t.Fatal("event record not found")
	}
	if rec.Pending != 1 {
		eventMu.Unlock()
		t.Fatalf("expected Pending=1, got %d", rec.Pending)
	}
	// Force LastUpdated to 31s ago to trigger retry
	rec.LastUpdated = time.Now().UTC().Add(-31 * time.Second)
	eventMu.Unlock()

	// Run retry logic
	retryUnackedEvents()

	// Read the retried message from WS
	conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	var retried map[string]interface{}
	if err := conn.ReadJSON(&retried); err != nil {
		t.Fatalf("read retried message: %v", err)
	}
	if retried["text"] != "RETRY-TEST" {
		t.Fatalf("unexpected retried payload: %#v", retried)
	}

	// Verify retry count incremented
	eventMu.Lock()
	if rec.RetryCount != 1 {
		eventMu.Unlock()
		t.Fatalf("expected RetryCount=1, got %d", rec.RetryCount)
	}
	eventMu.Unlock()
}

func TestRetryStopsAfterMaxRetries(t *testing.T) {
	eventMu.Lock()
	eventDelivery = map[string]*eventDeliveryRecord{}
	eventBuffer = nil
	eventMu.Unlock()

	eventID := "evt_retry_max_test"
	payload, _ := json.Marshal(map[string]interface{}{"text": "MAX-RETRY"})

	StoreEventForReplay(eventID, "chat", payload)

	eventMu.Lock()
	eventDelivery[eventID] = &eventDeliveryRecord{
		EventID:     eventID,
		EventKey:    "chat",
		Delivered:   4,
		Acked:       0,
		Pending:     4,
		RetryCount:  3,
		MaxRetries:  3,
		Route:       "ob_clients",
		LastUpdated: time.Now().UTC().Add(-31 * time.Second),
		CreatedAt:   time.Now().UTC().Add(-2 * time.Minute),
		Consumers:   map[string]string{},
	}
	eventMu.Unlock()

	retryUnackedEvents()

	eventMu.Lock()
	rec := eventDelivery[eventID]
	if rec.RetryCount != 3 {
		eventMu.Unlock()
		t.Fatalf("expected RetryCount=3 (no more retries), got %d", rec.RetryCount)
	}
	eventMu.Unlock()
}

func TestRetryPayloadExpired(t *testing.T) {
	eventMu.Lock()
	eventDelivery = map[string]*eventDeliveryRecord{}
	eventBuffer = nil
	eventMu.Unlock()

	eventID := "evt_expired_payload"

	eventMu.Lock()
	eventDelivery[eventID] = &eventDeliveryRecord{
		EventID:     eventID,
		EventKey:    "chat",
		Delivered:   1,
		Acked:       0,
		Pending:     1,
		RetryCount:  0,
		MaxRetries:  3,
		Route:       "ob_clients",
		LastUpdated: time.Now().UTC().Add(-31 * time.Second),
		CreatedAt:   time.Now().UTC().Add(-6 * time.Minute),
		Consumers:   map[string]string{},
	}
	eventMu.Unlock()

	retryUnackedEvents()

	eventMu.Lock()
	rec := eventDelivery[eventID]
	if rec.RetryCount != rec.MaxRetries {
		eventMu.Unlock()
		t.Fatalf("expected RetryCount=%d (payload expired), got %d", rec.MaxRetries, rec.RetryCount)
	}
	eventMu.Unlock()
}

func TestLookupEventPayload(t *testing.T) {
	eventMu.Lock()
	eventBuffer = nil
	eventMu.Unlock()

	payload := json.RawMessage(`{"text":"lookup-test"}`)
	StoreEventForReplay("evt_lookup", "chat", payload)

	got := lookupEventPayload("evt_lookup")
	if got == nil {
		t.Fatal("expected to find payload, got nil")
	}
	if string(got) != `{"text":"lookup-test"}` {
		t.Fatalf("unexpected payload: %s", string(got))
	}

	got2 := lookupEventPayload("evt_nonexistent")
	if got2 != nil {
		t.Fatalf("expected nil for nonexistent event, got: %s", string(got2))
	}
}

// ── Phase 1A: one-time agent registration keys ────────────────────────────

func resetAgentKeys(t *testing.T) {
	t.Helper()
	agentKeys = &sync.Map{}
	t.Cleanup(func() { agentKeys = &sync.Map{} })
}

func TestGenerateAgentKeyHappyPath(t *testing.T) {
	resetAgentKeys(t)

	key, err := GenerateAgentKey("z1-agent")
	if err != nil {
		t.Fatalf("GenerateAgentKey: %v", err)
	}
	if key == "" {
		t.Fatal("empty key")
	}
	if len(key) != len("sk-xg-")+64 {
		t.Fatalf("key length: got %d want %d", len(key), len("sk-xg-")+64)
	}
	if key[:6] != "sk-xg-" {
		t.Fatalf("key prefix: got %q", key[:6])
	}

	// Same codename → conflict while a key is outstanding.
	if _, err := GenerateAgentKey("z1-agent"); err == nil {
		t.Fatal("expected error generating a second key for same codename, got nil")
	}

	// Empty codename rejected.
	if _, err := GenerateAgentKey(""); err == nil {
		t.Fatal("expected error for empty codename, got nil")
	}
}

func TestValidateAndConsumeAgentKey(t *testing.T) {
	resetAgentKeys(t)

	key, err := GenerateAgentKey("z1-validate")
	if err != nil {
		t.Fatalf("GenerateAgentKey: %v", err)
	}

	if !ValidateAgentKey("z1-validate", key) {
		t.Fatal("expected key to validate")
	}
	if ValidateAgentKey("z1-validate", "sk-xg-wrong") {
		t.Fatal("expected wrong key to be rejected")
	}
	if ValidateAgentKey("z1-validate", "") {
		t.Fatal("expected empty key to be rejected")
	}
	if ValidateAgentKey("unknown-agent", key) {
		t.Fatal("expected unknown agent to be rejected")
	}

	ConsumeAgentKey("z1-validate")
	if ValidateAgentKey("z1-validate", key) {
		t.Fatal("expected key to be invalid after consume")
	}

	// Consuming a non-existent key is a no-op.
	ConsumeAgentKey("z1-validate")
}

func TestGenerateAgentKeyRejectsRegisteredCodename(t *testing.T) {
	resetAgentKeys(t)

	identity, _, err := RegisterAgent("z1-taken", "Z1 Taken", "generic")
	if err != nil {
		t.Fatalf("RegisterAgent: %v", err)
	}
	if identity == nil {
		t.Fatal("nil identity")
	}
	t.Cleanup(func() {
		agentIDToAppID.Delete("z1-taken")
		agentNameToAppID.Delete("Z1 Taken")
		identityDB.Delete(identity.AppID)
	})

	if _, err := GenerateAgentKey("z1-taken"); err == nil {
		t.Fatal("expected error generating key for already-registered codename")
	}
}

// TestRegisterAgentEndpointKeyGate exercises the full HTTP path:
// no key → 401, wrong key → 401, valid key → 200 + key consumed.
func TestRegisterAgentEndpointKeyGate(t *testing.T) {
	resetAgentKeys(t)

	mux := http.NewServeMux()
	mux.HandleFunc("POST /register/agent", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			AgentID   string `json:"agent_id"`
			AgentName string `json:"agent_name"`
			Key       string `json:"key"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad body", http.StatusBadRequest)
			return
		}
		if !ValidateAgentKey(req.AgentID, req.Key) {
			http.Error(w, "invalid or missing agent key", http.StatusUnauthorized)
			return
		}
		identity, token, err := RegisterAgent(req.AgentID, req.AgentName, "generic")
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		ConsumeAgentKey(req.AgentID)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]string{
			"app_id": identity.AppID,
			"token":  token,
		})
	})
	server := httptest.NewServer(mux)
	defer server.Close()

	post := func(body map[string]string) (*http.Response, map[string]string) {
		raw, _ := json.Marshal(body)
		resp, err := http.Post(server.URL+"/register/agent", "application/json", bytes.NewReader(raw))
		if err != nil {
			t.Fatalf("post: %v", err)
		}
		defer resp.Body.Close()
		var out map[string]string
		_ = json.NewDecoder(resp.Body).Decode(&out)
		return resp, out
	}

	// 1) No key → 401.
	resp, _ := post(map[string]string{"agent_id": "z1-http", "agent_name": "Z1 HTTP"})
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("no key: got %d want 401", resp.StatusCode)
	}

	// 2) Wrong key → 401.
	key, err := GenerateAgentKey("z1-http")
	if err != nil {
		t.Fatalf("GenerateAgentKey: %v", err)
	}
	resp, _ = post(map[string]string{"agent_id": "z1-http", "agent_name": "Z1 HTTP", "key": "sk-xg-wrong"})
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("wrong key: got %d want 401", resp.StatusCode)
	}

	// 3) Valid key → 200 and the key is consumed.
	resp, out := post(map[string]string{"agent_id": "z1-http", "agent_name": "Z1 HTTP", "key": key})
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("valid key: got %d want 200", resp.StatusCode)
	}
	if out["app_id"] == "" || out["token"] == "" {
		t.Fatalf("missing app_id/token in response: %v", out)
	}
	if ValidateAgentKey("z1-http", key) {
		t.Fatal("key should have been consumed after successful registration")
	}

	// 4) Reusing the same key → 401.
	resp, _ = post(map[string]string{"agent_id": "z1-http", "agent_name": "Z1 HTTP", "key": key})
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("reused key: got %d want 401", resp.StatusCode)
	}
}
