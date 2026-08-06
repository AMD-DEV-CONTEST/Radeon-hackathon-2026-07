package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gorilla/websocket"
	"github.com/konspace/unionagents-go/internal/uasclient"
)

// cmdDoctor implements `ils doctor`. It exercises four things:
//
//  1. /health and /events/status over HTTP, so a CI/smoke run
//     can confirm the Gateway process is up without standing up
//     a WS client.
//  2. /boundary on both Gateway and Orchestrator, since boundary
//     drift is a common post-deploy footgun.
//  3. The /register/client HTTP path (via uasclient.RegisterClient),
//     which is what every long-lived ILS consumer (this very CLI,
//     OB, and the eventual Agent runtimes) relies on for an
//     app_id. If register is broken, doctor fails fast.
//  4. A short WS dial + ready handshake, to catch the most common
//     "I registered fine but the WS path is broken" failure mode
//     (the original doctor did this and we keep it).
//
// doctor does NOT exercise reconnect, dedupe, or replay: those
// paths are smoke-tested in the e2e suite, not in this one-shot
// command. Keeping doctor fast and deterministic matters more
// than covering every code path.
func cmdDoctor(args []string) {
	fs := flag.NewFlagSet("doctor", flag.ExitOnError)
	gatewayURL := fs.String("gateway-url", envOr("GATEWAY_URL", "wss://api.upser.pro"), "UAS Gateway base URL")
	orchestratorURL := fs.String("orchestrator-url", envOr("ORCHESTRATOR_URL", "http://111.228.42.18:8000"), "UAS Orchestrator URL")
	jsonOutput := fs.Bool("json", true, "print JSON output")
	if err := fs.Parse(args); err != nil {
		fmt.Fprintf(os.Stderr, "parse flags: %v\n", err)
		os.Exit(2)
	}

	result := map[string]interface{}{
		"status":           "ok",
		"gateway_url":      *gatewayURL,
		"orchestrator_url": *orchestratorURL,
		"protocol": map[string]interface{}{
			"ils_ws":            true,
			"chat_endpoint":     "/api/gateway/chat",
			"ack_replay":        true,
			"http_timeout_sec":  int(ilsHTTPTimeout().Seconds()),
			"short_timeout_sec": int(ilsShortHTTPTimeout().Seconds()),
		},
		"checks": []map[string]interface{}{},
	}
	checks := make([]map[string]interface{}, 0)
	ok := true

	addCheck := func(name string, passed bool, detail interface{}) {
		if !passed {
			ok = false
		}
		checks = append(checks, map[string]interface{}{
			"name":   name,
			"ok":     passed,
			"detail": detail,
		})
	}

	health, healthOK := doctorGetJSON(gatewayHTTPBase(*gatewayURL) + "/health")
	addCheck("gateway_health", healthOK, health)

	status, statusOK := doctorGetJSON(gatewayHTTPBase(*gatewayURL) + "/events/status")
	addCheck("event_status", statusOK, status)

	gatewayBoundary, gatewayBoundaryOK := doctorGetJSON(gatewayHTTPBase(*gatewayURL) + "/boundary")
	addCheck("gateway_boundary", gatewayBoundaryOK, gatewayBoundary)

	orchestratorBoundary, orchestratorBoundaryOK := doctorGetJSON(strings.TrimRight(*orchestratorURL, "/") + "/boundary")
	addCheck("orchestrator_boundary", orchestratorBoundaryOK, orchestratorBoundary)

	// /register/client is the entry point for any long-lived ILS
	// consumer. Test it directly so a regression there is loud.
	hc := &http.Client{Timeout: ilsShortHTTPTimeout()}
	ctx, cancel := context.WithTimeout(context.Background(), ilsShortHTTPTimeout())
	defer cancel()
	appID, token, regErr := uasclient.RegisterClient(ctx, hc, *gatewayURL, "ils-doctor", "uasclient/0.1", "")
	addCheck("register_client", regErr == nil, doctorIdentityDetail(regErr, appID, token))

	wsOK := false
	wsDetail := interface{}("skipped because register_client failed")
	if regErr == nil {
		wsOK, wsDetail = doctorCheckWS(*gatewayURL, appID, token)
	}
	addCheck("ws_ready", wsOK, wsDetail)

	if !ok {
		result["status"] = "fail"
	}
	result["checks"] = checks

	out, _ := json.MarshalIndent(result, "", "  ")
	if *jsonOutput {
		fmt.Println(string(out))
	} else {
		fmt.Println(string(out))
	}
	if !ok {
		os.Exit(1)
	}
}

func doctorGetJSON(url string) (interface{}, bool) {
	client := &http.Client{Timeout: ilsShortHTTPTimeout()}
	resp, err := client.Get(url)
	if err != nil {
		return err.Error(), false
	}
	defer resp.Body.Close()
	out, err := io.ReadAll(resp.Body)
	if err != nil {
		return err.Error(), false
	}
	if resp.StatusCode >= 300 {
		return fmt.Sprintf("HTTP %d: %s", resp.StatusCode, string(out)), false
	}
	var decoded interface{}
	if err := json.Unmarshal(out, &decoded); err != nil {
		return string(out), true
	}
	return decoded, true
}

func doctorCheckWS(gatewayURL, appID, token string) (bool, interface{}) {
	dialer := websocket.Dialer{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}}
	wsURL := strings.TrimRight(gatewayURL, "/")
	if !strings.HasSuffix(wsURL, "/ws") {
		wsURL += "/ws"
	}
	wsURL += "?app_id=" + appID + "&token=" + token
	conn, _, err := dialer.Dial(wsURL, nil)
	if err != nil {
		return false, err.Error()
	}
	defer conn.Close()

	_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	_, raw, err := conn.ReadMessage()
	if err != nil {
		return false, err.Error()
	}
	var evt map[string]interface{}
	if err := json.Unmarshal(raw, &evt); err != nil {
		return false, string(raw)
	}
	connectionID, _ := evt["connection_id"].(string)
	if evt["type"] != "server:welcome" || connectionID == "" {
		return false, evt
	}
	ready := map[string]interface{}{
		"type":          "client.ready",
		"connection_id": connectionID,
		"ts":            time.Now().UTC().Format(time.RFC3339),
	}
	_ = conn.SetWriteDeadline(time.Now().Add(3 * time.Second))
	if err := conn.WriteJSON(ready); err != nil {
		return false, err.Error()
	}
	evt["client_ready_sent"] = true
	return true, evt
}

func doctorIdentityDetail(err error, appID, token string) interface{} {
	if err != nil {
		return err.Error()
	}
	return map[string]interface{}{
		"app_id":         appID,
		"token_received": token != "",
	}
}
