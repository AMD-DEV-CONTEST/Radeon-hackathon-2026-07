package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"strings"
	"time"
)

// ilsBridgeRun starts an HTTP bridge between Cockpit (Tauri desktop) and the Orchestrator.
// Currently pure passthrough — ILS enrichment is DISABLED.
func ilsBridgeRun() {
	port := envOr("BRIDGE_PORT", "8081")
	orchURL := envOr("ORCHESTRATOR_URL", "http://127.0.0.1:8000")

	mux := http.NewServeMux()
	bridge := &bridgeHandler{orchURL: orchURL, client: &http.Client{Timeout: 30 * time.Second}}

	mux.HandleFunc("/tasks", bridge.handleCreateTask)
	mux.HandleFunc("/tasks/", bridge.handleProxyTask)
	mux.HandleFunc("/agents", bridge.handleProxyAgents)
	mux.HandleFunc("/health", bridge.handleHealth)
	mux.HandleFunc("/tasks/stats", bridge.handleProxyStats)

	log.Printf("ILS bridge (cockpit→orch passthrough) :%s → %s", port, orchURL)
	log.Fatal(http.ListenAndServe(":"+port, mux))
}

type bridgeHandler struct {
	orchURL string
	client  *http.Client
}

// handleCreateTask — pure passthrough from Cockpit to Orchestrator.
// Forces task_type="discussion" to bypass ILS validation (enrichment disabled).
func (b *bridgeHandler) handleCreateTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var raw map[string]interface{}
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		writeJSON(w, 400, map[string]interface{}{"error": "invalid JSON: " + err.Error()})
		return
	}

	if _, ok := raw["created_by"]; !ok {
		raw["created_by"] = "cockpit"
	}
	raw["task_type"] = "discussion"

	body, _ := json.Marshal(raw)
	resp, err := b.client.Post(b.orchURL+"/tasks", "application/json", bytes.NewReader(body))
	if err != nil {
		writeJSON(w, 502, map[string]interface{}{"error": "orchestrator unreachable: " + err.Error()})
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}

func (b *bridgeHandler) handleProxyTask(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}
	b.proxy(w, r.URL.Path)
}

func (b *bridgeHandler) handleProxyAgents(w http.ResponseWriter, r *http.Request) {
	b.proxy(w, "/agents")
}

func (b *bridgeHandler) handleProxyStats(w http.ResponseWriter, r *http.Request) {
	b.proxy(w, "/tasks/stats")
}

func (b *bridgeHandler) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, 200, map[string]string{"status": "ok", "service": "ils-bridge", "orch": b.orchURL})
}

func (b *bridgeHandler) proxy(w http.ResponseWriter, path string) {
	resp, err := b.client.Get(b.orchURL + path)
	if err != nil {
		writeJSON(w, 502, map[string]interface{}{"error": "orchestrator unreachable"})
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}

func stringField(m map[string]interface{}, key string) string {
	v, _ := m[key].(string)
	return strings.TrimSpace(v)
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
